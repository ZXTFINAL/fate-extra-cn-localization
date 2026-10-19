#!/usr/bin/env python3
"""Compact Fate/Extra's extended glyph table into its 4096-glyph runtime range."""

from __future__ import annotations

import argparse
import collections
import json
import math
import struct
from pathlib import Path

from patch_fate_extra_font import load_font_txb, split_font_page, swizzle_t4, unswizzle_t4, write_font_txb


WIDTH = HEIGHT = 256
TILE = 16
PAGE_GLYPHS = (WIDTH // TILE) * (HEIGHT // TILE)
MODE_TEXT = {
    0: "本作独有的硬派模式。\n\r适合有一定RPG经验的玩家。",
    1: "整体调整得更易上手。\n\r适合不熟悉RPG的玩家。",
    2: "已读取通关存档。",
    3: "跳过部分预选赛，\n\r从选择从者开始游戏。",
}


def read_rows(path: Path) -> tuple[int, list[bytes], bytes]:
    data = path.read_bytes()
    count = struct.unpack_from("<I", data)[0]
    end = 4 + count * 6
    if end > len(data):
        raise ValueError(f"truncated kanzi.bin: declares {count} glyphs")
    rows = [data[4 + i * 6:10 + i * 6] for i in range(count)]
    return count, rows, data[end:]


def decode_key(row: bytes) -> str:
    try:
        return row[:2][::-1].decode("cp932").replace("\0", "")
    except UnicodeDecodeError:
        return ""


def count_runtime_chars(
    translations_path: Path,
    glyph_map: dict[str, str],
) -> collections.Counter[str]:
    counts: collections.Counter[str] = collections.Counter()
    with translations_path.open(encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            row = json.loads(line)
            text = row.get("zh_cn") or row.get("jp", "")
            weight = max(1, int(row.get("reference_count", 1) or 1))
            counts.update({glyph_map.get(char, char): weight * text.count(char) for char in set(text)})
    # The mode-select's message table lives outside the extracted DAT text table.
    for text in MODE_TEXT.values():
        mapped = "".join(glyph_map.get(char, char) for char in text)
        counts.update(mapped)
    return counts


def read_glyph_bitmap(texture_pages: list[bytes], index: int) -> tuple[bytes, int, int]:
    page, tile = divmod(index, PAGE_GLYPHS)
    if page >= len(texture_pages):
        raise ValueError(f"glyph index {index} points past the font texture bundle")
    pixels = texture_pages[page]
    tile_x = (tile % (WIDTH // TILE)) * TILE
    tile_y = (tile // (WIDTH // TILE)) * TILE
    bitmap = bytearray(TILE * TILE)
    for y in range(TILE):
        start = (tile_y + y) * WIDTH + tile_x
        bitmap[y * TILE:(y + 1) * TILE] = pixels[start:start + TILE]
    return bytes(bitmap), tile_x, tile_y


def write_glyph_bitmap(pixels: bytearray, bitmap: bytes, index: int) -> None:
    page, tile = divmod(index, PAGE_GLYPHS)
    if page >= math.ceil((index + 1) / PAGE_GLYPHS):
        raise ValueError("invalid destination page")
    tile_x = (tile % (WIDTH // TILE)) * TILE
    tile_y = (tile // (WIDTH // TILE)) * TILE
    for y in range(TILE):
        start = (tile_y + y) * WIDTH + tile_x
        pixels[start:start + TILE] = bitmap[y * TILE:(y + 1) * TILE]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-root", type=Path, default=Path("work/build"))
    parser.add_argument("--extract-root", type=Path, default=Path("work/extracted"))
    parser.add_argument("--translations", type=Path, default=Path("work/translation/text.jsonl"))
    parser.add_argument("--glyph-map", type=Path, default=Path("work/translation/glyph-map.json"))
    parser.add_argument("--max-glyphs", type=int, default=4096)
    args = parser.parse_args()

    font_dir = args.build_root / "assets/packages/pack/PRELOAD"
    kanzi_path = font_dir / "kanzi.bin"
    font_path = font_dir / "font.txb"
    original_kanzi = args.extract_root / "packages/pack/PRELOAD/kanzi.bin"

    current_count, current_rows, trailing = read_rows(kanzi_path)
    original_count, original_rows, _original_trailing = read_rows(original_kanzi)
    if current_count <= args.max_glyphs:
        print(f"Font already fits: {current_count} glyphs <= {args.max_glyphs}.")
        return
    if original_count > current_count or len(current_rows) != current_count:
        raise ValueError("current and original glyph tables do not match expected layout")

    glyph_map = json.loads(args.glyph_map.read_text(encoding="utf-8"))
    use_counts = count_runtime_chars(args.translations, glyph_map)
    # Rows for Chinese PUA aliases follow the untouched Japanese rows in this build.
    custom_rows = current_rows[original_count:]
    remove_count = current_count - args.max_glyphs

    candidates = []
    for index, row in enumerate(original_rows):
        char = decode_key(row)
        if len(char) == 1 and "\u3400" <= char <= "\u9fff" and use_counts[char] == 0:
            candidates.append(index)
    # Prefer high-codepoint, unreferenced CJK entries; these are least likely
    # to be needed by unextracted UI, and all scripted references are counted above.
    candidates.sort(reverse=True)
    if len(candidates) < remove_count:
        raise ValueError(
            f"only {len(candidates)} unused Japanese CJK glyphs are available; "
            f"need {remove_count} to stay within {args.max_glyphs}"
        )
    removed = set(candidates[:remove_count])
    kept_original = [i for i in range(original_count) if i not in removed]
    new_rows = [current_rows[i] for i in kept_original] + custom_rows
    if len(new_rows) != args.max_glyphs:
        raise ValueError(f"compacted table has {len(new_rows)} rows, expected {args.max_glyphs}")

    has_paths, texture_entries = load_font_txb(font_path)
    if has_paths:
        raise ValueError("expected an unpathed font texture bundle")
    texture_parts = [split_font_page(entry) for entry in texture_entries]
    headers = [part[0] for part in texture_parts]
    texture_tails = [part[2] for part in texture_parts]
    texture_pages = [unswizzle_t4(part[1]) for part in texture_parts]
    needed_pages = math.ceil(args.max_glyphs / PAGE_GLYPHS)
    if needed_pages > len(headers):
        raise ValueError("not enough source font texture pages")

    rebuilt_pixels = [bytearray(WIDTH * HEIGHT) for _ in range(needed_pages)]
    old_indices = kept_original + list(range(original_count, current_count))
    for new_index, old_index in enumerate(old_indices):
        bitmap, _x, _y = read_glyph_bitmap(texture_pages, old_index)
        page = new_index // PAGE_GLYPHS
        write_glyph_bitmap(rebuilt_pixels[page], bitmap, new_index % PAGE_GLYPHS)

    rebuilt_pages = [
        headers[page] + swizzle_t4(rebuilt_pixels[page]) + texture_tails[page]
        for page in range(needed_pages)
    ]
    rebuilt_kanzi = struct.pack("<I", args.max_glyphs) + b"".join(new_rows) + trailing
    kanzi_path.write_bytes(rebuilt_kanzi)
    font_path.write_bytes(write_font_txb(rebuilt_pages, has_paths=False))

    removed_report = [
        {"old_index": index, "character": decode_key(original_rows[index])}
        for index in sorted(removed)
    ]
    (args.build_root / "font-compaction-report.json").write_text(
        json.dumps({
            "original_font_glyph_count": original_count,
            "extended_font_glyph_count": current_count,
            "new_font_glyph_count": len(new_rows),
            "texture_pages": needed_pages,
            "removed_unreferenced_japanese_glyphs": removed_report,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Compacted {current_count} glyphs to {len(new_rows)} across "
        f"{needed_pages} pages; dropped {remove_count} unreferenced Japanese CJK glyphs."
    )


if __name__ == "__main__":
    main()
