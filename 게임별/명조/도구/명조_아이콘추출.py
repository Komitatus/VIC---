#!/usr/bin/env python3
"""Extract the exact configured Wuwa UI textures and decode them to local PNGs.

BC7Prep is decoded using the separately recorded CUE4Parse reference helper.
This adapter validates dimensions, block counts, payload sizes and offsets;
unsupported texture layouts stay unresolved rather than receiving guessed art.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import struct
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from balance.wuwa_pak import WuwaPak, OodleDecoder


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def save(p, value):
    Path(p).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def win(p):
    value = str(Path(p).resolve())
    if not value.startswith('/mnt/c/'):
        raise ValueError('The Windows helper requires a C: path')
    return 'C:/' + value[7:]


def package_path(path):
    if not path.startswith('/Game/'):
        raise ValueError('Unsupported asset mount')
    return 'Client/Content/' + path[6:].split('.')[0]


def texture_layout(asset, export):
    """Recognize this installed build's validated UI texture export layouts."""
    formats = list(re.finditer(rb'PF_[A-Za-z0-9]+\x00', export))
    for hit in reversed(formats):
        pos = hit.start()
        if pos < 16 or struct.unpack_from('<I', export, pos - 4)[0] != len(hit.group()):
            continue
        width, height, slices = struct.unpack_from('<III', export, pos - 16)
        if not (0 < width <= 8192 and 0 < height <= 8192 and slices == 1):
            continue
        fmt = hit.group()[:-1].decode()
        blocks = ((width + 3) // 4) * ((height + 3) // 4)
        if b'OodleTextureStorageProvider' in asset and fmt == 'PF_BC7':
            needle = struct.pack('<4I', width, height, 1, 1)
            start = export.find(needle)
            while start >= 0:
                if start + 84 <= len(export):
                    version, flags = struct.unpack_from('<II', export, start + 16)
                    modes = struct.unpack_from('<10I', export, start + 24)
                    bulk_flags, count, size, offset = struct.unpack_from('<IIIq', export, start + 64)
                    expected = sum(v * (4 if i == 9 else 16) for i, v in enumerate(modes)) + (sum(modes) + 1) // 2
                    if (version == 1980 and sum(modes) == blocks and count == size == expected
                            and bulk_flags == 0x48 and offset == len(asset) + start + 84
                            and start + 84 + size <= len(export)):
                        return dict(format=fmt, width=width, height=height, codec='BC7Prep',
                                    offset=start + 84, length=size, modes=modes, flags=flags)
                start = export.find(needle, start + 1)
        end = hit.end()
        if end + 32 > len(export):
            continue
        first, mips, cooked = struct.unpack_from('<III', export, end)
        bulk_flags, count, size, offset = struct.unpack_from('<IIIq', export, end + 12)
        expected = {'PF_BC7': blocks * 16, 'PF_DXT1': blocks * 8, 'PF_DXT5': blocks * 16,
                    'PF_B8G8R8A8': width * height * 4, 'PF_G8': width * height}.get(fmt)
        data_offset = end + 32
        if (mips >= 1 and cooked == 1 and bulk_flags == 0x48 and count == size == expected
                and data_offset + size + 12 <= len(export)
                and struct.unpack_from('<III', export, data_offset + size) == (width, height, 1)):
            return dict(format=fmt, width=width, height=height, codec=fmt,
                        offset=data_offset, length=size)
    raise ValueError('Unrecognized UI texture layout')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--base', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--libs', type=Path, required=True)
    ap.add_argument('--helper', type=Path, required=True)
    args = ap.parse_args()
    base, out = args.base.resolve(), args.out.resolve()
    if out.exists():
        ap.error('Output must be new')
    out.mkdir(parents=True)
    raw_root, png_root = out / 'raw', out / 'png'
    raw_root.mkdir(); png_root.mkdir()
    sys.path.insert(0, str(args.libs.resolve()))
    import texture2ddecoder
    from PIL import Image
    tables = base / '추출/20261118_클라이언트/테이블_3'
    more = base / '추출/20261118_콘텐츠기획/테이블_등록부'
    evidence = load(base / '결과/20261118_콘텐츠기획/콘텐츠_근거.json')
    definitions = load(base / '결과/20261118_콘텐츠기획/기획_정의.json')['plans']
    lang_path = base / '추출/20261118_클라이언트/원본추출/Client/Content/Aki/ConfigDB/ko/lang_multi_text.db'
    lang = sqlite3.connect(lang_path.as_uri() + '?mode=ro', uri=True)
    def text(key):
        r = lang.execute('select Content from MultiText where Id=?', (key,)).fetchone()
        return r[0] if r and r[0] else key
    used = {1, 2, 3, 5, 36000004, 36000014, 43010004, 43020004}
    def walk(value):
        if isinstance(value, dict):
            if 'item_id' in value:
                used.add(value['item_id'])
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
    walk(evidence)
    records = []
    item_rows = {}
    source_tables = []
    for table in ['iteminfo', 'previewitem', 'phantomitem', 'weaponconf']:
        path = tables / (table + '.json'); source_tables.append(path)
        for r in load(path):
            item_id = r.get('Id', r.get('ItemId'))
            if item_id in used and item_id not in item_rows:
                item_rows[item_id] = (r, table)
    for item_id in sorted(used):
        if item_id not in item_rows:
            records.append(dict(key=f'item:{item_id}', kind='item', id=item_id,
                                name=evidence['item_names'].get(str(item_id), f'미확인 품목 {item_id}'), status='missing_item_definition'))
            continue
        r, table = item_rows[item_id]
        name = text(r.get('Name', r.get('MonsterName', '')))
        if table == 'phantomitem':
            name += ' 에코'
        records.append(dict(key=f'item:{item_id}', kind='item', id=item_id, name=name,
                            quality=r.get('QualityId', 0), source_table=table, source_field='Icon',
                            object_path=r.get('Icon', ''), description=text(r.get('AttributesDescription', ''))))
    detection = {}
    for table in ['dungeondetection', 'silentareadetection']:
        path = tables / (table + '.json'); source_tables.append(path)
        for r in load(path):
            detection[r['Id']] = (r, table)
    secondary = {r['Id']: r for r in load(tables / 'secondaryguidedata.json')}
    source_tables.append(tables / 'secondaryguidedata.json')
    for e in evidence['catalog']:
        r, table = detection[e['id']]
        field = 'BigIcon' if r.get('BigIcon') else 'Icon'
        records.append(dict(key=f"dungeon:{e['id']}", kind='dungeon', id=e['id'], name=e['name'],
                            category=e['category'], region=e['region'], source_table=table, source_field=field,
                            object_path=r.get(field, ''), description=e['description']))
    activities = {r['Id']: r for r in load(more / 'activity.json')}
    source_tables.append(more / 'activity.json')
    for e in evidence['activities']:
        r = activities[e['id']]
        path = next((v for v in r['TabTexture'] if v), '') or r['TabResource']
        records.append(dict(key=f"activity:{e['id']}", kind='activity', id=e['id'], name=e['name'],
                            source_table='activity', source_field='TabTexture/TabResource', object_path=path))
    for p in definitions:
        cat = p['id']; entries = [e for e in evidence['catalog'] if e['category'] == cat]
        path = ''; source = ''; field = ''
        if entries:
            r, table = detection[entries[0]['id']]
            if cat in ['role_exp', 'weapon_exp', 'shell']:
                path, source, field = r['BigIcon'], table, 'BigIcon'
            else:
                path, source, field = secondary[r['Secondary']]['Icon'], 'secondaryguidedata', 'Icon'
        if cat == 'daily':
            r = next(r for r in load(tables / 'guidedata.json') if r['ChildViewName'] == 'DailyActivityTabView')
            path, source, field = r['BgTexture'], 'guidedata', 'BgTexture'
            source_tables.append(tables / 'guidedata.json')
        if cat in ['double_reward', 'rogue_archive', 'event_framework']:
            aid = 100700001 if cat in ['double_reward', 'event_framework'] else 100600005
            r = activities[aid]; field = 'TabResource' if cat == 'event_framework' else 'TabTexture[0]'
            path = r['TabResource'] if cat == 'event_framework' else r['TabTexture'][0]
            source = f'activity:{aid}'
        records.append(dict(key='category:' + cat, kind='category', id=cat, name=p['title'],
                            source_table=source, source_field=field, object_path=path))
    assets = {}
    wanted = set()
    for record in records:
        obj = record.get('object_path')
        if not obj:
            record.setdefault('status', 'no_configured_icon'); continue
        original = package_path(obj)
        stem = original
        if Path(stem).name.startswith('SP_'):
            stem = str(Path(stem).parent / '_SpriteTextures' / Path(stem).name)
        record['texture_stem'] = stem
        record['sprite_stem'] = original if original != stem else None
        for path in [stem, original]:
            for ext in ['.uasset', '.uexp', '.ubulk']:
                wanted.add(path + ext)
        assets.setdefault(stem, dict(key=hashlib.sha256(stem.encode()).hexdigest()[:16], stem=stem, originals=[]))['originals'].append(original)
    matches = defaultdict(list)
    index = base / '추출/20261118_확률추적/전체패키지_파일목록.tsv'
    with index.open() as f:
        for r in csv.DictReader(f, delimiter='\t'):
            if r['entry'] in wanted:
                matches[r['entry']].append(r)
    selected = {}
    for name, entries in matches.items():
        selected[name] = max(entries, key=lambda e: ('_P.' in e['package'], '/HD/' not in e['package'], e['package']))
    grouped = defaultdict(list)
    for name, r in selected.items():
        grouped[r['package']].append(name)
    key_map = load(base / '추출/20261118_클라이언트/로컬_키매핑.json')
    oodle = OodleDecoder(base / '추출/20261118_클라이언트/추출도구/liboo2corelinux64.so.9')
    game = Path('/mnt/c/Program Files/Wuthering Waves/Wuthering Waves Game')
    paths = {}; extraction = []
    for package, names in grouped.items():
        pak = WuwaPak(game / package, bytes.fromhex(key_map[package].removeprefix('0x')))
        for name in names:
            stem = name.rsplit('.', 1)[0]
            target_dir = raw_root / hashlib.sha256(stem.encode()).hexdigest()[:16]
            target_dir.mkdir(exist_ok=True)
            target = target_dir / Path(name).name
            target.write_bytes(pak.extract(name, oodle)); paths[name] = target
            extraction.append(dict(package=package, entry=name, file=str(target), sha256=sha(target), bytes=target.stat().st_size))
        print(f'Extracted {len(names)} entries: {Path(package).name}', flush=True)
        del pak
    save(out / '추출_명세.json', extraction)
    helper_input = []
    for stem, info in assets.items():
        asset, export = paths.get(stem + '.uasset'), paths.get(stem + '.uexp')
        if not asset or not export:
            info['status'] = 'missing_texture_file'; continue
        try:
            info['layout'] = layout = texture_layout(asset.read_bytes(), export.read_bytes())
            info['raw_asset'] = str(asset); info['raw_export'] = str(export)
            if layout['codec'] == 'BC7Prep':
                bc7 = export.with_suffix('.bc7'); info['bc7_file'] = str(bc7)
                helper_input.append(dict(Key=info['key'], InputPath=win(export), OutputPath=win(bc7),
                                         Offset=layout['offset'], Length=layout['length'], Modes=layout['modes'], Flags=layout['flags']))
            info['status'] = 'layout_verified'
        except Exception as exc:
            info['status'] = 'decode_unresolved'; info['error'] = str(exc)
    save(out / 'BC7Prep_입력.json', helper_input)
    subprocess.run(['/mnt/c/Program Files/dotnet/dotnet.exe', win(args.helper), win(out / 'BC7Prep_입력.json'), win(out / 'BC7Prep_결과.json')], check=True)
    helper_results = {r['Key']: r for r in load(out / 'BC7Prep_결과.json')}
    for stem, info in assets.items():
        if info['status'] != 'layout_verified':
            continue
        layout = info['layout']; width, height = layout['width'], layout['height']
        try:
            if layout['codec'] == 'BC7Prep':
                if not helper_results[info['key']]['Success']:
                    raise ValueError(helper_results[info['key']].get('Error'))
                data = Path(info['bc7_file']).read_bytes()
            else:
                data = Path(info['raw_export']).read_bytes()[layout['offset']:layout['offset'] + layout['length']]
            decoder = {'PF_BC7': texture2ddecoder.decode_bc7, 'PF_DXT1': texture2ddecoder.decode_bc1,
                       'PF_DXT5': texture2ddecoder.decode_bc3}.get(layout['format'])
            if decoder:
                image = Image.frombytes('RGBA', (width, height), decoder(data, width, height), 'raw', 'BGRA')
            elif layout['format'] == 'PF_B8G8R8A8':
                image = Image.frombytes('RGBA', (width, height), data, 'raw', 'BGRA')
            elif layout['format'] == 'PF_G8':
                image = Image.frombytes('L', (width, height), data).convert('RGBA')
            else:
                raise ValueError('Unsupported texture format')
            png = png_root / (info['key'] + '.png'); image.save(png)
            info.update(status='decoded', png_path=str(png), png_sha256=sha(png))
        except Exception as exc:
            info.update(status='decode_unresolved', error=str(exc))
    for r in records:
        if not r.get('texture_stem'):
            continue
        info = assets[r['texture_stem']]
        r['status'] = info['status']
        if r.get('sprite_stem'):
            original = paths.get(r['sprite_stem'] + '.uasset')
            expected = '/_SpriteTextures/' + Path(r['sprite_stem']).name
            r['sprite_reference_verified'] = bool(original and expected.encode() in original.read_bytes())
            if not r['sprite_reference_verified']:
                r['status'] = 'sprite_reference_unverified'
        if r['status'] == 'decoded':
            r.update(file=info['png_path'], sha256=info['png_sha256'], width=info['layout']['width'], height=info['layout']['height'])
    manifest = dict(source='installed_client_3.8.0', records=records, assets=list(assets.values()),
                    sources={str(p): sha(p) for p in set(source_tables + [lang_path, index, Path(__file__).resolve(), args.helper.resolve()])},
                    extraction_manifest=str(out / '추출_명세.json'), helper_reference='https://github.com/FabianFG/CUE4Parse/blob/master/CUE4Parse/UE4/Assets/Exports/Texture/BC7PrepDecoder.cs')
    save(out / '아이콘_매핑.json', manifest)
    counts = defaultdict(int)
    for r in records:
        counts[r['kind'] + ':' + r['status']] += 1
    print(json.dumps(dict(counts), ensure_ascii=False))


if __name__ == '__main__':
    main()
