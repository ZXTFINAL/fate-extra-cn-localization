#!/usr/bin/env python3
"""Extend Fate/Extra's dedicated poem font table and atlas for Chinese captions."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import subprocess
import tempfile
from pathlib import Path

from patch_fate_extra_font import (
    load_font_txb,
    split_font_page,
    swizzle_t4,
    unswizzle_t4,
    write_font_txb,
)


WIDTH = HEIGHT = 256
# CPoem initializes its font at 14x14 (EBOOT VA 0xA6254), while the
# dialogue font uses 16x16. The runtime derives an 18x18 grid from the
# 256x256 texture, so its page boundary is 324 glyphs, not 256.
TILE = 14
# The drawing rectangle spans cell_size-1 texels and advances by 14. Keep
# the final row/column transparent, like the native atlas, to avoid clipping.
RASTER_SIZE = TILE - 1
FONT_SIZE = 12
PAGE_GLYPHS = (WIDTH // TILE) * (HEIGHT // TILE)


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def row_key(row: bytes) -> bytes:
    return row[:2][::-1]


def row_char(row: bytes) -> str:
    return row[2:5].split(b"\0", 1)[0].decode("utf-8")


def cp932_key(char: str) -> bytes | None:
    try:
        encoded = char.encode("cp932")
    except UnicodeEncodeError:
        return None
    if len(encoded) not in (1, 2):
        return None
    try:
        if encoded.decode("cp932") != char:
            return None
    except UnicodeDecodeError:
        return None
    return encoded.ljust(2, b"\0")


def make_row(key: bytes, char: str) -> bytes:
    encoded = char.encode("utf-8")
    if len(encoded) > 3:
        raise ValueError(f"poem font only supports BMP characters: U+{ord(char):04X}")
    return key[::-1] + encoded.ljust(3, b"\0") + b"\0"


def read_bitmap(pixels: list[bytearray], index: int) -> bytes:
    page, tile = divmod(index, PAGE_GLYPHS)
    tile_x = (tile % (WIDTH // TILE)) * TILE
    tile_y = (tile // (WIDTH // TILE)) * TILE
    source = pixels[page]
    output = bytearray(TILE * TILE)
    for y in range(TILE):
        start = (tile_y + y) * WIDTH + tile_x
        output[y * TILE:(y + 1) * TILE] = source[start:start + TILE]
    return bytes(output)


def write_bitmap(pixels: bytearray, bitmap: bytes, index: int) -> None:
    if len(bitmap) != TILE * TILE or not 0 <= index < PAGE_GLYPHS:
        raise ValueError("invalid poem glyph bitmap or atlas index")
    tile_x = (index % (WIDTH // TILE)) * TILE
    tile_y = (index // (WIDTH // TILE)) * TILE
    for y in range(TILE):
        start = (tile_y + y) * WIDTH + tile_x
        pixels[start:start + TILE] = bitmap[y * TILE:(y + 1) * TILE]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--translations", type=Path, default=Path("work/translation/text.jsonl"))
    parser.add_argument("--references", type=Path, default=Path("work/translation/refs.jsonl"))
    parser.add_argument("--glyph-map", type=Path, default=Path("work/translation/glyph-map.json"))
    parser.add_argument("--existing-poem-glyph-map", type=Path, help="preserve aliases already used by a matching poem.bin/font pair")
    parser.add_argument("--extract-root", type=Path, default=Path("work/extracted/packages/pack"))
    parser.add_argument("--build-root", type=Path, default=Path("work/build/font-w6-clean"))
    parser.add_argument("--renderer", type=Path, default=Path("tools/render_font_glyphs.swift"))
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    translation_rows = {row["id"]: row for row in load_jsonl(args.translations)}
    references = load_jsonl(args.references)
    # Animated day-script chapter captions use a dedicated poem lookup table
    # and atlas. Older extraction runs called these refs "poem"; current runs
    # call opcode 0x0126 "motion". Accept both labels for reproducible builds.
    poem_ids = {
        row["id"] for row in references
        if row["file"].startswith("day/") and ({"poem", "motion"} & set(row.get("kinds", [])))
    }
    missing_ids = sorted(
        key for key in poem_ids
        if key not in translation_rows or not translation_rows[key].get("zh_cn", "")
    )
    if missing_ids:
        raise SystemExit(f"{len(missing_ids)} day-poem captions still have no translation.")
    poem_texts = {
        key: translation_rows[key].get("zh_cn", "")
        for key in poem_ids
    }
    if not poem_texts:
        raise SystemExit(
            "No animated chapter-card text was found for the dedicated poem-font builder."
        )

    glyph_map: dict[str, str] = json.loads(args.glyph_map.read_text(encoding="utf-8"))
    existing_poem_map: dict[str, str] = (
        json.loads(args.existing_poem_glyph_map.read_text(encoding="utf-8"))
        if args.existing_poem_glyph_map else {}
    )
    source_dir = args.extract_root / "poem/interface/poem"
    source_map = source_dir / "poem.bin"
    source_font = source_dir / "poem_font.txb"
    raw_map = source_map.read_bytes()
    old_count = struct.unpack_from("<I", raw_map)[0]
    if 4 + old_count * 6 > len(raw_map):
        raise ValueError("truncated poem.bin row table")
    old_rows = [raw_map[4 + i * 6:10 + i * 6] for i in range(old_count)]
    old_trailing = raw_map[4 + old_count * 6:]
    if any(old_trailing):
        raise ValueError("unexpected nonzero poem.bin trailer")
    if [row_key(row) for row in old_rows] != sorted(row_key(row) for row in old_rows):
        raise ValueError("poem.bin keys are not sorted; cannot safely extend lookup table")

    needed_chars = {
        char for text in poem_texts.values() for char in text
        if char not in "\r\n\t"
    }
    # The day-poem renderer has its own character table and atlas. Keep its
    # CP932 aliases independent from PRELOAD and preserve every original row;
    # only add aliases that the original table does not contain.
    old_index_by_key = {row_key(row): i for i, row in enumerate(old_rows)}
    if len(old_index_by_key) != old_count:
        raise ValueError("poem.bin contains duplicate original character keys")

    poem_aliases: dict[str, str] = {}
    translated_rows_by_key: dict[bytes, bytes] = {}
    for char in sorted(needed_chars):
        # A map saved with the current poem atlas takes precedence. The main
        # dialogue map may have been reallocated since that atlas was built.
        alias = existing_poem_map.get(char, glyph_map.get(char, char))
        try:
            encoded = alias.encode("cp932")
        except UnicodeEncodeError as exc:
            raise ValueError(f"shared font alias is not CP932 encodable for {char!r}: {alias!r}") from exc
        if len(encoded) != 2 or encoded.decode("cp932") != alias:
            raise ValueError(
                f"shared poem aliases must be two-byte CP932 characters: {char!r} -> {alias!r}"
            )
        key = encoded
        if key in translated_rows_by_key:
            other = row_char(translated_rows_by_key[key])
            raise ValueError(f"shared font key collision: {char!r} and {other!r} -> {key.hex()}")
        poem_aliases[char] = alias
        translated_rows_by_key[key] = make_row(key, char)

    source_keys = set(old_index_by_key)
    translated_keys = set(translated_rows_by_key)

    # Preserve source rows and their glyphs unless a translated alias uses
    # that key. Merge new aliases into the sorted lookup table, then rebuild
    # the atlas in the same order so the runtime's row-index lookup still
    # points at the matching 14x14 glyph tile.
    indexed_rows = []
    for source_index, row in enumerate(old_rows):
        key = row_key(row)
        translated_row = translated_rows_by_key.get(key)
        indexed_rows.append((key, translated_row or row, source_index))
    for key, row in translated_rows_by_key.items():
        if key not in source_keys:
            indexed_rows.append((key, row, None))
    indexed_rows.sort(key=lambda item: item[0])
    output_rows = [row for _key, row, _source_index in indexed_rows]
    output_index_by_key = {key: index for index, (key, _row, _source_index) in enumerate(indexed_rows)}
    char_to_index = {
        char: output_index_by_key[alias.encode("cp932")]
        for char, alias in poem_aliases.items()
    }
    new_count = len(output_rows)
    if new_count > 2 * PAGE_GLYPHS:
        raise ValueError("poem lookup table exceeds the two-page atlas capacity")
    output_keys = [row_key(row) for row in output_rows]
    if output_keys != sorted(output_keys):
        raise ValueError("extended poem.bin keys are not sorted")

    has_paths, font_entries = load_font_txb(source_font)
    if has_paths or len(font_entries) != 2:
        raise ValueError(f"unexpected poem font bundle: paths={has_paths}, pages={len(font_entries)}")
    parts = [split_font_page(entry) for entry in font_entries]
    headers = [part[0] for part in parts]
    tails = [part[2] for part in parts]
    source_pixels = [unswizzle_t4(part[1]) for part in parts]
    page_count = math.ceil(new_count / PAGE_GLYPHS)
    while len(headers) < page_count:
        headers.append(headers[-1])
        tails.append(tails[-1])
        source_pixels.append(bytearray(WIDTH * HEIGHT))
    # Build texture cells in the same order as the rebuilt key table. Keeping
    # the source pages blank outside the assigned rows avoids stale glyphs
    # appearing if a lookup misses.
    target_pixels = [bytearray(WIDTH * HEIGHT) for _ in range(page_count)]
    for index, (_key, _row, source_index) in enumerate(indexed_rows):
        if source_index is None:
            continue
        source_page, source_tile = divmod(source_index, PAGE_GLYPHS)
        target_page, target_tile = divmod(index, PAGE_GLYPHS)
        write_bitmap(target_pixels[target_page], read_bitmap(source_pixels, source_index), target_tile)

    # Re-render translated characters in a consistent Chinese face. The
    # source atlas must be read with the same 14x14 geometry: reading it as
    # 16x16 creates partial cells and was the cause of the corrupted captions.
    translated_chars = sorted(needed_chars)
    rendered_bitmaps: dict[str, bytes] = {}
    if translated_chars:
        with tempfile.TemporaryDirectory(prefix="fate-extra-poem-glyphs-") as tmp:
            glyph_list = Path(tmp) / "glyphs.txt"
            glyph_raw = Path(tmp) / "glyphs.raw"
            glyph_list.write_text("\n".join(translated_chars) + "\n", encoding="utf-8")
            subprocess.run([
                "swift", str(args.renderer), str(glyph_list), str(glyph_raw),
                str(RASTER_SIZE), str(FONT_SIZE),
            ], check=True)
            rendered = glyph_raw.read_bytes()
        count = struct.unpack_from("<I", rendered)[0]
        bitmap_size = RASTER_SIZE * RASTER_SIZE
        if count != len(translated_chars) or len(rendered) != 4 + count * bitmap_size:
            raise ValueError("poem glyph renderer returned an invalid bitmap set")
        for i, char in enumerate(translated_chars):
            raster = rendered[4 + i * bitmap_size:4 + (i + 1) * bitmap_size]
            bitmap = bytearray(TILE * TILE)
            for y in range(RASTER_SIZE):
                bitmap[y * TILE:y * TILE + RASTER_SIZE] = (
                    raster[y * RASTER_SIZE:(y + 1) * RASTER_SIZE]
                )
            rendered_bitmaps[char] = bytes(bitmap)

    for char, bitmap in rendered_bitmaps.items():
        index = char_to_index[char]
        page, tile = divmod(index, PAGE_GLYPHS)
        write_bitmap(
            target_pixels[page],
            bytes((value * 15 + 127) // 255 for value in bitmap),
            tile,
        )

    rebuilt_font = [
        headers[page] + swizzle_t4(target_pixels[page]) + tails[page]
        for page in range(page_count)
    ]
    rebuilt_txb = write_font_txb(rebuilt_font, has_paths=False)
    # The source trailer is zero padding to a 16-byte boundary. Its length
    # changes with the row count; preserving the old 14 bytes misaligns the
    # following resources in poem.pak and charsel.pak.
    rebuilt_bin = struct.pack("<I", new_count) + b"".join(output_rows)
    rebuilt_bin += b"\0" * ((-len(rebuilt_bin)) & 15)

    # Verify every translated character is represented by the CP932 key that
    # the DAT encoder will write, and that the lookup resolves to that same
    # Unicode glyph. This catches text/font alias drift before packaging.
    output_by_key = {row_key(row): row_char(row) for row in output_rows}
    for char in needed_chars:
        key = poem_aliases[char].encode("cp932")
        resolved = output_by_key.get(key)
        if resolved != char:
            raise ValueError(
                f"poem glyph lookup mismatch for {char!r}: "
                f"encoded key {key.hex()} resolves to {resolved!r}"
            )

    build_pack = args.build_root / "assets/packages/pack"
    targets = [
        build_pack / "poem/interface/poem",
        build_pack / "charsel/interface/poem",
    ]
    for target in targets:
        target.mkdir(parents=True, exist_ok=True)
        (target / "poem.bin").write_bytes(rebuilt_bin)
        (target / "poem_font.txb").write_bytes(rebuilt_txb)

    # Save a dedicated encoder map for DAT poems. Chinese characters that lack
    # a direct key use an unused original CP932 key, avoiding dependence on the
    # dialogue font's private-use aliases in this separate renderer.
    poem_map_path = args.build_root / "poem-glyph-map.json"
    # Override the general dialogue-font aliases for every poem character,
    # including directly supported CP932 characters.
    poem_map = {char: poem_aliases.get(char, char) for char in needed_chars}
    poem_map_path.write_text(json.dumps(poem_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.report:
        report_path = args.report
    else:
        report_path = args.build_root / "poem-font-report.json"
    report = {
        "source_rows": old_count,
        "retained_source_rows": old_count,
        "removed_source_only_rows": 0,
        "added_rows": len(translated_keys - source_keys),
        "final_rows": new_count,
        "texture_pages": page_count,
        "glyph_cell_width": TILE,
        "glyph_cell_height": TILE,
        "glyph_raster_width": RASTER_SIZE,
        "glyph_raster_height": RASTER_SIZE,
        "glyphs_per_texture_row": WIDTH // TILE,
        "glyphs_per_texture_page": PAGE_GLYPHS,
        "table_size": len(rebuilt_bin),
        "day_poem_ids": len(poem_texts),
        "translated_characters": len(needed_chars),
        "aliased_characters": sum(alias != char for char, alias in poem_aliases.items()),
        "reused_original_keys": sum(key in old_index_by_key for key in translated_keys),
        "one_byte_aliases": sum(len(alias.encode("cp932")) == 1 for alias in poem_aliases.values()),
        "private_use_aliases_in_poem_text": sum(
            0xE000 <= ord(alias) <= 0xE757 for alias in poem_aliases.values()
        ),
        "rerendered_characters": len(rendered_bitmaps),
        "poem_glyph_map": str(poem_map_path),
        "poem_bin_sha256": hashlib.sha256(rebuilt_bin).hexdigest(),
        "poem_font_sha256": hashlib.sha256(rebuilt_txb).hexdigest(),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
