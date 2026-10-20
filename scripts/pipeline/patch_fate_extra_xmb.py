#!/usr/bin/env python3
"""Localize XMB previews in their existing ISO sectors, without rebuilding boot data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib

from embed_fate_extra_cpk import SECTOR, PVD_SECTOR, walk


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def png_info(data: bytes) -> tuple[int, int, int, int]:
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('not a PNG')
    pos = 8
    info = None
    ended = False
    while pos < len(data):
        length = struct.unpack_from('>I', data, pos)[0]
        kind = data[pos+4:pos+8]
        payload = data[pos+8:pos+8+length]
        crc = struct.unpack_from('>I', data, pos+8+length)[0]
        if zlib.crc32(kind + payload) != crc:
            raise ValueError(f'PNG CRC mismatch in {kind!r}')
        if kind == b'IHDR':
            width, height, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', payload)
            if compression or filtering or interlace:
                raise ValueError('expected a non-interlaced standard PNG')
            info = width, height, depth, color
        pos += length + 12
        if kind == b'IEND':
            ended = True
            break
    if info is None or not ended or pos != len(data):
        raise ValueError('invalid PNG chunk structure')
    return info


def sfo_fields(data: bytes) -> dict:
    if data[:4] != b'\0PSF':
        raise ValueError('not a PSP SFO')
    version, key_start, data_start, count = struct.unpack_from('<4I', data, 4)
    result = {}
    for i in range(count):
        index = 20 + i * 16
        key_offset, fmt, length, capacity, value_offset = struct.unpack_from('<HHIII', data, index)
        start = key_start + key_offset
        end = data.index(b'\0', start)
        key = data[start:end].decode('ascii')
        value_start = data_start + value_offset
        value = data[value_start:value_start+length]
        if value_start + capacity > len(data) or length > capacity:
            raise ValueError(f'invalid SFO field {key}')
        result[key] = dict(index=index, format=fmt, length=length, capacity=capacity,
                           offset=value_start, bytes=value.hex())
    return result


def title_sfo(source: bytes, title: str) -> bytes:
    before = sfo_fields(source)
    field = before['TITLE']
    value = title.encode('utf-8') + b'\0'
    if field['format'] != 0x204 or len(value) > field['capacity']:
        raise ValueError('TITLE cannot fit its existing UTF-8 SFO field')
    out = bytearray(source)
    start, cap = field['offset'], field['capacity']
    out[start:start+cap] = value.ljust(cap, b'\0')
    struct.pack_into('<I', out, field['index'] + 4, len(value))
    after = sfo_fields(out)
    if any(after[k] != v for k, v in before.items() if k != 'TITLE'):
        raise ValueError('another SFO field changed')
    if bytes.fromhex(after['TITLE']['bytes']) != value:
        raise ValueError('TITLE writeback failed')
    return bytes(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--iso', type=Path, required=True)
    ap.add_argument('--assets', type=Path, required=True)
    ap.add_argument('--title', default='Fate/EXTRA 中文汉化版')
    ap.add_argument('--report', type=Path, required=True)
    args = ap.parse_args()
    names = ['ICON0.PNG', 'PIC0.PNG', 'PIC1.PNG', 'PARAM.SFO']
    report = dict(iso=str(args.iso), title=args.title, files=[])
    with args.iso.open('r+b') as stream:
        stream.seek(PVD_SECTOR*SECTOR)
        pvd = stream.read(SECTOR)
        if pvd[:7] != b'\x01CD001\x01':
            raise ValueError('invalid ISO primary volume descriptor')
        root_extent = struct.unpack_from('<I', pvd, 158)[0]
        root_size = struct.unpack_from('<I', pvd, 166)[0]
        entries = list(walk(stream, root_extent, root_size))
        by_path = {'/'.join(e[4]): e for e in entries}
        patches = []
        # Validate every mutation before touching the image.
        for name in names:
            path = 'PSP_GAME/' + name
            record_offset, record, extent, old_size, _, is_dir = by_path[path]
            if is_dir or struct.unpack_from('>I', record, 6)[0] != extent or struct.unpack_from('>I', record, 14)[0] != old_size:
                raise ValueError(f'invalid ISO directory record: {path}')
            stream.seek(extent*SECTOR)
            old = stream.read(old_size)
            new = title_sfo(old, args.title) if name.endswith('.SFO') else (args.assets/name).read_bytes()
            capacity = ((old_size + SECTOR - 1)//SECTOR)*SECTOR
            if len(new) > capacity:
                raise ValueError(f'{path} exceeds its existing sector allocation')
            if name.endswith('.PNG') and png_info(old) != png_info(new):
                raise ValueError(f'{path} changes native PNG dimensions/format')
            end = extent*SECTOR + capacity
            for other in entries:
                if other[4] == by_path[path][4] or not other[3]:
                    continue
                other_start = other[2]*SECTOR
                other_end = other_start + other[3]
                if extent*SECTOR < other_end and other_start < end:
                    raise ValueError(f'{path} overlaps another file/directory')
            patches.append((path, record_offset, extent, old, new))
        for path, record_offset, extent, old, new in patches:
            stream.seek(extent*SECTOR)
            stream.write(new)
            if len(new) < len(old):
                stream.write(b'\0'*(len(old)-len(new)))
            stream.seek(record_offset+10)
            stream.write(struct.pack('<I', len(new)) + struct.pack('>I', len(new)))
            report['files'].append(dict(path=path, extent=extent, old_bytes=len(old),
                                       bytes=len(new), old_sha256=sha(old), sha256=sha(new)))
        stream.flush()
        for patch, item in zip(patches, report['files']):
            path, record_offset, extent, old, new = patch
            stream.seek(extent*SECTOR)
            actual = stream.read(len(new))
            if actual != new:
                raise ValueError(f'{path} ISO payload readback differs')
            stream.seek(record_offset+10)
            if stream.read(8) != struct.pack('<I', len(new)) + struct.pack('>I', len(new)):
                raise ValueError(f'{path} ISO directory readback differs')
            item['readback_ok'] = True
        stream.seek(PVD_SECTOR*SECTOR)
        if stream.read(SECTOR) != pvd:
            raise ValueError('XMB patch unexpectedly changed primary volume descriptor')
    report['existing_sector_allocation_only'] = True
    report['sfo_other_fields_unchanged'] = True
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
