#!/usr/bin/env python3
"""Reproduce the exact glyph fragments and independently audit the corrected atlas.

Run with a Python environment containing Pillow. All binary inputs are small local
snapshots; no old build directories, production decoder modules, or emulator used.
The glyph samples are tightly assembled (13 px) for screenshot fragment matching;
this is not a simulation of the game's animation positions/timing.
"""
from pathlib import Path
import struct
import json
import hashlib
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
PITCH = 14
SPAN = 13
COLUMNS = 18
PER_PAGE = COLUMNS * COLUMNS
POINTERS = [('opening', 9840), ('ordinary', 9904)]


def decode_t4(data):
    assert len(data) == 32768
    result = bytearray(65536)
    for by in range(32):
        for bx in range(8):
            for row in range(8):
                base = by * 1024 + bx * 128 + row * 16
                for b in range(16):
                    v = data[base+b]
                    x, y = bx*32+b*2, by*8+row
                    result[y*256+x] = (v & 15)*17
                    result[y*256+x+1] = (v >> 4)*17
    return Image.frombytes('L', (256, 256), bytes(result))


def load_assets(folder):
    raw = (folder/'poem.bin').read_bytes()
    count = struct.unpack_from('<I', raw)[0]
    rows = [raw[4+6*i:10+6*i] for i in range(count)]
    keys = {r[:2][::-1]: i for i, r in enumerate(rows)}
    assert len(keys) == count
    assert [r[:2][::-1] for r in rows] == sorted(keys)
    txb = (folder/'poem_font.txb').read_bytes()
    n, flags = struct.unpack_from('<HH', txb)
    assert flags == 0
    sizes = struct.unpack_from('<'+'I'*n, txb, 4)
    pos = (4+4*n+15) & ~15
    atlas = []
    for size in sizes:
        entry = txb[pos:pos+size]
        assert struct.unpack_from('<HHHH', entry, 0x10) == (4, 1, 256, 256)
        assert struct.unpack_from('<I', entry, 0x1c)[0] == 32768
        atlas.append(decode_t4(entry[48:48+32768]))
        pos += size
    dat = (folder/'0000.dat').read_bytes()
    return rows, keys, atlas, dat


def sample(atlas, index):
    page, cell = divmod(index, PER_PAGE)
    x, y = (cell % COLUMNS)*PITCH, (cell//COLUMNS)*PITCH
    return atlas[page].crop((x, y, x+SPAN, y+SPAN)), (page, x, y)


def render(folder, tag):
    rows, keys, atlas, dat = load_assets(folder)
    records = []
    for name, pointer in POINTERS:
        offset = struct.unpack_from('<I', dat, pointer)[0]
        raw = dat[offset:dat.index(0, offset)]
        aliases = raw.decode('cp932')
        image = Image.new('L', (len(aliases)*SPAN+1, 14))
        actual = ''
        coords = []
        for j, ch in enumerate(aliases):
            key = ch.encode('cp932')
            idx = keys[key]
            glyph, (page, x, y) = sample(atlas, idx)
            resolved = rows[idx][2:5].split(b'\0')[0].decode('utf8')
            actual += resolved
            coords.append(dict(alias=ch, translated=resolved, key=key.hex(), index=idx, page=page, x=x, y=y))
            image.paste(glyph, (j*SPAN, 0))
        image.resize((image.width*5, image.height*5), Image.Resampling.NEAREST).save(HERE/f'{name}-{tag}.png')
        records.append(dict(name=name, pointer_offset=pointer, target_offset=offset, raw=raw.hex(), alias_text=aliases, translated_text=actual, coordinates=coords))
    return records


before = render(HERE/'before-assets', 'runtime')
after = render(HERE/'after-assets', 'after')
assert [r['raw'] for r in before] == [r['raw'] for r in after]
(HERE/'coordinates.json').write_text(json.dumps(before, ensure_ascii=False, indent=2)+'\n')
(HERE/'after-coordinates.json').write_text(json.dumps(after, ensure_ascii=False, indent=2)+'\n')

rows, keys, atlas, dat = load_assets(HERE/'after-assets')
aliases = json.loads((HERE/'after-assets/poem-glyph-map.json').read_text())
empty = []
nonzero_padding = []
lookup_mismatches = []
for char, alias in aliases.items():
    idx = keys[alias.encode('cp932')]
    resolved = rows[idx][2:5].split(b'\0')[0].decode('utf8')
    if resolved != char:
        lookup_mismatches.append([char, resolved])
    page, cell = divmod(idx, PER_PAGE)
    x, y = (cell % COLUMNS)*PITCH, (cell//COLUMNS)*PITCH
    tile = atlas[page].crop((x, y, x+PITCH, y+PITCH))
    if tile.getbbox() is None:
        empty.append(char)
    if tile.crop((0, 13, 14, 14)).getbbox() or tile.crop((13, 0, 14, 14)).getbbox():
        nonzero_padding.append(char)
assert not empty, empty
assert not nonzero_padding, nonzero_padding
assert not lookup_mismatches, lookup_mismatches
report = dict(translated_glyphs=len(aliases), empty_glyphs=empty, nonzero_protection_row_or_column=nonzero_padding,
              lookup_mismatches=lookup_mismatches, cell_pitch=PITCH, sampled_span=SPAN,
              comparison_assembly_advance=SPAN, layout_note='Tight samples for fragment comparison; does not simulate animation layout.',
              snapshots={str(p.relative_to(HERE)): hashlib.sha256(p.read_bytes()).hexdigest()
                         for d in ['before-assets','after-assets'] for p in sorted((HERE/d).iterdir())})
(HERE/'final-atlas-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')

canvas = Image.new('RGB', (1120, 440), (24, 24, 24))
draw = ImageDraw.Draw(canvas)
for y, title, tag in [(12, 'BEFORE: v13 atlas sampled at actual 14 px cells', 'runtime'),
                       (220, 'AFTER: corrected atlas sampled at the same 14 px cells', 'after')]:
    draw.text((20, y), title, fill='white', font=ImageFont.load_default(size=18))
    for yy, name in [(y+34, 'opening'), (y+112, 'ordinary')]:
        im = Image.open(HERE/f'{name}-{tag}.png').convert('RGB')
        canvas.paste(im, (20, yy))
draw.text((20, 422), 'STATIC GLYPH SAMPLES ASSEMBLED TIGHTLY - NOT AN EMULATOR SCREENSHOT', fill=(160,160,160), font=ImageFont.load_default(size=12))
canvas.save(HERE/'before-after-static.png')
print(json.dumps(dict(translated_glyphs=len(aliases), empty_glyphs=len(empty), padding_failures=len(nonzero_padding), lookup_mismatches=len(lookup_mismatches), rendered_text=[r['translated_text'] for r in after]), ensure_ascii=False, indent=2))
