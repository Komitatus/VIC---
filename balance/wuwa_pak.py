"""Read-only Wuthering Waves v12 PAK adapter (not a general Unreal reader).

Format references: CUE4Parse FPakEntry and PartialEncryptionPakFileReader,
https://github.com/FabianFG/CUE4Parse/tree/master/CUE4Parse/UE4/Pak
https://github.com/FabianFG/CUE4Parse/blob/master/CUE4Parse/GameTypes/Misc/UE4/Paks/PartialEncryptionPakFileReader.cs
Keys are supplied externally; no network access or game process interaction.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path, PurePosixPath
import struct
import zlib


class PakError(ValueError):
    pass


class OodleDecoder:
    """Optional local decoder. Library acquisition is explicitly external."""
    def __init__(self, path: Path | str):
        import ctypes
        self.ctypes = ctypes
        self.library = ctypes.CDLL(str(Path(path).resolve()))
        self.function = self.library.OodleLZ_Decompress
        self.function.restype = ctypes.c_ssize_t
        self.function.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32,
                                  ctypes.c_uint32, ctypes.c_void_p, ctypes.c_size_t,
                                  ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.c_uint32]

    def __call__(self, data: bytes, size: int) -> bytes:
        if not 0 <= size <= 268435456:
            raise PakError("Invalid decompression block size")
        target = self.ctypes.create_string_buffer(size)
        result = self.function(data, len(data), target, size, 1, 1, 0,
                               None, 0, None, None, None, 0, 3)
        if result != size:
            raise PakError(f"Oodle decompression failed: {result}, expected {size}")
        return target.raw


class Reader:
    def __init__(self, data: bytes):
        self.stream = io.BytesIO(data)

    def read(self, size: int) -> bytes:
        if size < 0:
            raise PakError("Negative read size")
        value = self.stream.read(size)
        if len(value) != size:
            raise PakError("Truncated PAK index")
        return value

    def num(self, fmt: str) -> int:
        return struct.unpack("<" + fmt, self.read(struct.calcsize("<" + fmt)))[0]

    def string(self) -> str:
        length = self.num("i")
        if abs(length) > 1048576:
            raise PakError("Invalid FString length (wrong key or unsupported format)")
        if not length:
            return ""
        value = self.read(abs(length) * (2 if length < 0 else 1))
        return value.decode("utf-16le" if length < 0 else "utf-8").rstrip("\0")


def align16(value: int) -> int:
    return (value + 15) & ~15


def normalize_path(value: str) -> str:
    # UE mount points conventionally start ../../../; strip that prefix only.
    while value.startswith("../"):
        value = value[3:]
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value or ":" in value:
        raise PakError("Unsafe archive path")
    return str(path)


class WuwaPak:
    def __init__(self, path: Path | str, key: bytes | None = None):
        self.path = Path(path)
        self.key = key
        self.size = self.path.stat().st_size
        tail = self.read_at(self.size - 221, 221)
        if tail[17:21] != b"\xe1\x12\x6f\x5a":
            raise PakError("Unsupported PAK footer")
        self.version = struct.unpack_from("<I", tail, 21)[0]
        if self.version != 12:
            raise PakError(f"Only Wuthering Waves PAK v12 supported: {self.version}")
        self.encrypted = bool(tail[16])
        self.index_offset, self.index_size = struct.unpack_from("<QQ", tail, 25)
        self.index_sha1 = tail[41:61].hex()
        self.compressions = ["None"] + [tail[61+i*32:93+i*32].split(b"\0")[0].decode("ascii") for i in range(5)]
        raw = self.read_at(self.index_offset, self.index_size)
        data = self.decrypt(raw) if self.encrypted else raw
        if hashlib.sha1(data).hexdigest() != self.index_sha1:
            raise PakError("Primary index SHA1 mismatch")
        r = Reader(data)
        self.mount = r.string()
        self.count = r.num("I")
        self.seed = r.num("Q")
        directory_data = None
        for name in ("path_hash", "directory"):
            if r.num("I"):
                offset, size, digest = r.num("Q"), r.num("Q"), r.read(20)
                if name == "directory":
                    raw = self.read_at(offset, size)
                    directory_data = self.decrypt(raw) if self.encrypted else raw
                    if hashlib.sha1(directory_data).digest() != digest:
                        raise PakError("Directory index SHA1 mismatch")
        self.encoded = r.read(r.num("I"))
        if r.num("I"):
            raise PakError("Non-encoded entries not supported")
        if directory_data is None:
            raise PakError("No full directory index")
        r = Reader(directory_data)
        self.entries = {}
        for _ in range(r.num("I")):
            directory = r.string()
            for _ in range(r.num("I")):
                filename, offset = r.string(), r.num("i")
                if offset == -2147483648:
                    continue
                if offset < 0:
                    raise PakError("Non-encoded entry reference")
                name = normalize_path(self.mount + directory + filename)
                if name in self.entries:
                    raise PakError("Duplicate archive path")
                self.entries[name] = self.decode_entry(offset)

    def read_at(self, offset: int, size: int) -> bytes:
        if offset < 0 or size < 0 or offset + size > self.size:
            raise PakError("Read exceeds package boundaries")
        with self.path.open("rb") as f:
            f.seek(offset)
            value = f.read(size)
        if len(value) != size:
            raise PakError("Truncated package")
        return value

    def decrypt(self, value: bytes) -> bytes:
        if self.key is None or len(self.key) != 32:
            raise PakError("AES-256 key required")
        if len(value) % 16:
            raise PakError("Unaligned encrypted data")
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        except ImportError as exc:
            raise PakError("Encrypted PAK extraction requires cryptography") from exc
        decryptor = Cipher(algorithms.AES(self.key), modes.ECB()).decryptor()
        return decryptor.update(value) + decryptor.finalize()

    def decode_entry(self, index_offset: int) -> dict:
        if not 0 <= index_offset < len(self.encoded):
            raise PakError("Entry index out of range")
        r = Reader(self.encoded[index_offset:index_offset+1048576])
        source = r.num("I")
        # Wuwa v12 rearranges the stock bitfield and swaps the first two values.
        bits = ((source >> 16) & 63) | ((source & 65535) << 6)
        bits |= ((source >> 28) & 1) << 22
        bits |= (source & 0x0FC00000) << 1
        bits |= (source & 0xC0000000) >> 1
        bits |= (source & 0x20000000) << 2
        custom = r.num("B")
        block_size = r.num("I") if bits & 63 == 63 else (bits & 63) << 11
        method = (bits >> 23) & 63
        if method >= len(self.compressions):
            raise PakError("Unknown compression method")
        length = r.num("I" if bits & (1 << 31) else "Q")
        offset = r.num("I" if bits & (1 << 30) else "Q")
        compressed = r.num("I" if bits & (1 << 29) else "Q") if method else length
        encrypted = bool(bits & (1 << 22))
        count = (bits >> 6) & 65535
        header = 53 + (4 + 16 * count if method else 0)
        blocks = []
        cursor = offset + header
        for _ in range(count):
            size = compressed if count == 1 and not encrypted else r.num("I")
            blocks.append((cursor, size))
            cursor += align16(size) if encrypted else size
        if custom not in (0, 1, 2, 4):
            raise PakError(f"Unknown partial encryption mode {custom}")
        return dict(offset=offset, size=length, compressed_size=compressed,
                    compression=self.compressions[method], encrypted=encrypted,
                    custom=custom, header_size=header, block_size=length if count == 1 else block_size,
                    blocks=blocks, encoded_offset=index_offset)

    def extract(self, name: str, oodle=None) -> bytes:
        e = self.entries[name]
        limit = {0: 2**63-1, 1: 0x200000, 2: 0x800, 4: 0}[e["custom"]] if e["encrypted"] else 0
        parts = []
        blocks = e["blocks"] or [(e["offset"] + e["header_size"], e["size"])]
        for offset, size in blocks:
            padded = align16(size) if e["encrypted"] else size
            encrypted_length = min(limit, padded)
            data = self.read_at(offset, padded)
            if encrypted_length:
                data = self.decrypt(data[:encrypted_length]) + data[encrypted_length:]
            limit = max(0, limit - padded)
            data = data[:size]
            if e["compression"] == "Zlib":
                data = zlib.decompress(data)
            elif e["compression"] == "Oodle" and oodle is not None:
                expected = min(e["block_size"], e["size"] - sum(map(len, parts)))
                data = oodle(data, expected)
            elif e["compression"] != "None":
                raise PakError(f"Decoder required: {e['compression']}")
            parts.append(data)
        result = b"".join(parts)
        if len(result) != e["size"]:
            raise PakError("Extracted length mismatch")
        return result

    def save(self, name: str, output: Path, oodle=None) -> dict:
        root = output.resolve()
        target = (root / normalize_path(name)).resolve()
        if not target.is_relative_to(root):
            raise PakError("Extraction path leaves output directory")
        if target.exists():
            raise FileExistsError(target)
        data = self.extract(name, oodle)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {"package": str(self.path), "package_bytes": self.size,
                "package_index_sha1": self.index_sha1, "entry": name,
                "entry_metadata": self.entries[name], "output": str(target),
                "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
