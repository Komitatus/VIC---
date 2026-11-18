import hashlib
import struct
import tempfile
import unittest
from pathlib import Path
import zlib

from balance.wuwa_analysis import echo_costs
from balance.wuwa_pak import PakError, Reader, WuwaPak, normalize_path


def fstring(value):
    value = value.encode() + b"\0"
    return struct.pack("<i", len(value)) + value


def fixture(path, payload=b"local table data", key=None, partial=0, compressed=False):
    """Synthetic independent archive with known plaintext and Wuwa field order."""
    def encrypt(data):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        c = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
        return c.update(data) + c.finalize()

    def padded(data):
        return data + b"\0" * (-len(data) % 16)

    data = zlib.compress(payload) if compressed else payload
    stored_size = len(data)
    header = 73 if compressed else 53
    if key:
        data = padded(data)
        size = len(data) if partial == 0 else min(2048, len(data))
        data = encrypt(data[:size]) + data[size:]
    content = b"\0" * header + data
    bits = 0xE0000000 | (0x10000000 if key else 0)
    if compressed:
        bits |= 0x00400001  # compression slot 1 and one block in Wuwa layout
    encoded = struct.pack("<IBII", bits, partial, len(payload), 0)
    if compressed:
        encoded += struct.pack("<I", len(data))
        if key:
            encoded += struct.pack("<I", stored_size)
    directory = struct.pack("<I", 1) + fstring("") + struct.pack("<I", 1) + fstring("table.bin") + struct.pack("<i", 0)
    if key:
        directory = padded(directory)
    digest = hashlib.sha1(directory).digest()

    def index(offset):
        return (fstring("../../../Client/") + struct.pack("<IQIIQQ", 1, 0, 0, 1, offset, len(directory))
                + digest + struct.pack("<I", len(encoded)) + encoded + struct.pack("<I", 0))
    initial = index(0)
    idx_size = len(padded(initial)) if key else len(initial)
    index_data = index(len(content) + idx_size)
    if key:
        index_data = padded(index_data)
    footer = (b"\0"*16 + bytes([bool(key)]) + struct.pack("<IIQQ", 0x5A6F12E1, 12, len(content), len(index_data))
              + hashlib.sha1(index_data).digest() + (b"Zlib"+b"\0"*28 if compressed else b"\0"*32) + b"\0"*128)
    path.write_bytes(content + (encrypt(index_data) if key else index_data) + (encrypt(directory) if key else directory) + footer)


class PakTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "sample.pak"

    def test_plain_extract_and_source_unchanged(self):
        fixture(self.path)
        original = self.path.read_bytes()
        pak = WuwaPak(self.path)
        result = pak.save("Client/table.bin", Path(self.temp.name)/"out")
        self.assertEqual(Path(result["output"]).read_bytes(), b"local table data")
        self.assertEqual(self.path.read_bytes(), original)
        with self.assertRaises(FileExistsError):
            pak.save("Client/table.bin", Path(self.temp.name)/"out")

    def test_zlib_block(self):
        data = b"sqlite evidence" * 400
        fixture(self.path, data, compressed=True)
        self.assertEqual(WuwaPak(self.path).extract("Client/table.bin"), data)

    def test_rejects_corrupt_index_and_wrong_format(self):
        fixture(self.path)
        data = bytearray(self.path.read_bytes())
        offset = struct.unpack_from("<Q", data, len(data)-221+25)[0]
        data[offset+4] ^= 1
        self.path.write_bytes(data)
        with self.assertRaisesRegex(PakError, "SHA1"):
            WuwaPak(self.path)
        fixture(self.path)
        data = bytearray(self.path.read_bytes())
        struct.pack_into("<I", data, len(data)-221+21, 11)
        self.path.write_bytes(data)
        with self.assertRaisesRegex(PakError, "v12"):
            WuwaPak(self.path)

    def test_encrypted_index_and_partial_file(self):
        try:
            import cryptography
        except ImportError:
            self.skipTest("Optional cryptography dependency not installed")
        data = bytes(range(256))*20
        fixture(self.path, data, key=b"k"*32, partial=2)
        self.assertEqual(WuwaPak(self.path, b"k"*32).extract("Client/table.bin"), data)
        with self.assertRaises(PakError):
            WuwaPak(self.path, b"x"*32)
        with self.assertRaises(PakError):
            WuwaPak(self.path)

    def test_path_boundaries_and_truncated_strings(self):
        self.assertEqual(normalize_path("../../../Client//data.bin"), "Client/data.bin")
        for path in ("/tmp/data", "Client/../data", "C:/data", "Client\\data"):
            with self.assertRaises(PakError):
                normalize_path(path)
        with self.assertRaises(PakError):
            Reader(struct.pack("<i", 5)+b"a").string()


class GrowthTests(unittest.TestCase):
    def test_refund_rounds_down_and_cost_rounds_up(self):
        rows = [{"Level":0,"Exp":0},{"Level":1,"Exp":5},{"Level":2,"Exp":8}]
        quality = {"LevelLimit":2,"SlotUnlockLevel":[1,2],"IdentifyCost":{"99":3},"IdentifyCoin":7}
        results = echo_costs(rows,quality,100,750,300)
        self.assertEqual(results[-1]["cumulative_exp"], 13)
        self.assertEqual(results[-1]["incremental_exp"], 8)
        self.assertEqual(results[-1]["level_coins"], 2)
        self.assertEqual(results[-1]["refunded_exp"], 9)
        self.assertEqual(results[-1]["lost_exp"], 4)
        self.assertEqual(results[-1]["refunded_tuners"], 1)
        self.assertEqual(results[-1]["lost_tuners"], 5)

    def test_missing_levels_not_interpolated(self):
        quality = {"LevelLimit":2,"SlotUnlockLevel":[2],"IdentifyCost":{"99":3},"IdentifyCoin":7}
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            echo_costs([{"Level":0,"Exp":0},{"Level":2,"Exp":8}],quality,100,750,300)


if __name__ == "__main__":
    unittest.main()
