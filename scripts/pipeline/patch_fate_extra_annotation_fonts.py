#!/usr/bin/env python3
"""Add Chinese ruby glyphs without reallocating working dialogue/poem aliases.

Input font resources come from the last working CPK. Original ruby cells and
all used dialogue cells retain their indices. The ruby atlas has 9px cells,
14 columns, and 196 cells per page; it is not the 16px dialogue font.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import subprocess
import tempfile

from patch_fate_extra_ui import pack_bundle, unpack_bundle


RUBY = re.compile(r"#RUBS(.*?)#RUBE(.*?)#REND", re.S)
COLOR = re.compile(r"#(?:C\d{9}|CDEF)")


def table_rows(data: bytes) -> list[bytes]:
    count = struct.unpack_from('<I', data)[0]
    end = 4 + 6 * count
    if end > len(data) or any(data[end:]):
        raise ValueError('invalid glyph table size/trailer')
    rows = [data[4 + 6 * i:10 + 6 * i] for i in range(count)]
    if len({r[:2] for r in rows}) != count:
        raise ValueError('duplicate glyph table keys')
    return rows


def encode_key(char: str, mapping: dict[str, str]) -> bytes:
    raw = mapping.get(char, char).encode('cp932')
    if len(raw) not in (1, 2):
        raise ValueError(f'unsupported font key: {char!r}')
    return raw.ljust(2, b'\0')[::-1]


def make_row(char: str, mapping: dict[str, str]) -> bytes:
    label = char.encode('utf-8')
    if len(label) > 3:
        raise ValueError(f'font table requires BMP scalar: {char!r}')
    return encode_key(char, mapping) + label.ljust(3, b'\0') + b'\0'


def build_table(rows: list[bytes]) -> bytes:
    out = struct.pack('<I', len(rows)) + b''.join(rows)
    return out + b'\0' * (-len(out) % 16)


def unswizzle(data: bytes, width: int) -> bytearray:
    row_bytes = width // 2
    if row_bytes % 16 or len(data) % (row_bytes * 8):
        raise ValueError('invalid swizzled T4 extent')
    linear = bytearray(len(data))
    pos = 0
    for by in range(len(data) // row_bytes // 8):
        for bx in range(row_bytes // 16):
            for y in range(8):
                dst = (by * 8 + y) * row_bytes + bx * 16
                linear[dst:dst + 16] = data[pos:pos + 16]
                pos += 16
    pixels = bytearray(len(linear) * 2)
    for i, v in enumerate(linear):
        pixels[2 * i] = v & 15
        pixels[2 * i + 1] = v >> 4
    return pixels


def swizzle(pixels: bytes, width: int) -> bytes:
    row_bytes = width // 2
    if len(pixels) % (width * 8):
        raise ValueError('invalid linear T4 extent')
    linear = bytes(pixels[i] | pixels[i + 1] << 4 for i in range(0, len(pixels), 2))
    out = bytearray()
    for by in range(len(linear) // row_bytes // 8):
        for bx in range(row_bytes // 16):
            for y in range(8):
                src = (by * 8 + y) * row_bytes + bx * 16
                out.extend(linear[src:src + 16])
    return bytes(out)


def split_tex(data: bytes) -> tuple[bytes, bytearray, bytes, int]:
    fmt, swz, width, height, stride = struct.unpack_from('<5H', data, 0x10)
    size = struct.unpack_from('<I', data, 0x1c)[0]
    if fmt != 4 or swz != 1 or width != stride or 48 + size + 80 != len(data):
        raise ValueError('unexpected font TEX')
    pixels = unswizzle(data[48:48 + size], width)
    if len(pixels) < width * height or swizzle(pixels, width) != data[48:48 + size]:
        raise ValueError('font TEX roundtrip failed')
    return data[:48], pixels, data[48 + size:], width


def cell(pixels: bytes, index: int, pitch: int, width: int) -> bytes:
    columns = width // pitch
    x, y = index % columns * pitch, index // columns * pitch
    return b''.join(pixels[(y + r) * width + x:(y + r) * width + x + pitch] for r in range(pitch))


def put_cell(pixels: bytearray, bitmap: bytes, index: int, pitch: int, width: int) -> None:
    columns = width // pitch
    x, y = index % columns * pitch, index // columns * pitch
    for r in range(pitch):
        pixels[(y + r) * width + x:(y + r) * width + x + pitch] = bitmap[r * pitch:(r + 1) * pitch]


def render(chars: list[str], pitch: int, size: float, renderer: Path) -> dict[str, bytes]:
    if not chars:
        return {}
    with tempfile.TemporaryDirectory(prefix='fate-ruby-') as directory:
        src, dst = Path(directory) / 'chars.txt', Path(directory) / 'glyphs.raw'
        src.write_text('\n'.join(chars) + '\n', encoding='utf-8')
        subprocess.run(['swift', str(renderer), str(src), str(dst), str(pitch), str(size)], check=True)
        raw = dst.read_bytes()
    if struct.unpack_from('<I', raw)[0] != len(chars) or len(raw) != 4 + len(chars) * pitch ** 2:
        raise ValueError('renderer returned unexpected glyph count/size')
    bitmaps = {c: bytes((v + 8) // 17 for v in raw[4 + i * pitch ** 2:4 + (i + 1) * pitch ** 2])
               for i, c in enumerate(chars)}
    if any(not any(p) for c, p in bitmaps.items() if not c.isspace()):
        raise ValueError('renderer produced an empty glyph')
    return bitmaps


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, required=True, help='working PRELOAD resources')
    ap.add_argument('--translations', type=Path, required=True)
    ap.add_argument('--glyph-map', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--out-glyph-map', type=Path, required=True)
    ap.add_argument('--report', type=Path, required=True)
    ap.add_argument('--renderer', type=Path, default=Path('tools/render_font_glyphs.swift'))
    args = ap.parse_args()
    texts = [json.loads(l)['zh_cn'] for l in args.translations.read_text(encoding='utf-8').splitlines() if l.strip()]
    mapping = json.loads(args.glyph_map.read_text(encoding='utf-8'))
    old_mapping = dict(mapping)
    all_chars = {c for t in texts for c in t if ord(c) >= 128 and not c.isspace()}
    main_rows = table_rows((args.source / 'kanzi.bin').read_bytes())
    main_keys = {r[:2] for r in main_rows}
    missing = []
    for c in sorted(all_chars):
        try:
            exists = encode_key(c, mapping) in main_keys
        except UnicodeEncodeError:
            exists = False
        if not exists:
            missing.append(c)
    required_keys = set()
    for c in all_chars - set(missing):
        required_keys.add(encode_key(c, mapping))
    # Existing aliases never move. Only unreferenced CJK entries can host a new
    # glyph, maintaining the known 4096-entry dialogue-font runtime range.
    spare = []
    for i, r in enumerate(main_rows):
        try:
            label = r[2:5].rstrip(b'\0').decode('utf-8')
        except UnicodeDecodeError:
            continue
        if len(label) == 1 and '\u3400' <= label <= '\u9fff' and r[:2] not in required_keys:
            spare.append(i)
    if len(spare) < len(missing):
        raise ValueError('insufficient unreferenced dialogue glyph slots')
    main_changes = []
    has_paths, main_entries = unpack_bundle((args.source / 'font.txb').read_bytes())
    main_parts = [split_tex(b) for _, b in main_entries]
    new_main_glyphs = render(missing, 16, 13, args.renderer)
    for c, index in zip(missing, reversed(spare)):
        for codepoint in range(0xe000, 0xe758):
            alias = chr(codepoint)
            k = encode_key(alias, {})
            if k not in main_keys and alias not in mapping.values():
                mapping[c] = alias
                main_keys.add(k)
                break
        else:
            raise ValueError('no unused CP932 private key')
        old_row = main_rows[index]
        main_rows[index] = make_row(c, mapping)
        put_cell(main_parts[index // 256][1], new_main_glyphs[c], index % 256, 16, 256)
        main_changes.append({'char': c, 'index': index, 'old_row_hex': old_row.hex(), 'new_key': mapping[c]})
    args.out.mkdir(parents=True, exist_ok=True)
    if missing:
        rebuilt = [(n, h + swizzle(p, w) + tail) for (n, _), (h, p, tail, w) in zip(main_entries, main_parts)]
        (args.out / 'font.txb').write_bytes(pack_bundle(rebuilt, has_paths))
        (args.out / 'kanzi.bin').write_bytes(build_table(main_rows))

    old_ruby = table_rows((args.source / 'ruby.bin').read_bytes())
    ruby_rows = list(old_ruby)
    ruby_keys = {r[:2] for r in ruby_rows}
    upper_chars = {c for t in texts for u, _ in RUBY.findall(t) for c in COLOR.sub('', u) if not c.isspace()}
    new_chars = [c for c in sorted(upper_chars) if encode_key(c, mapping) not in ruby_keys]
    has_paths, entries = unpack_bundle((args.source / 'ruby.txb').read_bytes())
    original_parts = [split_tex(b) for _, b in entries]
    parts = [(h, bytearray(p), tail, w) for h, p, tail, w in original_parts]
    count = len(ruby_rows) + len(new_chars)
    needed_pages = math.ceil(count / 196)
    while len(parts) < needed_pages:
        h, p, tail, w = original_parts[0]
        parts.append((h, bytearray(len(p)), tail, w))
        entries.append((f'font08_{len(entries):02d}.tex', b''))
    glyphs = render(new_chars, 9, 8, args.renderer)
    for c in new_chars:
        index = len(ruby_rows)
        ruby_rows.append(make_row(c, mapping))
        put_cell(parts[index // 196][1], glyphs[c], index % 196, 9, 128)
    for i in range(len(old_ruby)):
        page, pos = divmod(i, 196)
        if cell(parts[page][1], pos, 9, 128) != cell(original_parts[page][1], pos, 9, 128):
            raise ValueError(f'original ruby glyph {i} was modified')
    ruby_txb = pack_bundle([(n, h + swizzle(p, w) + tail) for (n, _), (h, p, tail, w) in zip(entries, parts)], has_paths)
    ruby_bin = build_table(ruby_rows)
    (args.out / 'ruby.txb').write_bytes(ruby_txb)
    (args.out / 'ruby.bin').write_bytes(ruby_bin)
    args.out_glyph_map.parent.mkdir(parents=True, exist_ok=True)
    args.out_glyph_map.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    final_keys = {r[:2] for r in ruby_rows}
    if any(encode_key(c, mapping) not in final_keys for c in upper_chars):
        raise ValueError('missing ruby key after rebuild')
    report = {'ruby_original_rows': len(old_ruby), 'ruby_rows': len(ruby_rows), 'ruby_pages': needed_pages,
              'ruby_new_characters': ''.join(new_chars), 'ruby_new_count': len(new_chars),
              'ruby_bin_sha256': hashlib.sha256(ruby_bin).hexdigest(),
              'ruby_txb_sha256': hashlib.sha256(ruby_txb).hexdigest(),
              'main_changes': main_changes, 'existing_aliases_changed': any(mapping[k] != v for k, v in old_mapping.items()),
              'runtime_page_boundary_indices': [195, 196, 391, 392],
              'original_ruby_cells_preserved': len(old_ruby)}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k != 'ruby_new_characters'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
