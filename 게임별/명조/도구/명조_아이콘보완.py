#!/usr/bin/env python3
"""Resolve configured LGUI atlas sprites and supplementary cosmetic icons.

The atlas reader validates tagged property boundaries, sprite keys, texture
indices, frame coordinates and UV-derived dimensions before extracting pixels.
It is intentionally restricted to the installed client's observed layout.
"""
from __future__ import annotations
import argparse
from collections import Counter
from pathlib import Path
import re
import struct
import subprocess
import sys
from 명조_아이콘추출 import load, save, sha, win, texture_layout


class Atlas:
    def __init__(self, stem):
        a = stem.with_suffix('.uasset').read_bytes()
        self.data = stem.with_suffix('.uexp').read_bytes()
        count, pos = struct.unpack_from('<II', a, 41)
        self.names = []
        for _ in range(count):
            length = struct.unpack_from('<i', a, pos)[0]
            if not 0 < length < 1000:
                raise ValueError('Unsupported name table')
            pos += 4
            self.names.append(a[pos:pos + length - 1].decode('utf-8'))
            pos += length + 4
        root, _ = self.props(0)
        textures = root['SoftAtlasTextures']
        count, = self.read('<I', textures['pos'])
        pos = textures['pos'] + 4
        ni, nn, ti, tn, size, index, si, sn = self.read('<8I', pos)
        assert self.names[ti] == 'StructProperty' and self.names[si] == 'SoftObjectPath'
        assert nn == tn == sn == index == 0 and self.data[pos + 48] == 0
        pos += 49
        self.textures = []
        for _ in range(count):
            ni, number, subpath_length = self.read('<III', pos)
            assert number == subpath_length == 0
            self.textures.append(self.names[ni]); pos += 12
        assert pos == textures['pos'] + textures['size']
        info = root['SpriteInfoMap']
        removed, count = self.read('<II', info['pos'])
        assert removed == 0
        pos = info['pos'] + 8
        self.info = {}
        for _ in range(count):
            key, = self.read('<H', pos)
            values, pos = self.props(pos + 2)
            fields = {}
            for name, p in values.items():
                fmt = {'FloatProperty': '<f', 'UInt16Property': '<H', 'Int16Property': '<h'}.get(p['type'])
                if fmt:
                    fields[name], = self.read(fmt, p['pos'])
            self.info[key] = fields
        assert pos == info['pos'] + info['size']
        sprites = root['Sprites']
        count, = self.read('<I', sprites['pos'])
        self.sprites = {}
        for i in range(count):
            name, number = self.read('<II', sprites['pos'] + 4 + 8 * i)
            assert number == 0
            self.sprites[self.names[name]] = i
        atlas = root['SpriteAtlasTextureMap']
        removed, count = self.read('<II', atlas['pos'])
        assert removed == 0 and atlas['size'] == 8 + count * 3
        self.indices = dict(self.read('<HB', atlas['pos'] + 8 + i * 3) for i in range(count))
        frames = root['SpriteFrameInfoMapNew']
        removed, count = self.read('<II', frames['pos'])
        assert removed == 0
        pos = frames['pos'] + 8
        self.frames = {}
        for _ in range(count):
            length, = self.read('<I', pos); pos += 4
            path = self.data[pos:pos + length - 1].decode('utf-8'); pos += length
            self.frames[path] = self.read('<II', pos); pos += 8
        assert pos == frames['pos'] + frames['size']

    def read(self, fmt, pos):
        return struct.unpack_from(fmt, self.data, pos)

    def props(self, pos):
        result = {}
        while True:
            ni, number = self.read('<II', pos); pos += 8
            assert number == 0
            name = self.names[ni]
            if name == 'None':
                return result, pos
            ti, number, size, index = self.read('<IIii', pos); pos += 16
            assert number == index == 0 and size >= 0
            kind = self.names[ti]
            if kind in ['ArrayProperty', 'SetProperty', 'ByteProperty', 'EnumProperty']: pos += 8
            if kind == 'MapProperty': pos += 16
            if kind == 'StructProperty': pos += 24
            guid = self.data[pos]; pos += 1
            assert guid in [0, 1]
            if guid: pos += 16
            result[name] = dict(type=kind, pos=pos, size=size)
            pos += size
            assert pos <= len(self.data)

    def extract(self, object_path, image):
        key = self.sprites[object_path]
        info = self.info[key]
        width, height = info['width'], info['height']
        left, top = self.frames[object_path]
        uv = [info['uv0X'] * image.width, info['uv3Y'] * image.height,
              info['uv3X'] * image.width, info['uv0Y'] * image.height]
        rect = [left, top, left + width, top + height]
        assert all(abs(a - b) < .01 for a, b in zip(uv, rect)), (uv, rect)
        assert 0 <= left < left + width <= image.width and 0 <= top < top + height <= image.height
        assert all(info.get(k, 0) == 0 for k in ['paddingLeft', 'paddingRight', 'paddingTop', 'paddingBottom'])
        return image.crop(rect), dict(sprite_index=key, atlas_index=self.indices[key], frame=rect, uv=uv)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mapping', type=Path, required=True)
    ap.add_argument('--supplement', type=Path, required=True)
    ap.add_argument('--libs', type=Path, required=True)
    ap.add_argument('--helper', type=Path, required=True)
    ap.add_argument('--extra-records', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists(): ap.error('Output must be new')
    args.out.mkdir(parents=True)
    sys.path.insert(0, str(args.libs.resolve()))
    import texture2ddecoder
    from PIL import Image
    mapping = load(args.mapping)
    if args.extra_records:
        replacements = {r['key']: r for r in load(args.extra_records)}
        mapping['records'] = [replacements.get(r['key'], r) for r in mapping['records']]
    layouts, batch = {}, []
    for asset in sorted(args.supplement.rglob('*.uasset')):
        if not asset.name.startswith('T_'):
            continue
        export = asset.with_suffix('.uexp')
        if not export.exists(): continue
        layout = texture_layout(asset.read_bytes(), export.read_bytes())
        assert layout['codec'] == 'BC7Prep'
        layouts[asset.stem] = (asset, layout)
        batch.append(dict(Key=asset.stem, InputPath=win(export), OutputPath=win(args.out / (asset.stem + '.bc7')),
                          Offset=layout['offset'], Length=layout['length'], Modes=layout['modes'], Flags=layout['flags']))
    save(args.out / 'BC7Prep_입력.json', batch)
    subprocess.run(['/mnt/c/Program Files/dotnet/dotnet.exe', win(args.helper), win(args.out / 'BC7Prep_입력.json'), win(args.out / 'BC7Prep_결과.json')], check=True)
    result = load(args.out / 'BC7Prep_결과.json')
    assert all(r['Success'] for r in result)
    images, files = {}, {}
    for key, (asset, layout) in layouts.items():
        width, height = layout['width'], layout['height']
        bc7 = (args.out / (key + '.bc7')).read_bytes()
        img = Image.frombytes('RGBA', (width, height), texture2ddecoder.decode_bc7(bc7, width, height), 'raw', 'BGRA')
        path = args.out / (key + '.png'); img.save(path)
        images[key], files[key] = img, path
    atlases = [Atlas(p.with_suffix('')) for p in args.supplement.rglob('TPI_*.uasset')]
    for r in mapping['records']:
        if r['status'] == 'decoded': continue
        obj = r.get('object_path', '')
        key = obj.rsplit('.', 1)[-1]
        path = None
        if key in images:
            path = files[key]
        for atlas in atlases:
            if obj not in atlas.sprites: continue
            atlas_key = atlas.textures[atlas.indices[atlas.sprites[obj]]].rsplit('.', 1)[-1]
            img, coords = atlas.extract(obj, images[atlas_key])
            path = args.out / (key + '.png'); img.save(path)
            r.update(sprite_reference_verified=True, atlas_coordinates=coords, atlas_texture=atlas_key)
        if path:
            img = Image.open(path)
            r.update(status='decoded', file=str(path.resolve()), sha256=sha(path), width=img.width, height=img.height)
    mapping['parent_mapping'] = {'file': str(args.mapping.resolve()), 'sha256': sha(args.mapping)}
    mapping['supplement'] = {str(p.resolve()): sha(p) for p in args.supplement.rglob('*') if p.is_file()}
    mapping['sources'][str(Path(__file__).resolve())] = sha(__file__)
    if args.extra_records: mapping['sources'][str(args.extra_records.resolve())] = sha(args.extra_records)
    for r in mapping['records']:
        if r.get('source_file'):
            mapping['sources'][r['source_file']] = sha(r['source_file'])
    save(args.out / '아이콘_매핑.json', mapping)
    print(dict(Counter(r['kind'] + ':' + r['status'] for r in mapping['records'])))


if __name__ == '__main__':
    main()
