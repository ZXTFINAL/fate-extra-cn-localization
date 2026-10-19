#!/usr/bin/env python3
"""Allocate unused kanji glyphs for translated Chinese and rebuild PRELOAD fonts."""

from __future__ import annotations

import argparse
import json
import struct
import subprocess
import tempfile
import unicodedata
from pathlib import Path

from extract_fate_extra import unpack_pak


WIDTH = HEIGHT = 256
FONT_PAGE_SIZE = 256
TEX_HEADER_SIZE = 0x30
TEX_DATA_SIZE = WIDTH * HEIGHT // 2


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def parse_kanzi(data: bytes) -> tuple[int, list[dict]]:
    count = struct.unpack_from("<I", data, 0)[0]
    rows = []
    for index in range(count):
        start = 4 + index * 6
        record = data[start:start + 6]
        if len(record) != 6:
            raise ValueError("truncated kanzi.bin record table")
        sjis = record[:2][::-1]
        try:
            char = sjis.decode("cp932")
        except UnicodeDecodeError:
            char = ""
        rows.append({"index": index, "sjis": sjis, "char": char, "record_offset": start})
    return count, rows


def unswizzle_t4(data: bytes) -> bytearray:
    if len(data) != WIDTH * HEIGHT // 2:
        raise ValueError(f"unexpected T4 image length: {len(data)}")
    pixels = bytearray(WIDTH * HEIGHT)
    row_bytes = WIDTH // 2
    block_bytes, block_height = 16, 8
    blocks_per_row = row_bytes // block_bytes
    for block_y in range(0, HEIGHT, block_height):
        for block_x in range(blocks_per_row):
            block_start = (block_y // block_height) * row_bytes * block_height + block_x * block_bytes * block_height
            for row in range(block_height):
                source = block_start + row * block_bytes
                y = block_y + row
                for byte_index in range(block_bytes):
                    value = data[source + byte_index]
                    x = block_x * block_bytes * 2 + byte_index * 2
                    pixels[y * WIDTH + x] = value & 0x0F
                    pixels[y * WIDTH + x + 1] = value >> 4
    return pixels


def swizzle_t4(pixels: bytes | bytearray) -> bytes:
    if len(pixels) != WIDTH * HEIGHT:
        raise ValueError("unexpected linear glyph atlas dimensions")
    output = bytearray(WIDTH * HEIGHT // 2)
    row_bytes = WIDTH // 2
    block_bytes, block_height = 16, 8
    blocks_per_row = row_bytes // block_bytes
    for block_y in range(0, HEIGHT, block_height):
        for block_x in range(blocks_per_row):
            block_start = (block_y // block_height) * row_bytes * block_height + block_x * block_bytes * block_height
            for row in range(block_height):
                destination = block_start + row * block_bytes
                y = block_y + row
                for byte_index in range(block_bytes):
                    x = block_x * block_bytes * 2 + byte_index * 2
                    output[destination + byte_index] = pixels[y * WIDTH + x] | (pixels[y * WIDTH + x + 1] << 4)
    return bytes(output)


def load_font_txb(path: Path) -> tuple[bool, list[bytes]]:
    data = path.read_bytes()
    count, flags = struct.unpack_from("<HH", data, 0)
    has_paths = flags == 0x8000
    sizes = list(struct.unpack_from("<" + "I" * count, data, 4)) if count else []
    pos = (4 + 4 * count + 15) & ~15
    entries = []
    for size in sizes:
        if has_paths:
            pos += 64
        entry = data[pos:pos + size]
        if len(entry) != size:
            raise ValueError("truncated font texture PAK")
        entries.append(entry)
        pos += size
    return has_paths, entries


def write_font_txb(entries: list[bytes], has_paths: bool) -> bytes:
    out = bytearray(struct.pack("<HH", len(entries), 0x8000 if has_paths else 0))
    for entry in entries:
        out.extend(struct.pack("<I", len(entry)))
    out.extend(b"\0" * ((-len(out)) & 15))
    for entry in entries:
        out.extend(entry)
    return bytes(out)


def is_chinese_glyph(char: str) -> bool:
    codepoint = ord(char)
    if (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x3000 <= codepoint <= 0x303F
        or 0xFF00 <= codepoint <= 0xFFEF
    ):
        return True
    if codepoint in {0x00B7, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D, 0x2026}:
        return True
    return unicodedata.category(char).startswith("P") and unicodedata.east_asian_width(char) in {"F", "W"}


def split_font_page(entry: bytes) -> tuple[bytes, bytes, bytes]:
    """Split one Fate font TEX entry into TEX header, swizzled T4 data, and CLUT tail."""
    if len(entry) < TEX_HEADER_SIZE:
        raise ValueError("truncated font texture entry")
    texture_type, swizzled = struct.unpack_from("<HH", entry, 0x10)
    width, height = struct.unpack_from("<HH", entry, 0x14)
    data_size = struct.unpack_from("<I", entry, 0x1C)[0]
    if (texture_type, swizzled, width, height, data_size) != (4, 1, WIDTH, HEIGHT, TEX_DATA_SIZE):
        raise ValueError(
            "unexpected font TEX metadata: "
            f"type={texture_type}, swizzled={swizzled}, {width}x{height}, data={data_size}"
        )
    data_end = TEX_HEADER_SIZE + data_size
    if len(entry) < data_end:
        raise ValueError("truncated font TEX pixel data")
    return entry[:TEX_HEADER_SIZE], entry[TEX_HEADER_SIZE:data_end], entry[data_end:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--translations", type=Path, default=Path("work/translation/text.jsonl"))
    parser.add_argument("--refs", type=Path, default=Path("work/translation/refs.jsonl"))
    parser.add_argument("--extract-root", type=Path, default=Path("work/extracted/packages"))
    parser.add_argument("--out-root", type=Path, default=Path("work/build/assets/packages/pack/PRELOAD"))
    parser.add_argument("--glyph-map", type=Path, default=Path("work/translation/glyph-map.json"))
    parser.add_argument("--allocations", type=Path, default=Path("work/translation/glyph-allocations.jsonl"))
    parser.add_argument("--renderer", type=Path, default=Path("tools/render_font_glyphs.swift"))
    args = parser.parse_args()

    rows = load_jsonl(args.translations)
    nonblank = [row for row in rows if row.get("zh_cn")]
    if not nonblank:
        raise SystemExit("No Chinese translations are present yet; font mapping will be allocated when text is translated.")

    root = args.extract_root / "pack/PRELOAD"
    kanzi_path = root / "kanzi.bin"
    font_path = root / "font.txb"
    original_kanzi = kanzi_path.read_bytes()
    glyph_count, glyph_rows = parse_kanzi(original_kanzi)
    glyph_index_by_char = {row["char"]: row["index"] for row in glyph_rows if len(row["char"]) == 1}

    translated_chars = {char for row in nonblank for char in row["zh_cn"]}
    # Keep every original Japanese glyph intact. Reusing rare Japanese slots
    # corrupts any unextracted UI text that still contains those characters.
    # Unsupported Chinese characters get dedicated CP932 user-defined slots.
    mapping: dict[str, str] = {}
    remaining_jp_refs: dict[str, int] = {}
    for row in rows:
        weight = row.get("reference_count", 1)
        for char in set(row["jp"]):
            remaining_jp_refs[char] = remaining_jp_refs.get(char, 0) + weight
    unsupported = set()
    for char in translated_chars:
        if char in "\r\n\t" or (ord(char) < 128):
            continue
        if ord(char) > 0xFFFF:
            raise ValueError(f"kanzi.bin stores only three-byte UTF-8 BMP glyphs; cannot install U+{ord(char):X}")
        try:
            char.encode("cp932")
        except UnicodeEncodeError:
            unsupported.add(char)
            continue
        if char not in glyph_index_by_char:
            unsupported.add(char)
    new_unsupported = sorted(unsupported)
    new_placeholder_rows = []
    next_index = glyph_count

    def append_private_placeholder(placeholder: str) -> None:
        nonlocal next_index
        row = {
            "index": next_index,
            "sjis": placeholder.encode("cp932"),
            "char": placeholder,
            "record_offset": 4 + next_index * 6,
            "remaining_jp_refs": 0,
        }
        new_placeholder_rows.append(row)
        glyph_index_by_char[placeholder] = next_index
        next_index += 1

    # CP932's user-defined range has enough slots for this translation set.
    # Append each entry so the game can resolve it without changing any
    # original Japanese character-to-glyph mapping.
    for target in new_unsupported:
        placeholder = None
        for codepoint in range(0xE000, 0xE758):
            char = chr(codepoint)
            if char in translated_chars or char in mapping.values():
                continue
            if char in glyph_index_by_char:
                continue
            try:
                encoded = char.encode("cp932")
            except UnicodeEncodeError:
                continue
            if len(encoded) == 2 and encoded.decode("cp932") == char:
                placeholder = char
                break
        if placeholder is None:
            raise ValueError("not enough Shift-JIS user-defined characters for added glyph slots")
        mapping[target] = placeholder
        append_private_placeholder(placeholder)

    glyph_count += len(new_placeholder_rows)
    glyph_rows.extend(new_placeholder_rows)

    # Render every translated Han/punctuation glyph in one Chinese face. Keeping
    # native CP932 glyphs untouched mixes Japanese and Chinese metrics, which
    # makes adjacent characters visibly differ in size and weight.
    target_chars = sorted(
        char for char in translated_chars
        if is_chinese_glyph(char) and (char in mapping or char in glyph_index_by_char)
    )
    if not target_chars:
        raise SystemExit("No translatable Han/punctuation glyphs were found.")
    args.glyph_map.parent.mkdir(parents=True, exist_ok=True)
    args.glyph_map.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="fate-extra-glyphs-") as tmp:
        tmp_path = Path(tmp)
        glyph_list = tmp_path / "glyphs.txt"
        glyph_raw = tmp_path / "glyphs.raw"
        glyph_list.write_text("\n".join(target_chars) + "\n", encoding="utf-8")
        subprocess.run(["swift", str(args.renderer), str(glyph_list), str(glyph_raw)], check=True)
        rendered = glyph_raw.read_bytes()
    rendered_count = struct.unpack_from("<I", rendered, 0)[0]
    if rendered_count != len(target_chars) or len(rendered) != 4 + rendered_count * 256:
        raise ValueError("font renderer returned an invalid glyph bitmap set")
    glyph_bitmaps = {char: rendered[4 + i * 256:4 + (i + 1) * 256] for i, char in enumerate(target_chars)}

    has_paths, texture_entries = load_font_txb(font_path)
    texture_parts = [split_font_page(item) for item in texture_entries]
    texture_headers = [bytearray(header) for header, _data, _tail in texture_parts]
    texture_pixels = [unswizzle_t4(data) for _header, data, _tail in texture_parts]
    texture_tails = [tail for _header, _data, tail in texture_parts]
    while len(texture_pixels) * FONT_PAGE_SIZE < glyph_count:
        texture_headers.append(bytearray(texture_headers[-1]))
        texture_pixels.append(bytearray(WIDTH * HEIGHT))
        texture_tails.append(texture_tails[-1])
    modified_kanzi = bytearray(original_kanzi)
    if new_placeholder_rows:
        struct.pack_into("<I", modified_kanzi, 0, glyph_count)
        modified_kanzi.extend(b"\0" * (6 * len(new_placeholder_rows)))
        for row in new_placeholder_rows:
            record = row["record_offset"]
            modified_kanzi[record:record + 2] = row["sjis"][::-1]
    for target, placeholder in mapping.items():
        index = glyph_index_by_char.get(placeholder)
        if index is None:
            raise ValueError(f"placeholder missing from kanzi.bin: {placeholder!r}")
        row = glyph_rows[index]
        encoded_utf8 = target.encode("utf-8")
        if len(encoded_utf8) > 3:
            raise ValueError(f"only BMP characters can be installed in kanzi.bin: U+{ord(target):04X}")
        record = row["record_offset"]
        modified_kanzi[record + 2:record + 5] = encoded_utf8.ljust(3, b"\0")
        modified_kanzi[record + 5] = 0

    for target in target_chars:
        if target not in glyph_bitmaps:
            continue
        placeholder = mapping.get(target, target)
        index = glyph_index_by_char.get(placeholder)
        if index is None:
            raise ValueError(f"font slot missing from kanzi.bin: {placeholder!r}")
        page, tile = divmod(index, FONT_PAGE_SIZE)
        tile_x, tile_y = (tile % 16) * 16, (tile // 16) * 16
        page_pixels = texture_pixels[page]
        bitmap = glyph_bitmaps[target]
        for y in range(16):
            for x in range(16):
                intensity = bitmap[y * 16 + x]
                page_pixels[(tile_y + y) * WIDTH + tile_x + x] = (intensity * 15 + 127) // 255

    rebuilt_entries = [
        bytes(texture_headers[i]) + swizzle_t4(texture_pixels[i]) + texture_tails[i]
        for i in range(len(texture_headers))
    ]
    rebuilt_font_txb = write_font_txb(rebuilt_entries, has_paths=has_paths)
    args.out_root.mkdir(parents=True, exist_ok=True)
    (args.out_root / "font.txb").write_bytes(rebuilt_font_txb)
    (args.out_root / "kanzi.bin").write_bytes(modified_kanzi)
    args.allocations.parent.mkdir(parents=True, exist_ok=True)
    with args.allocations.open("w", encoding="utf-8", newline="\n") as f:
        for target, placeholder in mapping.items():
            index = glyph_index_by_char[placeholder]
            f.write(json.dumps({
                "character": target,
                "placeholder": placeholder,
                "glyph_index": index,
                "remaining_jp_refs": remaining_jp_refs.get(placeholder, 0),
            }, ensure_ascii=False) + "\n")
    print(f"Mapped {len(mapping)} Chinese characters to CP932 font slots")
    print(f"Patched font.txb and kanzi.bin under {args.out_root}")


if __name__ == "__main__":
    main()
