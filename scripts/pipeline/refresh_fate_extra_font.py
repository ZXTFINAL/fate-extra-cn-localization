#!/usr/bin/env python3
"""Refresh the font and mode-select packages in the translated CPK."""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

from build_fate_extra import build_cpk, encode_cmp, write_pak
from extract_fate_extra import decode_cmp, parse_cpk, read_cpk_entry, safe_relpath


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-root", type=Path, default=Path("work/build"))
    parser.add_argument("--extract-root", type=Path, default=Path("work/extracted"))
    args = parser.parse_args()

    build_root = args.build_root
    manifest = json.loads((args.extract_root / "manifest.json").read_text(encoding="utf-8"))
    package_paths = ("pack/PRELOAD.pak", "pack/modeselect.pak")
    packages = {item["path"]: item for item in manifest["packages"]}
    cpk = build_root / "data.cpk"
    meta, rows = parse_cpk(cpk)
    rows_by_path = {
        safe_relpath(item["DirName"], item["FileName"]).as_posix(): item
        for item in rows
    }
    replacements = {}
    rebuilt_packages = {}
    for package_rel in package_paths:
        package = packages[package_rel]
        row = rows_by_path[package_rel]
        raw = read_cpk_entry(cpk, row)
        compressed = raw.startswith(b"IECP")
        pak = decode_cmp(raw) if compressed else raw
        has_paths = struct.unpack_from("<H", pak, 2)[0] == 0x8000
        package_dir = build_root / "assets/packages" / Path(package_rel).with_suffix("")
        original_dir = args.extract_root / "packages" / Path(package_rel).with_suffix("")
        rebuilt_pak = write_pak(package["entries"], package_dir, original_dir, has_paths)
        replacements[package_rel] = encode_cmp(rebuilt_pak) if compressed else rebuilt_pak
        rebuilt_packages[package_rel] = rebuilt_pak

    next_cpk = build_root / "data.cpk.next"
    next_cpk.unlink(missing_ok=True)
    modified, size = build_cpk(cpk, next_cpk, replacements)
    check_meta, check_rows = parse_cpk(next_cpk)
    check_by_path = {
        safe_relpath(item["DirName"], item["FileName"]).as_posix(): item
        for item in check_rows
    }
    if modified != len(package_paths) or len(check_rows) != len(rows):
        raise ValueError("asset-package CPK validation failed")
    for package_rel, rebuilt_pak in rebuilt_packages.items():
        check_raw = read_cpk_entry(next_cpk, check_by_path[package_rel])
        check_pak = decode_cmp(check_raw) if check_raw.startswith(b"IECP") else check_raw
        if check_pak != rebuilt_pak:
            raise ValueError(f"asset package validation failed: {package_rel}")
    cpk.replace(build_root / "data.cpk.previous")
    next_cpk.replace(cpk)
    (build_root / "data.cpk.previous").unlink()
    print(f"Rebuilt {', '.join(package_paths)}; wrote {cpk} ({size:,} bytes).")


if __name__ == "__main__":
    main()
