#!/usr/bin/env python3
"""Build vector-rendered PPSSPP fonts and CCT UI tiles for a Chinese build.

Requires Pillow, numpy and xxhash. Hash algorithms/CLUT cache keys follow
PPSSPP's TextureReplacer / TexCacheEntry (ppsspp.org/docs/reference/texture-replacement).
No emulator is launched. Configured images are rendered from vectors at output
resolution, not enlarged from the PSP Chinese rasters.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
import numpy as np
import xxhash
from PIL import Image
from fate_extra_texture import Bundle, Texture
from patch_fate_extra_image_text import render_blocks
from ui_glyph_styles import load_atlas


def data_hash(raw: bytes, algorithm: str) -> int:
    if algorithm == 'xxh64':
        return xxhash.xxh64(raw, seed=0xBACD7814).intdigest() & 0xffffffff
    # StableQuickTexHash's SSE/NEON 64-byte recurrence, represented as eight
    # little-endian 16-bit lanes. Each operation wraps at its native lane size.
    if len(raw) % 64:
        raise ValueError('quick hash input must be a multiple of 64 bytes')
    cursor = np.zeros(8, dtype='<u2')
    multiplier = np.array([0xc00b, 0x9bd9, 0x4b73, 0xb651, 0x4d9b, 0x4309, 0x0083, 1], dtype='<u2')
    for row in np.frombuffer(raw, dtype='<u2').reshape(-1, 32):
        cursor = (cursor.astype(np.uint32) + row[:8].astype(np.uint32) * multiplier).astype('<u2')
        cursor = (cursor.view('<u4') ^ row[8:16].view('<u4')).view('<u2')
        cursor = (cursor.view('<u4').astype(np.uint64) + row[16:24].view('<u4')).astype('<u4').view('<u2')
        cursor ^= (row[24:32].astype(np.uint32) * multiplier).astype('<u2')
        multiplier = (multiplier.astype(np.uint32) + 0x2455).astype('<u2')
    return int((cursor.view('<u4').astype(np.uint64) + multiplier.view('<u4')).sum()) & 0xffffffff


def palette_key(tex: Texture, width: int, height: int) -> int:
    dim = int(math.log2(width)) | (int(math.log2(height)) << 8)
    if width != 1 << (dim & 255) or height != 1 << (dim >> 8):
        raise ValueError('GPU texture dimensions must be powers of two')
    if tex.palette is None:
        return dim
    palette = tex.palette.copy()
    # Fate zeroes RGB on transparent entries before guClutLoad. GE's raw
    # CLUTFORMAT command includes command id C5 and a FF index mask, even T4.
    palette[palette[:, 3] == 0] = 0
    return xxhash.xxh32(palette.tobytes(), seed=0xC0108888).intdigest() ^ 0xc500ff03 ^ dim


def tile_records(tex: Texture, image: Image.Image, scale: int, text_boxes):
    if tex.cct is not None and tex.swizzled and tex.width > 16:
        ch = tex.chunk_size
        cols = tex.canvas.shape[1] // ch
        for logical, unique in enumerate(tex.cct):
            if unique < 0:
                continue
            y, x = divmod(logical, cols)
            if not any(x*ch < bx+bw and (x+1)*ch > bx and
                       y*ch < by+bh and (y+1)*ch > by
                       for bx,by,bw,bh in text_boxes):
                continue
            indices = tex.canvas[y*ch:(y+1)*ch, x*ch:(x+1)*ch]
            if tex.palette[indices][:, :, 3].max() == 0:
                continue
            tile = Image.new('RGBA', (ch * scale, ch * scale))
            tile.paste(image.crop((x*ch*scale,y*ch*scale,(x+1)*ch*scale,(y+1)*ch*scale)), (0,0))
            if tile.getchannel('A').getextrema()[1] == 0:
                continue
            yield logical, tex.original_tiles[unique], ch, ch, tile
    else:
        yield 0, tex.pixel_data, tex.width, tex.height, image


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',type=Path,required=True,help='Original extracted pack directory')
    ap.add_argument('--overlay',type=Path,required=True,help='Current Chinese pack overlay (old hashes also supported)')
    ap.add_argument('--new-ui',type=Path,required=True,help='Newly generated Chinese UI bundles')
    ap.add_argument('--out',type=Path,required=True,help='New output directory')
    ap.add_argument('--scale',type=int,default=8,choices=[4,8],help='Direct vector raster resolution multiplier')
    ap.add_argument('--runtime-matches',type=Path,help='Optional independently observed runtime tile keys')
    args=ap.parse_args();root=Path(__file__).resolve().parents[2];scale=args.scale
    args.out.mkdir(parents=True,exist_ok=True);game=args.out/'NPJH50247';images=game/'CN_HD';images.mkdir(parents=True,exist_ok=True)
    atlas,meta=load_atlas(root/'data/evidence/ui/ui-style-glyph-atlas.png',root/'data/evidence/ui/ui-style-glyph-atlas.json')
    mappings={a:{} for a in ['xxh64','quick']};manifest={'scale':scale,'game_id':'NPJH50247','ui':[],'fonts':[],'conflicts':[],'runtime_key_validation':{}}
    image_cache={};priority={a:{} for a in mappings};bundles={};origins={};semantics={a:{} for a in mappings}
    runtime=json.loads(args.runtime_matches.read_text()) if args.runtime_matches else []
    observed={}
    for r in runtime:
        observed.setdefault((r['file'],r['index'],r['logical_tile']),set()).update(r['matches'])
    def bundle(base,f):
        key=(str(base),f)
        if key not in bundles:bundles[key]=Bundle.parse((base/f).read_bytes())
        return bundles[key]
    def add(image,category,keys,rank,semantic):
        digest=hashlib.sha256(image.tobytes()+str(image.size).encode()).hexdigest()
        name=f'CN_HD/{category}/{digest[:24]}.png'
        if name not in image_cache:
            p=game/name;p.parent.mkdir(parents=True,exist_ok=True);image.save(p,optimize=True);image_cache[name]=digest
        for algorithm,key in keys:
            old=mappings[algorithm].get(key)
            if old is not None and old!=name:
                manifest['conflicts'].append({'algorithm':algorithm,'key':key,'first':old,'second':name,'rank':rank})
                if semantics[algorithm][key] != semantic:
                    first = np.array(Image.open(game / old).convert('RGBA'))
                    second = np.array(image)
                    difference = np.max(np.abs(first.astype(np.int16)-second.astype(np.int16)), axis=2) > 2
                    ys, xs = np.where(difference)
                    edge = scale  # One source pixel at the output scale.
                    if len(xs) and np.all((xs < edge) | (xs >= image.width-edge) |
                                          (ys < edge) | (ys >= image.height-edge)):
                        manifest['conflicts'][-1]['resolution'] = (
                            'shared cache tile retained; text variants differ only in the one-source-pixel edge fringe'
                        )
                        continue
                    raise ValueError(f'ambiguous different-text UI cache key {algorithm}:{key}, {origins.get((algorithm,key))} vs {f}#{i} tile {logical}')
                # Current build keys take precedence over legacy aliases. A
                # cache key may be shared by duplicate UI labels, but only
                # when their Chinese text is identical.
                if priority[algorithm][key] == rank and rank > 1:
                    first = np.array(Image.open(game/old).convert('RGBA'))
                    second = np.array(image)
                    if np.abs(first.astype(np.int16)-second.astype(np.int16)).max() <= 2:
                        manifest['conflicts'][-1]['resolution']='canonical background; RGBA difference at most 2/255'
                        continue
                    difference = np.max(np.abs(first.astype(np.int16)-second.astype(np.int16)), axis=2) > 2
                    ys, xs = np.where(difference)
                    # Vector blur can spill a fraction of a source pixel from
                    # the NEXT character into an otherwise identical tile.
                    # Only that edge fringe may share the first canonical tile.
                    edge = 2
                    if len(xs) and np.all((xs < edge) | (xs >= image.width-edge) |
                                          (ys < edge) | (ys >= image.height-edge)):
                        manifest['conflicts'][-1]['resolution']='identical interior; canonical 0.25-source-pixel edge fringe'
                        continue
                    if semantics[algorithm][key] != semantic:
                        raise ValueError(f'ambiguous different-text UI cache key {algorithm}:{key}, {origins.get((algorithm,key))} vs {f}#{i} tile {logical}')
                    # PPSSPP keys textures by palette + pixels when
                    # ignoreAddress=true. Repeated copies of the same label
                    # can therefore have different one-pixel vector sizing,
                    # but no key can distinguish those uses. Keep the first
                    # deterministic image and record the shared-key choice.
                    manifest['conflicts'][-1]['resolution'] = (
                        'first deterministic replacement retained; identical text shares PPSSPP cache key'
                    )
                    continue
                if priority[algorithm][key] == rank:
                    if semantics[algorithm][key] != semantic:
                        raise ValueError(f'ambiguous different-text UI cache key {algorithm}:{key}, {origins.get((algorithm,key))} vs {f}#{i} tile {logical}')
                    manifest['conflicts'][-1]['resolution'] = (
                        'first deterministic replacement retained; identical text shares PPSSPP cache key'
                    )
                    continue
                if priority[algorithm][key] > rank:continue
            mappings[algorithm][key]=name;priority[algorithm][key]=rank
            origins[(algorithm,key)]=f'{f}#{i} tile {logical}'
            semantics[algorithm][key]=semantic
        return name
    configs=['ui-text-patches.json','image-text-patches.json','tutorial-text-patches.json']
    key_checks=[]
    for config_name in configs:
        c=json.loads((root/'data/evidence/ui'/config_name).read_text())
        for entry_number,e in enumerate(c['entries'],1):
            f=e['file'];i=e['index'];source=Texture(bundle(args.source,f).payloads[i])
            if source.encode()!=source.source:raise ValueError(f'unmodified roundtrip failed {f}#{i}')
            hd,_=render_blocks(source,e['blocks'],atlas,meta,output_scale=scale)
            candidates=[('current',args.new_ui if (args.new_ui/f).is_file() and config_name=='ui-text-patches.json' else args.overlay,2),('previous',args.overlay,1)]
            row={'file':f,'index':i,'size':list(hd.size),'tiles':[]}
            # Add old aliases first, then overwrite them with current keys.
            for version,base,rank in reversed(candidates):
                native=Texture(bundle(base,f).payloads[i])
                for logical,raw,w,h,tile in tile_records(native,hd,scale,
                        [b['box'] for b in e['blocks'] if b.get('text')]):
                    pal=palette_key(native,w,h)
                    keys=[(a,f'00000000{pal:08x}{data_hash(raw,a):08x}') for a in mappings]
                    if version=='previous':
                        for observed_key in observed.get((f,i,logical),[]):
                            if observed_key[-8:]!=keys[0][1][-8:]:
                                # The user may have dumps from several earlier
                                # builds. A decoded visual match alone does not
                                # prove the same T4 indices. Do not bind it.
                                continue
                            key_checks.append(keys[0][1]==observed_key)
                            keys.append(('xxh64',observed_key))
                    semantic=tuple(b.get('text','') for b in e['blocks'] if b.get('text'))
                    name=add(tile,'UI',keys,rank,semantic)
                    row['tiles'].append({'variant':version,'logical':logical,'file':name,'keys':dict(keys)})
            manifest['ui'].append(row)
            if entry_number % 25 == 0:
                print(f'{config_name}: {entry_number}/{len(c["entries"])}',flush=True)
        print(f'Rendered {config_name}: {len(c["entries"])} images',flush=True)
    # Main text uses 16x16 cells in full 256x256 T4 pages. kanzi UTF-8 bytes
    # describe the actual target glyph, including alias slots.
    kanzi=(args.overlay/'PRELOAD/kanzi.bin').read_bytes();count=struct.unpack_from('<I',kanzi)[0]
    glyphs=[kanzi[4+i*6+2:4+i*6+5].split(b'\0')[0].decode('utf8') for i in range(count)]
    if count!=4096 or any(len(g)!=1 for g in glyphs):raise ValueError('unexpected main glyph table')
    cell=16*scale
    with tempfile.TemporaryDirectory(prefix='fate-hd-') as tmp:
        tmp=Path(tmp);(tmp/'glyphs.txt').write_text('\n'.join(glyphs)+'\n')
        subprocess.run(['swift',str(root/'scripts/pipeline/render_hd_font_glyphs.swift'),str(tmp/'glyphs.txt'),str(tmp/'glyphs.raw'),str(cell),str(13*scale),'HiraginoSansGB-W6','PingFangSC-Semibold','Apple Symbols'],check=True)
        raw=(tmp/'glyphs.raw').read_bytes()
        if len(raw)!=4+count*cell*cell:raise ValueError('main font renderer output length mismatch')
        font_bundle=bundle(args.overlay,'PRELOAD/font.txb')
        for page in range(16):
            im=Image.new('RGBA',(256*scale,256*scale),(255,255,255,0))
            tex=Texture(font_bundle.payloads[page])
            native_alpha=tex.image().getchannel('A')
            for slot in range(256):
                start=4+(page*256+slot)*cell*cell;alpha=Image.frombytes('L',(cell,cell),raw[start:start+cell*cell]);tile=Image.new('RGBA',(cell,cell),(255,255,255,0));tile.putalpha(alpha);im.paste(tile,((slot%16)*cell,(slot//16)*cell))
                # ASCII is sampled from the LEFT half of the source cell by
                # the game. Centering it in a full CJK cell clips e.g. 1F and
                # Latin dialogue. Keep the original halfwidth bearings and
                # baseline, while redrawing the ink from vector outlines.
                if ord(glyphs[page*256+slot]) < 128:
                    native=native_alpha.crop(((slot%16)*16,(slot//16)*16,(slot%16+1)*16,(slot//16+1)*16))
                    box=native.getbbox();ink=alpha.getbbox()
                    if box and ink:
                        aligned=Image.new('RGBA',(cell,cell),(255,255,255,0))
                        glyph=tile.crop(ink).resize(((box[2]-box[0])*scale,(box[3]-box[1])*scale),Image.Resampling.LANCZOS)
                        aligned.paste(glyph,(box[0]*scale,box[1]*scale))
                        im.paste(aligned,((slot%16)*cell,(slot//16)*cell))
            pal=palette_key(tex,256,256)
            keys=[(a,f'00000000{pal:08x}{data_hash(tex.pixel_data,a):08x}') for a in mappings]
            name=add(im,'Fonts',keys,3,('font-page',page));manifest['fonts'].append({'page':page,'file':name,'keys':dict(keys),'size':list(im.size)})
    options='[options]\nversion = 1\nhash = {algorithm}\nignoreAddress = true\nignoreMipmap = true\nreduceHash = false\n\n[hashes]\n'
    for algorithm,mapping in mappings.items():
        ini=options.format(algorithm=algorithm)+'\n'.join(f'{k} = {v}' for k,v in sorted(mapping.items()))+'\n'
        (game/f'textures-{algorithm}.ini').write_text(ini)
        if algorithm=='xxh64':(game/'textures.ini').write_text(ini)
    manifest['runtime_key_validation']={'observations':len(key_checks),'exact_cache_key_matches':sum(key_checks),'supplementary_observed_keys':len(key_checks)-sum(key_checks)}
    manifest['image_files']=len(image_cache);manifest['mappings']={a:len(m) for a,m in mappings.items()}
    used=set(image_cache)
    for path in images.rglob('*.png'):
        if path.relative_to(game).as_posix() not in used:
            path.unlink()
    manifest['image_files']=len(used)
    manifest['runtime_test']='not run; verified against existing gameplay dumps only'
    (args.out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:manifest[k] for k in ['image_files','mappings','runtime_key_validation']}),flush=True)

if __name__=='__main__':main()
