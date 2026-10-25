#!/usr/bin/env python3
"""Validate the public translation data, changeset and JSON artifacts.

Checks:
  * text.jsonl row count, unique IDs, non-empty translation count
  * every non-empty translation is encodable after glyph-map substitution
  * glyph-map keys/values are unique
  * ruby fixes and key reports parse and have expected sizes
  * overlay manifest matches every shipped binary byte-for-byte
  * inventory listing parses and has the expected file count
  * all JSON files under data/ parse

Exit code 0 on success, 1 on the first failed check.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
EXPECTED_ROWS = 19711
EXPECTED_TRANSLATED = 19709
EXPECTED_GLYPHS = 1649
EXPECTED_RUBY_FIXES = 1133
EXPECTED_OVERLAY_FILES = 584
EXPECTED_OVERLAY_BYTES = 72893072
EXPECTED_INVENTORY_FILES = 15962


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as error:
                fail(f"{path}:{number}: {error}")
    return rows


def check_text() -> None:
    rows = load_jsonl(DATA / "translation" / "text.jsonl")
    if len(rows) != EXPECTED_ROWS:
        fail(f"text.jsonl has {len(rows)} rows, expected {EXPECTED_ROWS}")

    ids = [row.get("id") for row in rows]
    if len(set(ids)) != len(ids):
        fail("text.jsonl contains duplicate IDs")

    translated = [row for row in rows if (row.get("zh_cn") or "").strip()]
    if len(translated) != EXPECTED_TRANSLATED:
        fail(f"non-empty translations: {len(translated)}, expected {EXPECTED_TRANSLATED}")

    glyph_map = json.loads((DATA / "translation" / "glyph-map.json").read_text(encoding="utf-8"))
    if len(glyph_map) != EXPECTED_GLYPHS:
        fail(f"glyph-map has {len(glyph_map)} entries, expected {EXPECTED_GLYPHS}")
    if len(set(glyph_map.values())) != len(glyph_map):
        fail("glyph-map has duplicate alias values")

    bad = []
    for row in translated:
        mapped = "".join(glyph_map.get(char, char) for char in row["zh_cn"])
        try:
            mapped.encode("cp932")
        except UnicodeEncodeError as error:
            bad.append((row.get("id"), str(error)))
    if bad:
        fail(f"{len(bad)} translations are not CP932-encodable, first: {bad[0]}")

    print(
        f"OK text.jsonl: {len(rows)} rows, {len(translated)} translated, "
        f"{len(glyph_map)} glyph aliases"
    )


def check_ruby() -> None:
    fixes = load_jsonl(DATA / "review" / "ruby-fixes.jsonl")
    if len(fixes) != EXPECTED_RUBY_FIXES:
        fail(f"ruby-fixes.jsonl has {len(fixes)} rows, expected {EXPECTED_RUBY_FIXES}")
    for row in fixes:
        if not all(key in row for key in ("id", "zh_cn", "reason")):
            fail(f"ruby fix missing required field: {row.get('id')}")
    print(f"OK ruby-fixes.jsonl: {len(fixes)} rows")


def check_json_files() -> None:
    parsed = 0
    for path in sorted(DATA.rglob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            fail(f"{path}: {error}")
        parsed += 1
    print(f"OK JSON artifacts: {parsed} files")


def check_overlay() -> None:
    root = DATA / "overlay"
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        fail(f"overlay manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files", [])
    if len(files) != EXPECTED_OVERLAY_FILES:
        fail(f"overlay manifest lists {len(files)} files, expected {EXPECTED_OVERLAY_FILES}")

    actual = [p for p in (root / "packages").rglob("*") if p.is_file() and p.name != ".DS_Store"]
    if len(actual) != len(files):
        fail(f"overlay directory has {len(actual)} files, manifest lists {len(files)}")

    total = 0
    for row in files:
        path = root / row["path"]
        if not path.is_file():
            fail(f"overlay file missing: {row['path']}")
        data = path.read_bytes()
        total += len(data)
        if len(data) != row["size"]:
            fail(f"overlay size mismatch: {row['path']}")
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            fail(f"overlay hash mismatch: {row['path']}")
    if total != EXPECTED_OVERLAY_BYTES:
        fail(f"overlay total bytes {total}, expected {EXPECTED_OVERLAY_BYTES}")
    print(f"OK overlay: {len(files)} files, {total} bytes verified")


def check_inventory() -> None:
    path = DATA / "inventory" / "extracted-tree.jsonl.gz"
    if not path.exists():
        fail(f"inventory missing: {path}")
    rows, total = 0, 0
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                fail(f"{path}:{number}: {error}")
            if not {"path", "size", "sha256"} <= row.keys():
                fail(f"{path}:{number}: missing fields")
            rows += 1
            total += row["size"]
    if rows != EXPECTED_INVENTORY_FILES:
        fail(f"inventory has {rows} rows, expected {EXPECTED_INVENTORY_FILES}")
    print(f"OK inventory: {rows} files, {total} bytes listed")


def check_forbidden_assets() -> None:
    # work/、iso/、dist/ 是本地目录，不入库；只检查会被提交的路径。
    skipped = {"work", "iso", "dist", ".git"}
    forbidden = []
    for pattern in ("*.iso", "*.cpk", "*.7z"):
        for path in ROOT.rglob(pattern):
            relative = path.relative_to(ROOT)
            if relative.parts and relative.parts[0] in skipped:
                continue
            forbidden.append(path)
    if forbidden:
        fail(f"forbidden game assets in repository: {forbidden[:3]}")
    print("OK no ISO/CPK/archive assets")


def main() -> None:
    if not DATA.is_dir():
        fail(f"data directory missing: {DATA}")
    check_text()
    check_ruby()
    check_overlay()
    check_inventory()
    check_json_files()
    check_forbidden_assets()
    print("All checks passed.")


if __name__ == "__main__":
    main()
