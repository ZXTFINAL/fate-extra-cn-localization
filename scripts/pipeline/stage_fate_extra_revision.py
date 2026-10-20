#!/usr/bin/env python3
"""Patch reviewed strings against actual bytes of a previously working CPK.

Unchanged PAK members always come from that CPK, never a stale extraction.
Translation and glyph-alias changes both trigger string updates. Every pointer
is checked against the prior encoded translation before edits.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import shutil
import struct

from build_fate_extra import build_cpk, encode_cmp, encode_game_text
from extract_fate_extra import decode_cmp, parse_cpk, read_cpk_entry, safe_relpath


def jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines() if l.strip()]


class Package:
    def __init__(self, raw: bytes, manifest: dict):
        self.raw = raw
        count, flags = struct.unpack_from('<HH', raw)
        if count != len(manifest['entries']):
            raise ValueError(f'package entry count changed: {manifest["path"]}')
        sizes = struct.unpack_from(f'<{count}I', raw, 4)
        pos = (4 + 4 * count + 15) & ~15
        self.header = raw[:pos]
        self.names, self.payloads = [], []
        self.by_path = {e['path']: e['index'] for e in manifest['entries']}
        for entry, size in zip(manifest['entries'], sizes):
            name = raw[pos:pos + 64] if flags == 0x8000 else b''
            pos += len(name)
            if name and name.split(b'\0', 1)[0].decode('cp932') != entry['path']:
                raise ValueError(f'package member name changed: {entry["path"]}')
            payload = raw[pos:pos + size]
            if len(payload) != size:
                raise ValueError('truncated package member')
            self.names.append(name)
            self.payloads.append(payload)
            pos += size
        self.tail = raw[pos:]

    def get(self, path: str) -> bytes:
        return self.payloads[self.by_path[path]]

    def put(self, path: str, data: bytes) -> None:
        self.payloads[self.by_path[path]] = data

    def rebuild(self) -> bytes:
        out = bytearray(self.header)
        struct.pack_into(f'<{len(self.payloads)}I', out, 4, *(len(p) for p in self.payloads))
        for name, data in zip(self.names, self.payloads):
            out.extend(name)
            out.extend(data)
        out.extend(self.tail)
        return bytes(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-cpk', type=Path, required=True)
    ap.add_argument('--previous-translations', type=Path, required=True)
    ap.add_argument('--translations', type=Path, required=True)
    ap.add_argument('--previous-glyph-map', type=Path, required=True)
    ap.add_argument('--glyph-map', type=Path, required=True)
    ap.add_argument('--previous-poem-glyph-map', type=Path, action='append',
                    help='poem map used to encode the source CPK; repeat for a verified mixed-map recovery; defaults to --poem-glyph-map')
    ap.add_argument('--poem-glyph-map', type=Path, required=True)
    ap.add_argument('--references', type=Path, default=Path('work/translation/refs.jsonl'))
    ap.add_argument('--manifest', type=Path, default=Path('work/extracted/manifest.json'))
    ap.add_argument('--overlay', type=Path, required=True, help='image/font overlays, packages/pack/...')
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--prepare-only', action='store_true')
    ap.add_argument('--overrides', type=Path, help='optional per-reference translations: id,file,text_offset,zh_cn')
    args = ap.parse_args()
    old = {r['id']: r['zh_cn'] for r in jsonl(args.previous_translations)}
    new = {r['id']: r['zh_cn'] for r in jsonl(args.translations)}
    old_map = json.loads(args.previous_glyph_map.read_text(encoding='utf-8'))
    new_map = json.loads(args.glyph_map.read_text(encoding='utf-8'))
    poem_map = json.loads(args.poem_glyph_map.read_text(encoding='utf-8'))
    old_poem_paths = args.previous_poem_glyph_map or [args.poem_glyph_map]
    old_poem_maps = [json.loads(p.read_text(encoding='utf-8')) for p in old_poem_paths]
    changed = {i for i, t in new.items() if old.get(i) != t}
    overrides = {(r['file'], r['id'], r['text_offset']): r['zh_cn'] for r in jsonl(args.overrides)} if args.overrides else {}
    refs_by_file = defaultdict(list)
    encoded_cache = {}
    encoding_only_ids = set()
    encoding_only_references = 0

    def encoded_versions(ref):
        file = ref['file']
        poem = file.startswith('day/') and bool({'motion', 'poem'} & set(ref.get('kinds', [])))
        override_key = (file, ref['id'], ref['text_offset'])
        cache_key = (ref['id'], poem, override_key if override_key in overrides else None)
        if cache_key not in encoded_cache:
            before = old[ref['id']]
            after = overrides.get(override_key, new[ref['id']])
            if poem:
                before = before.replace('\n', '').replace('\r', '')
                after = after.replace('\n', '').replace('\r', '')
            prior_maps = old_poem_maps if poem else [old_map]
            encoded_prior = []
            for mapping in prior_maps:
                try:
                    encoded_prior.append(encode_game_text(before, mapping))
                except ValueError:
                    # A mixed-map recovery can include a newer caption whose
                    # characters did not yet exist in the oldest font map.
                    if not poem or len(prior_maps) == 1:
                        raise
            if not encoded_prior:
                raise ValueError(f'no declared prior map can encode {file} {ref["id"]}')
            expected = tuple(dict.fromkeys(encoded_prior))
            wanted = encode_game_text(after, poem_map if poem else new_map)
            encoded_cache[cache_key] = (expected, wanted, poem)
        return encoded_cache[cache_key]

    for ref in jsonl(args.references):
        override_key = (ref['file'], ref['id'], ref['text_offset'])
        expected, wanted, _poem = encoded_versions(ref)
        encoding_changed = any(prior != wanted for prior in expected)
        if ref['id'] in changed or override_key in overrides or encoding_changed:
            refs_by_file[ref['file']].append(ref)
            if ref['id'] not in changed and override_key not in overrides and encoding_changed:
                encoding_only_ids.add(ref['id'])
                encoding_only_references += 1
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    package_manifest = {Path(m['path']).with_suffix('').as_posix(): m for m in manifest['packages']}
    _, cpk_rows = parse_cpk(args.source_cpk)
    cpk_by_path = {safe_relpath(r['DirName'], r['FileName']).as_posix(): r for r in cpk_rows}
    packages = {}

    def package(name: str) -> Package:
        if name not in packages:
            m = package_manifest[name]
            raw = read_cpk_entry(args.source_cpk, cpk_by_path[m['path']])
            packages[name] = Package(decode_cmp(raw) if m['path'].endswith('.cmp') else raw, m)
            if len(packages) % 25 == 0:
                print(f'Loaded {len(packages)} working packages', flush=True)
        return packages[name]

    replacements = {}
    records = []
    args.out.mkdir(parents=True, exist_ok=True)
    dat_root = args.out / 'text-overlay'
    shutil.rmtree(dat_root, ignore_errors=True)
    for file, refs in refs_by_file.items():
        rel = Path(file)
        if rel.parts[0] == 'day':
            original = read_cpk_entry(args.source_cpk, cpk_by_path[file])
        else:
            original = package('pack/' + rel.parts[0]).get(Path(*rel.parts[1:]).as_posix())
        data = bytearray(original)
        pending = []
        # Read all current pointers before changing shared strings/pointers.
        for ref in refs:
            expected, wanted, poem = encoded_versions(ref)
            ptrs = {struct.unpack_from('<I', original, p)[0] for p in ref['pointer_offsets']}
            if len(ptrs) != 1:
                raise ValueError(f'pointer disagreement: {file} {ref["id"]}')
            at = next(iter(ptrs))
            end = original.find(b'\0', at)
            if at >= len(original) or end < at:
                raise ValueError(f'invalid current string offset: {file} {ref["id"]}')
            existing = original[at:end]
            if existing not in expected:
                alternatives = ','.join(v.hex() for v in expected)
                raise ValueError(f'prior text mismatch: {file} {ref["id"]}: current={existing.hex()} expected={alternatives}')
            pending.append((ref, at, existing, wanted, poem))
        new_offsets = {}
        for ref, at, existing, wanted, poem in pending:
            # Always append changes. This also separates context-dependent
            # translations whose current pointers share the same old string.
            if wanted != existing:
                if wanted not in new_offsets:
                    new_offsets[wanted] = len(data)
                    data.extend(wanted + b'\0')
                at = new_offsets[wanted]
                for pointer in ref['pointer_offsets']:
                    struct.pack_into('<I', data, pointer, at)
            for pointer in ref['pointer_offsets']:
                ptr = struct.unpack_from('<I', data, pointer)[0]
                if data[ptr:data.find(b'\0', ptr)] != wanted:
                    raise ValueError('post-patch pointer validation failed')
            records.append({'id': ref['id'], 'file': file, 'text_offset': at,
                            'pointer_offsets': ref['pointer_offsets'], 'bytes_hex': wanted.hex(),
                            'is_poem': poem, 'bytes_changed': existing != wanted})
        data.extend(b'\0' * (-len(data) % 16))
        if data != original:
            out = dat_root / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            if rel.parts[0] == 'day':
                replacements[file] = bytes(data)
            else:
                package('pack/' + rel.parts[0]).put(Path(*rel.parts[1:]).as_posix(), bytes(data))

    overlay_count = 0
    for path in sorted((args.overlay / 'packages/pack').rglob('*')):
        if not path.is_file():
            continue
        rel = path.relative_to(args.overlay / 'packages')
        pack_name = Path(*rel.parts[:2]).as_posix()
        member = Path(*rel.parts[2:]).as_posix()
        package(pack_name).put(member, path.read_bytes())
        overlay_count += 1
    for name, p in packages.items():
        m = package_manifest[name]
        rebuilt = p.rebuild()
        if rebuilt != p.raw:
            replacements[m['path']] = encode_cmp(rebuilt) if m['path'].endswith('.cmp') else rebuilt
    report = {'changed_ids': len(changed), 'changed_dat_files': len(refs_by_file), 'applied_references': len(records),
              'encoding_only_ids': len(encoding_only_ids), 'encoding_only_references': encoding_only_references,
              'rewritten_poem_references': sum(r['is_poem'] and r['bytes_changed'] for r in records),
              'overlay_resources': overlay_count, 'cpk_paths': len(replacements), 'prepared_only': args.prepare_only,
              'translation_sha256': hashlib.sha256(args.translations.read_bytes()).hexdigest(),
              'poem_glyph_map_sha256': hashlib.sha256(args.poem_glyph_map.read_bytes()).hexdigest(),
              'source_poem_glyph_maps_sha256': [hashlib.sha256(p.read_bytes()).hexdigest() for p in old_poem_paths],
              'replacement_sha256': {k: hashlib.sha256(v).hexdigest() for k, v in replacements.items()}}
    (args.out / 'applied-references.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records), encoding='utf-8')
    if not args.prepare_only:
        output_cpk = args.out / 'data.cpk'
        modified, size = build_cpk(args.source_cpk, output_cpk, replacements)
        _, final_rows = parse_cpk(output_cpk)
        if len(final_rows) != len(cpk_rows):
            raise ValueError('final CPK row count changed')
        confirmed = 0
        for row in final_rows:
            name = safe_relpath(row['DirName'], row['FileName']).as_posix()
            if name in replacements:
                if read_cpk_entry(output_cpk, row) != replacements[name]:
                    raise ValueError(f'final CPK payload mismatch: {name}')
                confirmed += 1
        if modified != confirmed:
            raise ValueError('modified CPK duplicate count mismatch')
        report.update({'cpk_modified_rows': modified, 'cpk_bytes': size})
    (args.out / 'build-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k != 'replacement_sha256'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
