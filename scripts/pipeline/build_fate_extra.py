#!/usr/bin/env python3
"""Apply a translated JSONL table and rebuild the affected Japanese CPK."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import struct
import sys
import tempfile
from pathlib import Path, PurePosixPath

from extract_fate_extra import decode_cmp, parse_cpk, safe_relpath


ALIGNMENT = 2048


def align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def encode_game_text(text: str, glyph_map: dict[str, str]) -> bytes:
    mapped = "".join(glyph_map.get(char, char) for char in text)
    try:
        return mapped.encode("cp932")
    except UnicodeEncodeError as e:
        unsupported = sorted(set(mapped[e.start:e.end]))
        chars = ", ".join(f"{c} (U+{ord(c):04X})" for c in unsupported)
        raise ValueError(f"text contains characters with no CP932/glyph mapping: {chars}") from e


def apply_dat_translations(
    extracted_packages: Path,
    extracted_cpk: Path,
    build_assets: Path,
    translations_path: Path,
    refs_path: Path,
    glyph_map_path: Path | None,
    motion_glyph_map_path: Path | None,
) -> tuple[set[Path], int]:
    translations = {row["id"]: row.get("zh_cn", "") for row in load_jsonl(translations_path)}
    refs = load_jsonl(refs_path)
    glyph_map = json.loads(glyph_map_path.read_text(encoding="utf-8")) if glyph_map_path else {}
    motion_glyph_map = (
        json.loads(motion_glyph_map_path.read_text(encoding="utf-8"))
        if motion_glyph_map_path else glyph_map
    )
    changed_files: set[Path] = set()
    applied = 0
    has_pack_prefix = (extracted_packages / "pack").is_dir()
    package_root = extracted_packages / "pack" if has_pack_prefix else extracted_packages
    package_output_prefix = Path("pack") if has_pack_prefix else Path()
    by_file: dict[str, list[dict]] = {}
    for ref in refs:
        replacement = translations.get(ref["id"], "")
        if replacement and replacement != "" :
            by_file.setdefault(ref["file"], []).append((ref, replacement))

    for game_path, records in by_file.items():
        rel = safe_relpath("", game_path)
        if rel.parts[0] == "day":
            source = extracted_cpk / rel
            output = build_assets / "day" / Path(*rel.parts[1:])
        else:
            source = package_root / rel
            output = build_assets / "packages" / package_output_prefix / rel
        if not source.is_file():
            raise FileNotFoundError(f"referenced DAT file missing: {source}")
        data = bytearray(source.read_bytes())
        appended: dict[bytes, int] = {}
        modified = False
        for ref, replacement in records:
            mapping = glyph_map
            if ref["file"].startswith("day/") and ({"motion", "poem"} & set(ref.get("kinds", []))):
                # These animated chapter-card captions use the dedicated poem
                # lookup table and font, so their byte aliases must match it.
                mapping = motion_glyph_map
                replacement = replacement.replace("\r", "").replace("\n", "")
            new_bytes = encode_game_text(replacement, mapping)
            text_offset = ref["text_offset"]
            end = data.find(b"\0", text_offset)
            if end < 0:
                raise ValueError(f"unterminated source string: {game_path} @ 0x{text_offset:x}")
            old_bytes = bytes(data[text_offset:end])
            if old_bytes == new_bytes:
                continue
            if len(new_bytes) <= len(old_bytes):
                # Clear the full original slot.  Some scripted title-card
                # renderers use a stored character count instead of stopping
                # at the first NUL; leaving the source tail after a shorter
                # translation makes old characters leak into the new caption.
                slot_size = len(old_bytes) + 1
                data[text_offset:text_offset + slot_size] = (
                    new_bytes + b"\0" * (slot_size - len(new_bytes))
                )
            else:
                new_offset = appended.get(new_bytes)
                if new_offset is None:
                    new_offset = len(data)
                    data.extend(new_bytes + b"\0")
                    appended[new_bytes] = new_offset
                for pointer_offset in ref["pointer_offsets"]:
                    struct.pack_into("<I", data, pointer_offset, new_offset)
            modified = True
            applied += 1
        if modified:
            data.extend(b"\0" * ((-len(data)) & 15))
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
            changed_files.add(rel)
    return changed_files, applied


def write_pak(entries: list[dict], package_dir: Path, original_package_dir: Path, has_paths: bool) -> bytes:
    count = len(entries)
    out = bytearray(struct.pack("<HH", count, 0x8000 if has_paths else 0))
    payloads = []
    for entry in entries:
        rel = safe_relpath("", entry["path"])
        payload_path = package_dir / rel
        if not payload_path.is_file():
            payload_path = original_package_dir / rel
        if not payload_path.is_file():
            raise FileNotFoundError(f"PAK member missing: {payload_path}")
        payload = payload_path.read_bytes()
        out.extend(struct.pack("<I", len(payload)))
        payloads.append((entry["path"], payload))
    out.extend(b"\0" * ((-len(out)) & 15))
    for name, payload in payloads:
        if has_paths:
            encoded_name = name.encode("shift_jis")
            if len(encoded_name) > 64:
                raise ValueError(f"PAK path exceeds its 64-byte field: {name}")
            out.extend(encoded_name + b"\0" * (64 - len(encoded_name)))
        out.extend(payload)
    return bytes(out)


_CMP_ENCODER = None


def _native_cmp_encoder():
    global _CMP_ENCODER
    if _CMP_ENCODER is not None:
        return _CMP_ENCODER
    source = Path(__file__).with_name("cmp_lzss_encoder.c")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
    suffix = ".dylib" if sys.platform == "darwin" else ".so"
    library = Path(tempfile.gettempdir()) / f"fate_extra_cmp_{digest}{suffix}"
    if not library.exists():
        command = ["cc", "-O3", "-fPIC"]
        command.extend(["-dynamiclib"] if sys.platform == "darwin" else ["-shared"])
        command.extend(["-o", str(library), str(source)])
        subprocess.run(command, check=True)
    encoder = ctypes.CDLL(str(library))
    encode = encoder.fate_cmp_encode
    encode.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                       ctypes.POINTER(ctypes.POINTER(ctypes.c_uint8)),
                       ctypes.POINTER(ctypes.c_uint32)]
    encode.restype = ctypes.c_int
    encoder.fate_cmp_free.argtypes = [ctypes.c_void_p]
    _CMP_ENCODER = (encoder, encode)
    return _CMP_ENCODER


def encode_cmp(data: bytes) -> bytes:
    """Encode IECP LZSS with the native bounded-memory encoder."""
    if len(data) <= 0xFFFFFFFF:
        encoder, encode = _native_cmp_encoder()
        output = ctypes.POINTER(ctypes.c_uint8)()
        output_size = ctypes.c_uint32()
        status = encode(ctypes.c_char_p(data), len(data), ctypes.byref(output),
                        ctypes.byref(output_size))
        if status:
            raise MemoryError(f"native IECP encoder failed with status {status}")
        try:
            return ctypes.string_at(output, output_size.value)
        finally:
            encoder.fate_cmp_free(output)

    """Fallback implementation for inputs beyond the native 32-bit limit."""
    import collections

    # A long chain of identical 3-byte sequences is common in background and
    # scenario packages. Searching every candidate makes a full rebuild
    # needlessly quadratic. Recent candidates tend to give the same or longer
    # matches, and any selected candidate is a valid LZSS reference.
    max_candidates = 64
    chains: dict[bytes, collections.deque[int]] = {}
    stream = bytearray()
    pos = 0
    while pos < len(data):
        control_pos = len(stream)
        stream.append(0)
        control = 0
        tokens = bytearray()
        for bit in range(8):
            if pos >= len(data):
                break
            best_len = 0
            best_pos = -1
            if pos + 2 < len(data):
                key = data[pos:pos + 3]
                candidates = chains.get(key, ())
                for candidate_index, candidate in enumerate(reversed(candidates)):
                    if candidate_index >= max_candidates:
                        break
                    distance = pos - candidate
                    if distance > 4096:
                        break
                    length = 3
                    limit = min(18, len(data) - pos)
                    while length < limit and data[candidate + (length % distance)] == data[pos + length]:
                        length += 1
                    if length > best_len:
                        best_len, best_pos = length, candidate
                        if length == limit:
                            break
            if best_len >= 3:
                dictionary_offset = (0xFEE + best_pos) & 0xFFF
                tokens.extend((dictionary_offset & 0xFF, ((dictionary_offset >> 4) & 0xF0) | (best_len - 3)))
                length = best_len
            else:
                control |= 1 << bit
                tokens.append(data[pos])
                length = 1
            end = pos + length
            for index in range(pos, end):
                if index + 2 < len(data):
                    item = data[index:index + 3]
                    queue = chains.setdefault(item, collections.deque())
                    queue.append(index)
                    while queue and index - queue[0] > 4096:
                        queue.popleft()
            pos = end
        stream[control_pos] = control
        stream.extend(tokens)
    return b"IECP" + struct.pack("<I", len(data)) + stream


def utf_field_offsets(data: bytes, utf_offset: int) -> tuple[int, int, list[list[tuple[str, int, int, int]]]]:
    if data[utf_offset:utf_offset + 4] != b"@UTF":
        raise ValueError(f"@UTF missing at 0x{utf_offset:x}")
    content = utf_offset + 8
    rows_offset, _strings_offset, _data_offset, _name_offset, ncols, row_width, nrows = struct.unpack_from(
        ">IIIIHHI", data, content
    )
    schema_pos = content + 24
    schema = []
    widths = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 8, 8: 4, 10: 4, 11: 8}
    for _ in range(ncols):
        flags = data[schema_pos]
        name_offset = struct.unpack_from(">I", data, schema_pos + 1)[0]
        string_base = content + _strings_offset
        name_start = string_base + name_offset
        name_end = data.find(b"\0", name_start)
        name = data[name_start:name_end].decode("utf-8", "replace")
        storage, typ = flags & 0xF0, flags & 0x0F
        schema_pos += 5
        width = widths[typ]
        const_pos = -1
        if storage == 0x30:
            const_pos = schema_pos
            schema_pos += width
        elif storage not in (0x10, 0x50):
            raise ValueError(f"unknown UTF column storage mode 0x{storage:x}")
        schema.append((name, storage, typ, width, const_pos))
    if schema_pos - content != rows_offset:
        raise ValueError("UTF schema length does not match rows offset")
    rows = []
    row_start = content + rows_offset
    for row_index in range(nrows):
        row_pos = row_start + row_index * row_width
        fields = []
        for name, storage, typ, width, const_pos in schema:
            if storage == 0x50:
                fields.append((name, row_pos, width, typ))
                row_pos += width
            elif storage == 0x30:
                fields.append((name, const_pos, width, typ))
            else:
                fields.append((name, -1, width, typ))
        rows.append(fields)
    return row_start, row_width, rows


def write_utf_value(buf: bytearray, fields: list[tuple[str, int, int, int]], name: str, value: int) -> None:
    for field_name, offset, width, typ in fields:
        if field_name != name:
            continue
        if offset < 0:
            raise ValueError(f"UTF field {name} is a zero-storage column")
        if typ not in (2, 3, 4, 5, 6):
            raise ValueError(f"UTF field {name} is not an integer")
        buf[offset:offset + width] = value.to_bytes(width, "big", signed=typ in (3, 5))
        return
    raise KeyError(f"UTF field missing: {name}")


def build_cpk(source_cpk: Path, output_cpk: Path, replacements: dict[str, bytes]) -> tuple[int, int]:
    with source_cpk.open("rb") as source:
        header_prefix_data = source.read(0x2000)
    header, header_rows = __import__("extract_fate_extra").parse_utf(header_prefix_data, 0x10)
    header_row = header_rows[0]
    meta, rows = parse_cpk(source_cpk)
    base = meta["ContentBase"]
    content_start = header_row["ContentOffset"]
    toc_offset = header_row["TocOffset"]
    etoc_offset = header_row["EtocOffset"]
    etoc_size = header_row["EtocSize"]
    with source_cpk.open("rb") as f:
        f.seek(etoc_offset)
        etoc = f.read(etoc_size)
    if len(etoc) != etoc_size:
        raise ValueError("truncated ETOC")

    with source_cpk.open("rb") as source:
        header_prefix = bytearray(source.read(content_start))
    source_file = source_cpk.open("rb")
    output_cpk.parent.mkdir(parents=True, exist_ok=True)
    with output_cpk.open("w+b") as out:
        out.write(header_prefix)
        cursor = content_start
        toc_updates = {}
        count_modified = 0
        row_index_by_identity = {id(row): index for index, row in enumerate(rows)}
        for row in sorted(rows, key=lambda item: item["AbsoluteOffset"]):
            cursor = align_up(cursor, ALIGNMENT)
            if out.tell() < cursor:
                out.write(b"\0" * (cursor - out.tell()))
            rel = safe_relpath(row["DirName"], row["FileName"]).as_posix()
            data = replacements.get(rel)
            if data is None:
                source_file.seek(row["AbsoluteOffset"])
                data = source_file.read(row["FileSize"])
                if len(data) != row["FileSize"]:
                    raise ValueError(f"truncated source CPK entry {rel}")
                file_size, extract_size = row["FileSize"], row["ExtractSize"]
            else:
                file_size = extract_size = len(data)
                count_modified += 1
            row_index = row_index_by_identity[id(row)]
            toc_updates[row_index] = (cursor - base, file_size, extract_size)
            out.write(data)
            cursor += len(data)
        new_etoc_offset = align_up(cursor, ALIGNMENT)
        if out.tell() < new_etoc_offset:
            out.write(b"\0" * (new_etoc_offset - out.tell()))
        out.write(etoc)
        content_size = new_etoc_offset - content_start
        final_size = out.tell()

        toc_frame_utf = toc_offset + 0x10
        _, _, toc_rows = utf_field_offsets(header_prefix, toc_frame_utf)
        for row_index, (file_offset, file_size, extract_size) in toc_updates.items():
            fields = toc_rows[row_index]
            write_utf_value(header_prefix, fields, "FileOffset", file_offset)
            write_utf_value(header_prefix, fields, "FileSize", file_size)
            write_utf_value(header_prefix, fields, "ExtractSize", extract_size)
        _, _, header_fields = utf_field_offsets(header_prefix, 0x10)
        write_utf_value(header_prefix, header_fields[0], "EtocOffset", new_etoc_offset)
        write_utf_value(header_prefix, header_fields[0], "ContentSize", content_size)
        out.seek(0)
        out.write(header_prefix)
        out.truncate(final_size)
    source_file.close()
    return count_modified, output_cpk.stat().st_size


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--translations", type=Path, default=Path("work/translation/text.jsonl"))
    parser.add_argument("--references", type=Path, default=Path("work/translation/refs.jsonl"))
    parser.add_argument("--glyph-map", type=Path, help="JSON mapping unsupported Chinese characters to allocated CP932 placeholder glyphs")
    parser.add_argument("--motion-glyph-map", type=Path, help="JSON character aliases for animated chapter-card text and its dedicated font")
    parser.add_argument("--extract-root", type=Path, default=Path("work/extracted"))
    parser.add_argument("--manifest", type=Path, default=Path("work/extracted/manifest.json"))
    parser.add_argument("--source-cpk", type=Path, required=True)
    parser.add_argument("--output-cpk", type=Path, default=Path("work/build/data.cpk"))
    args = parser.parse_args()

    build_assets = args.output_cpk.parent / "assets"
    changed, applied = apply_dat_translations(
        args.extract_root / "packages",
        args.extract_root / "cpk",
        build_assets,
        args.translations,
        args.references,
        args.glyph_map,
        args.motion_glyph_map,
    )
    asset_changes = set()
    package_asset_root = build_assets / "packages"
    if package_asset_root.exists():
        asset_changes = {p.relative_to(package_asset_root) for p in package_asset_root.rglob("*") if p.is_file()}
    changed.update(asset_changes)
    if not changed:
        raise SystemExit("No nonblank translations were found; edit zh_cn entries before building.")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    replacements = {}
    for package in manifest["packages"]:
        package_path = PurePosixPath(package["path"])
        if package_path.as_posix() in replacements:
            continue
        package_rel = Path(*package_path.with_suffix("").parts)
        if not any(path.parts[:len(package_rel.parts)] == package_rel.parts for path in changed):
            continue
        raw_path = args.extract_root / "cpk" / Path(*package_path.parts)
        raw = raw_path.read_bytes()
        build_package_dir = build_assets / "packages" / package_rel
        original_package_dir = args.extract_root / "packages" / package_rel
        if package_path.suffix.lower() == ".cmp":
            pak = decode_cmp(raw)
            has_paths = struct.unpack_from("<H", pak, 2)[0] == 0x8000
            rebuilt = write_pak(package["entries"], build_package_dir, original_package_dir, has_paths)
            replacements[package_path.as_posix()] = encode_cmp(rebuilt)
        else:
            has_paths = struct.unpack_from("<H", raw, 2)[0] == 0x8000
            rebuilt = write_pak(package["entries"], build_package_dir, original_package_dir, has_paths)
            replacements[package_path.as_posix()] = rebuilt

    for rel in changed:
        if rel.parts[0] == "day":
            replacements[rel.as_posix()] = (build_assets / "day" / Path(*rel.parts[1:])).read_bytes()

    modified, output_size = build_cpk(args.source_cpk, args.output_cpk, replacements)
    print(f"Translated {applied} strings in {len(changed)} DAT files")
    print(f"Rebuilt {len(replacements)} PAK/CMP packages; updated {modified} CPK rows")
    print(f"Wrote {args.output_cpk} ({output_size:,} bytes)")


if __name__ == "__main__":
    main()
