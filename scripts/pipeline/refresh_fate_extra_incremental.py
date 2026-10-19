#!/usr/bin/env python3
"""Apply changed translation rows to an already translated Fate/Extra CPK."""

from __future__ import annotations

import argparse
import json
import shutil
import struct
from collections import defaultdict
from pathlib import Path, PurePosixPath

from build_fate_extra import build_cpk, encode_cmp, encode_game_text, write_pak
from extract_fate_extra import decode_cmp, parse_cpk, read_cpk_entry, safe_relpath


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-translations", type=Path, required=True)
    parser.add_argument("--translations", type=Path, default=Path("work/translation/text.jsonl"))
    parser.add_argument("--references", type=Path, default=Path("work/translation/refs.jsonl"))
    parser.add_argument("--glyph-map", type=Path, default=Path("work/translation/glyph-map.json"))
    parser.add_argument("--motion-glyph-map", type=Path, help="character aliases for animated chapter-card text and its dedicated font")
    parser.add_argument("--previous-motion-glyph-map", type=Path, help="legacy aliases used to decode existing motion text before rewriting it")
    parser.add_argument("--force-motion-glyph-map", action="store_true", help="rewrite all day text-motion strings even when translations are unchanged")
    parser.add_argument(
        "--force-assets",
        type=Path,
        nargs="*",
        default=[],
        help="package-relative asset paths to copy from the current build and rebuild into the CPK",
    )
    parser.add_argument("--extract-root", type=Path, default=Path("work/extracted"))
    parser.add_argument("--manifest", type=Path, default=Path("work/extracted/manifest.json"))
    parser.add_argument("--build-root", type=Path, default=Path("work/build"))
    args = parser.parse_args()

    previous = {r["id"]: r.get("zh_cn", "") for r in load_jsonl(args.previous_translations)}
    current = {r["id"]: r.get("zh_cn", "") for r in load_jsonl(args.translations)}
    changed_ids = {key for key, value in current.items() if previous.get(key, "") != value}
    glyph_map = json.loads(args.glyph_map.read_text(encoding="utf-8"))
    motion_glyph_map = (
        json.loads(args.motion_glyph_map.read_text(encoding="utf-8"))
        if args.motion_glyph_map else glyph_map
    )
    previous_motion_glyph_map = (
        json.loads(args.previous_motion_glyph_map.read_text(encoding="utf-8"))
        if args.previous_motion_glyph_map else {}
    )
    refs_by_file: dict[str, list[dict]] = defaultdict(list)
    all_refs = load_jsonl(args.references)
    forced_motion_ids = {
        ref["id"] for ref in all_refs
        if args.force_motion_glyph_map
        and ref["file"].startswith("day/")
        and ({"motion", "poem"} & set(ref.get("kinds", [])))
    }
    changed_ids.update(forced_motion_ids)
    if not changed_ids:
        raise SystemExit("No changed translations or forced motion glyph-map updates were found.")
    for ref in all_refs:
        if ref["id"] in changed_ids:
            refs_by_file[ref["file"]].append(ref)

    build_assets = args.build_root / "assets"
    refresh_root = args.build_root / "refresh"
    overlay_root = refresh_root / "overlay"
    merged_root = refresh_root / "merged"
    shutil.rmtree(refresh_root, ignore_errors=True)
    overlay_root.mkdir(parents=True)
    applied = 0
    changed_files: set[Path] = set()

    for name, refs in refs_by_file.items():
        rel = safe_relpath("", name)
        if rel.parts[0] == "day":
            source = build_assets / "day" / Path(*rel.parts[1:])
        else:
            source = build_assets / "packages" / rel
        if not source.is_file():
            raise FileNotFoundError(f"translated DAT is missing from current build: {source}")
        original = source.read_bytes()
        data = bytearray(original)
        appended: dict[bytes, int] = {}
        touched = False
        for ref in refs:
            old_text = previous[ref["id"]]
            new_text = current[ref["id"]]
            old_mapping = glyph_map
            if ref["file"].startswith("day/") and ({"motion", "poem"} & set(ref.get("kinds", []))):
                # Existing builds may contain the old poem-only aliases;
                # decode them for comparison, then rewrite with the main map.
                old_mapping = {**glyph_map, **previous_motion_glyph_map}
                new_text = new_text.replace("\r", "").replace("\n", "")
                old_text = old_text.replace("\r", "").replace("\n", "")
            output_mapping = glyph_map
            if ref["file"].startswith("day/") and ({"motion", "poem"} & set(ref.get("kinds", []))):
                output_mapping = motion_glyph_map
            replacement = encode_game_text(new_text, output_mapping)
            expected_old = encode_game_text(old_text, old_mapping)
            pointer_values = {
                struct.unpack_from("<I", data, pointer)[0]
                for pointer in ref["pointer_offsets"]
            }
            if len(pointer_values) != 1:
                raise ValueError(f"DAT pointers disagree in {name} for {ref['id']}")
            text_offset = next(iter(pointer_values))
            end = data.find(b"\0", text_offset)
            if end < 0:
                raise ValueError(f"unterminated DAT string in {name} for {ref['id']}")
            existing = bytes(data[text_offset:end])
            if existing == replacement:
                continue
            if existing != expected_old:
                raise ValueError(
                    f"current DAT string differs from the saved translation in {name} for {ref['id']}"
                )
            if len(replacement) <= len(existing):
                data[text_offset:text_offset + len(replacement)] = replacement
                data[text_offset + len(replacement)] = 0
            else:
                new_offset = appended.get(replacement)
                if new_offset is None:
                    new_offset = len(data)
                    data.extend(replacement + b"\0")
                    appended[replacement] = new_offset
                for pointer in ref["pointer_offsets"]:
                    struct.pack_into("<I", data, pointer, new_offset)
            touched = True
            applied += 1
        if touched:
            data.extend(b"\0" * ((-len(data)) & 15))
            output = overlay_root / rel
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
            changed_files.add(rel)

    # Copy explicitly selected package assets into the merge overlay. This is
    # useful when a dedicated lookup table/texture changes without its source
    # DAT translations changing.
    for rel in args.force_assets:
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"forced asset path must stay package-relative: {rel}")
        source = build_assets / "packages" / rel
        if not source.is_file():
            raise FileNotFoundError(f"forced asset is missing from current build: {source}")
        target = overlay_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        changed_files.add(rel)

    if not changed_files:
        raise SystemExit("The changed translations already match the current DAT files.")

    # Keep unchanged translated DATs and font assets from the previous build,
    # while overlaying just the refreshed DAT files.
    shutil.copytree(build_assets, merged_root)
    for rel in changed_files:
        source = overlay_root / rel
        target = (merged_root / rel) if rel.parts[0] == "day" else (merged_root / "packages" / rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    source_cpk = args.build_root / "data.cpk"
    meta, cpk_rows = parse_cpk(source_cpk)
    cpk_by_path = {safe_relpath(row["DirName"], row["FileName"]).as_posix(): row for row in cpk_rows}
    replacements: dict[str, bytes] = {}
    handled_packages: set[str] = set()

    for package in manifest["packages"]:
        package_path = PurePosixPath(package["path"])
        package_name = package_path.as_posix()
        if package_name in handled_packages:
            continue
        package_rel = Path(*package_path.with_suffix("").parts)
        affected = any(path.parts[:len(package_rel.parts)] == package_rel.parts for path in changed_files)
        if not affected:
            continue
        handled_packages.add(package_name)
        row = cpk_by_path.get(package_name)
        if row is None:
            raise KeyError(f"package missing from current CPK: {package_name}")
        raw = read_cpk_entry(source_cpk, row)
        package_dir = merged_root / "packages" / package_rel
        original_package_dir = args.extract_root / "packages" / package_rel
        if package_path.suffix.lower() == ".cmp":
            pak = decode_cmp(raw)
            has_paths = struct.unpack_from("<H", pak, 2)[0] == 0x8000
            rebuilt = write_pak(package["entries"], package_dir, original_package_dir, has_paths)
            replacements[package_name] = encode_cmp(rebuilt)
        else:
            has_paths = struct.unpack_from("<H", raw, 2)[0] == 0x8000
            rebuilt = write_pak(package["entries"], package_dir, original_package_dir, has_paths)
            replacements[package_name] = rebuilt
        if len(replacements) % 25 == 0:
            print(f"Rebuilt {len(replacements)} affected packages…", flush=True)

    for rel in changed_files:
        if rel.parts[0] == "day":
            replacements[rel.as_posix()] = (merged_root / rel).read_bytes()

    output_cpk = args.build_root / "data.cpk.next"
    output_cpk.unlink(missing_ok=True)
    print(
        f"Prepared {len(changed_ids)} changed translations in {len(changed_files)} DAT files; "
        f"rebuilding {len(replacements)} CPK entries.",
        flush=True,
    )
    modified, output_size = build_cpk(source_cpk, output_cpk, replacements)
    check_meta, check_rows = parse_cpk(output_cpk)
    if len(check_rows) != len(cpk_rows) or check_meta["TocOffset"] == 0:
        raise ValueError("incremental CPK validation failed")
    source_cpk.replace(args.build_root / "data.cpk.previous")
    output_cpk.replace(source_cpk)
    (args.build_root / "data.cpk.previous").unlink()

    # Commit the refreshed DAT overlays only after the new CPK has been built.
    for rel in changed_files:
        source = overlay_root / rel
        target = (build_assets / rel) if rel.parts[0] == "day" else (build_assets / "packages" / rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    print(f"Updated {applied} text references in {len(changed_files)} DAT files.")
    print(f"Rebuilt {modified} CPK rows; wrote {source_cpk} ({output_size:,} bytes).")


if __name__ == "__main__":
    main()
