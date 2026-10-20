#!/usr/bin/env python3
"""Read every animated chapter caption back from a built CPK, without gameplay.

The expected bytes come from the translation and encoder map. The visible text
is resolved separately through every packaged poem.bin, so a consistent but
incorrect encoder map cannot make the audit pass. Duplicate CPK TOC rows are
all examined rather than silently selecting the last row for a path.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import struct

from extract_fate_extra import decode_cmp, parse_cpk, read_cpk_entry, safe_relpath


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def members(raw: bytes, manifest: dict | None = None) -> list[tuple[str | None, bytes]]:
    if len(raw) < 4:
        raise ValueError("truncated package header")
    count, flags = struct.unpack_from("<HH", raw)
    if flags not in (0, 0x8000) or 4 + 4 * count > len(raw):
        raise ValueError("invalid package header")
    if manifest is not None and count != len(manifest["entries"]):
        raise ValueError("package manifest member count mismatch")
    sizes = struct.unpack_from(f"<{count}I", raw, 4)
    offset = (4 + 4 * count + 15) & ~15
    result = []
    for index, size in enumerate(sizes):
        name = None
        if flags == 0x8000:
            if offset + 64 > len(raw):
                raise ValueError("truncated package member name")
            name = raw[offset:offset + 64].split(b"\0", 1)[0].decode("cp932")
            offset += 64
        if manifest is not None:
            expected_name = manifest["entries"][index]["path"]
            if name is not None and name != expected_name:
                raise ValueError(f"package member name mismatch: {name} / {expected_name}")
            name = expected_name
        if offset + size > len(raw):
            raise ValueError("truncated package member payload")
        result.append((name, raw[offset:offset + size]))
        offset += size
    return result


def poem_table(raw: bytes) -> tuple[dict[bytes, str], int]:
    if len(raw) < 4:
        raise ValueError("truncated poem.bin header")
    count = struct.unpack_from("<I", raw)[0]
    end = 4 + count * 6
    if end > len(raw) or any(raw[end:]):
        raise ValueError("invalid poem.bin size or padding")
    keys = []
    table = {}
    for index in range(count):
        row = raw[4 + index * 6:10 + index * 6]
        key = row[:2][::-1]
        char = row[2:5].split(b"\0", 1)[0].decode("utf-8")
        if len(char) != 1 or key in table:
            raise ValueError("invalid poem.bin character or duplicate key")
        keys.append(key)
        table[key] = char
    if keys != sorted(keys):
        raise ValueError("poem.bin is not sorted for runtime binary lookup")
    return table, count


def atlas_pages(raw: bytes) -> int:
    pages = members(raw)
    for _name, page in pages:
        if len(page) < 0x20:
            raise ValueError("truncated poem texture")
        fmt, swizzled, width, height = struct.unpack_from("<HHHH", page, 0x10)
        data_size = struct.unpack_from("<I", page, 0x1C)[0]
        if (fmt, swizzled, width, height, data_size) != (4, 1, 256, 256, 32768):
            raise ValueError("unexpected poem texture metadata")
        if len(page) < 0x30 + data_size:
            raise ValueError("truncated poem texture pixels")
    return len(pages)


def resolve(raw: bytes, table: dict[bytes, str]) -> tuple[str, list[str]]:
    output, missing = [], []
    pos = 0
    while pos < len(raw):
        lead = raw[pos]
        length = 2 if 0x81 <= lead <= 0x9F or 0xE0 <= lead <= 0xFC else 1
        code = raw[pos:pos + length]
        if len(code) != length:
            missing.append(code.hex())
            output.append("\ufffd")
            break
        char = table.get(code.ljust(2, b"\0"))
        if char is None:
            missing.append(code.hex())
            char = "\ufffd"
        output.append(char)
        pos += length
    return "".join(output), missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpk", type=Path, required=True)
    parser.add_argument("--translations", type=Path, required=True)
    parser.add_argument("--references", type=Path, default=Path("work/translation/refs.jsonl"))
    parser.add_argument("--poem-glyph-map", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=Path("work/extracted/manifest.json"))
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    translations = {row["id"]: row["zh_cn"] for row in jsonl(args.translations)}
    glyph_map = json.loads(args.poem_glyph_map.read_text(encoding="utf-8"))
    references = [row for row in jsonl(args.references)
                  if row["file"].startswith("day/") and {"motion", "poem"} & set(row.get("kinds", []))]
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    manifests = {row["path"]: row for row in manifest["packages"]}
    _meta, rows = parse_cpk(args.cpk)
    by_path = defaultdict(list)
    for index, row in enumerate(rows):
        by_path[safe_relpath(row["DirName"], row["FileName"]).as_posix()].append((index, row))

    resources, tables, errors, map_errors = [], {}, [], []
    for path in ("pack/poem.pak", "pack/charsel.pak"):
        if not by_path[path]:
            errors.append(f"missing CPK package: {path}")
        for toc_index, row in by_path[path]:
            label = f"{path}@toc{toc_index}"
            try:
                raw = read_cpk_entry(args.cpk, row)
                if path.endswith(".cmp"):
                    raw = decode_cmp(raw)
                package = dict(members(raw, manifests.get(path)))
                table_raw = package["interface/poem/poem.bin"]
                font_raw = package["interface/poem/poem_font.txb"]
                table, count = poem_table(table_raw)
                pages = atlas_pages(font_raw)
                if count > pages * 324:
                    raise ValueError("poem table exceeds its 14x14 texture grid capacity")
                tables[label] = table
                resources.append({"resource": label, "cpk_toc_index": toc_index,
                                  "table_sha256": hashlib.sha256(table_raw).hexdigest(),
                                  "atlas_sha256": hashlib.sha256(font_raw).hexdigest(),
                                  "table_rows": count, "atlas_pages": pages})
                for char, alias in glyph_map.items():
                    key = alias.encode("cp932").ljust(2, b"\0")
                    if table.get(key) != char:
                        map_errors.append({"resource": label, "expected": char,
                                           "alias_hex": key.hex(), "resolved": table.get(key)})
            except (ValueError, KeyError, struct.error, UnicodeError) as exc:
                errors.append(f"{label}: {exc}")
    table_equal = len({item["table_sha256"] for item in resources}) == 1 and bool(resources)
    atlas_equal = len({item["atlas_sha256"] for item in resources}) == 1 and bool(resources)
    if not table_equal:
        errors.append("packaged poem.bin copies differ or are absent")
    if not atlas_equal:
        errors.append("packaged poem atlas copies differ or are absent")

    checks = []
    data_cache = {}
    for ref in references:
        path = ref["file"]
        if not by_path[path]:
            errors.append(f"missing caption DAT: {path}")
        for toc_index, row in by_path[path]:
            result = {"id": ref["id"], "file": path, "cpk_toc_index": toc_index,
                      "pointer_offsets": ref["pointer_offsets"]}
            try:
                expected = translations[ref["id"]].replace("\r", "").replace("\n", "")
                # Deliberately independent of the staging encoder implementation.
                encoded = "".join(glyph_map.get(char, char) for char in expected).encode("cp932")
                cache_key = (path, toc_index)
                if cache_key not in data_cache:
                    data_cache[cache_key] = read_cpk_entry(args.cpk, row)
                data = data_cache[cache_key]
                pointers = [struct.unpack_from("<I", data, offset)[0] for offset in ref["pointer_offsets"]]
                if len(set(pointers)) != 1:
                    raise ValueError("reference pointers disagree")
                pointer = pointers[0]
                if not 0 <= pointer < len(data):
                    raise ValueError("caption pointer outside DAT")
                end = data.find(b"\0", pointer)
                if end < 0:
                    raise ValueError("unterminated caption")
                actual = data[pointer:end]
                decoded = {name: resolve(actual, table) for name, table in tables.items()}
                actual_text = {name: text for name, (text, _missing) in decoded.items()}
                missing = {name: keys for name, (_text, keys) in decoded.items() if keys}
                result.update({"text_offset": pointer, "expected": expected,
                               "expected_bytes_hex": encoded.hex(), "actual_bytes_hex": actual.hex(),
                               "actual_resolved": actual_text, "missing_glyph_keys": missing,
                               "encoding_matches": actual == encoded,
                               "rendered_matches": bool(decoded) and not missing and all(text == expected for text in actual_text.values())})
            except (ValueError, KeyError, struct.error, UnicodeError) as exc:
                result.update({"error": str(exc), "encoding_matches": False, "rendered_matches": False})
            checks.append(result)

    mismatches = [row for row in checks if not row["encoding_matches"] or not row["rendered_matches"]]
    bad_ids = sorted({row["id"] for row in mismatches})
    bad_files = dict(sorted(Counter(row["file"] for row in mismatches).items()))
    report = {"audit_type": "CPK readback of every animated day caption and every packaged poem font copy",
              "cpk": str(args.cpk), "cpk_sha256": sha256(args.cpk),
              "translations_sha256": sha256(args.translations),
              "references_sha256": sha256(args.references),
              "poem_glyph_map_sha256": sha256(args.poem_glyph_map),
              "reference_count": len(references), "unique_ids": len({row["id"] for row in references}),
              "dat_files": len({row["file"] for row in references}), "cpk_copy_checks": len(checks),
              "encoding_mismatch_count": sum(not row["encoding_matches"] for row in checks),
              "rendered_mismatch_count": sum(not row["rendered_matches"] for row in checks),
              "mismatch_count": len(mismatches), "mismatch_ids": bad_ids, "mismatch_files": bad_files,
              "font_resources": resources, "font_tables_identical": table_equal, "font_atlases_identical": atlas_equal,
              "glyph_map_binding_errors": map_errors, "structural_errors": errors,
              "mismatches": mismatches, "all_caption_checks": checks}
    report["passed"] = not mismatches and not errors and not map_errors and bool(checks)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("passed", "reference_count", "cpk_copy_checks", "mismatch_count", "encoding_mismatch_count", "rendered_mismatch_count", "mismatch_files")}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
