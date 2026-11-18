#!/usr/bin/env python3
"""Read-only v12 PAK → SQLite/FlatBuffers → balance analysis helpers."""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import re
import sqlite3
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from balance.wuwa_pak import WuwaPak, OodleDecoder
from balance.wuwa_analysis import run_analysis, sha, write_json


def local_path(value: str) -> Path:
    if sys.platform != "win32" and re.match(r"^[A-Za-z]:[\\/]", value):
        return Path("/mnt/" + value[0].lower() + "/" + value[3:].replace("\\", "/")).resolve()
    return Path(value).resolve()


def key_for(pak: Path, key_map: Path | None) -> bytes | None:
    if key_map is None:
        return None
    mapping = json.loads(key_map.read_text(encoding="utf-8"))
    candidates = {v for k, v in mapping.items() if pak.as_posix().endswith(k.replace("\\", "/"))}
    if len(candidates) != 1:
        raise ValueError("Key map must match this package exactly once")
    return bytes.fromhex(next(iter(candidates)).removeprefix("0x"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    scan = commands.add_parser("scan", help="Inventory Unreal PAK footers without keys")
    scan.add_argument("--source", type=local_path, required=True)
    scan.add_argument("--out", type=local_path, required=True)
    for command in ("list", "extract"):
        c = commands.add_parser(command)
        c.add_argument("--pak", type=local_path, required=True)
        c.add_argument("--key-map", type=local_path)
        c.add_argument("--match", default=".", help="Regular expression matched against archive paths")
        c.add_argument("--out", type=local_path, required=True)
        if command == "extract":
            c.add_argument("--oodle-lib", type=local_path)
    snapshot = commands.add_parser("snapshot", help="Export BLOBs and SQLite key columns for the schema decoder")
    snapshot.add_argument("--db-root", type=local_path, required=True)
    snapshot.add_argument("--out", type=local_path, required=True)
    report = commands.add_parser("report", help="Verify evidence hashes and calculate costs")
    report.add_argument("--tables", type=local_path, required=True)
    report.add_argument("--extracted", type=local_path, required=True, help="Extracted Client/Content/Aki directory")
    report.add_argument("--manifest", type=local_path, required=True)
    report.add_argument("--out", type=local_path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("출력이 이미 있습니다. 새 회차 경로를 지정하세요.")
    if args.command == "scan":
        rows = []
        for file in sorted(args.source.rglob("*.pak")):
            if file.stat().st_size < 221:
                continue
            with file.open("rb") as f:
                f.seek(-221, 2)
                tail = f.read()
            if tail[17:21] != b"\xe1\x12\x6f\x5a":
                continue
            version = struct.unpack_from("<I", tail, 21)[0]
            offset, size = struct.unpack_from("<QQ", tail, 25)
            rows.append({"path": str(file), "bytes": file.stat().st_size, "version": version,
                         "index_encrypted": bool(tail[16]), "index_offset": offset,
                         "index_size": size, "index_sha1": tail[41:61].hex()})
        args.out.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.out, rows)
        print(f"Unreal PAK {len(rows)}개 → {args.out}")
    elif args.command in ("list", "extract"):
        pak = WuwaPak(args.pak, key_for(args.pak, args.key_map))
        pattern = re.compile(args.match)
        names = [n for n in pak.entries if pattern.search(n)]
        if not names:
            raise ValueError("No entries match; nothing extracted")
        if args.command == "list":
            args.out.parent.mkdir(parents=True, exist_ok=True)
            write_json(args.out, {n: pak.entries[n] for n in names})
        else:
            if args.out.is_relative_to(args.pak.parent):
                raise ValueError("Extraction output must be outside the source package directory")
            decoder = OodleDecoder(args.oodle_lib) if args.oodle_lib else None
            args.out.mkdir(parents=True)
            records = [pak.save(n, args.out, decoder) for n in names]
            write_json(args.out / "추출_명세.json", records)
        print(f"{len(names)}개 → {args.out}")
    elif args.command == "snapshot":
        tables = []
        for path in sorted(args.db_root.glob("*.db")):
            with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
                db.row_factory = sqlite3.Row
                if db.execute("pragma quick_check").fetchone()[0] != "ok":
                    raise ValueError(f"SQLite integrity check failed: {path}")
                digest = sha(path)
                for (table,) in db.execute("select name from sqlite_master where type='table'"):
                    query = 'select * from "' + table.replace('"', '""') + '"'
                    rows = [{k: base64.b64encode(v).decode() if isinstance(v, bytes) else v
                             for k, v in dict(r).items()} for r in db.execute(query)]
                    tables.append({"database": path.name, "name": table, "rows": rows, "sha256": digest})
        args.out.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.out, {"tables": tables})
        print(f"{len(tables)}개 테이블 → {args.out}")
    else:
        result = run_analysis(args.tables, args.extracted, args.manifest, args.out)
        print(f"{result['status']} → {args.out / '명조_보상성장_분석.html'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, sqlite3.Error) as error:
        print(f"분석 오류: {error}", file=sys.stderr)
        raise SystemExit(1)
