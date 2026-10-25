#!/usr/bin/env python3
"""Translate the Japanese difficulty screen's message table and baked labels."""

from __future__ import annotations

import argparse
import json
import struct
import subprocess
import tempfile
from pathlib import Path


PACKAGE = Path("pack/modeselect/interface/modeselect")
MODE_TEXT = {
    0: "本作独有的硬派模式。\n\r适合有一定RPG经验的玩家。",
    1: "整体调整得更易上手。\n\r适合不熟悉RPG的玩家。",
    2: "已读取通关存档。",
    3: "跳过部分预选赛，\n\r从选择从者开始游戏。",
}
TEXTURES = {
    "mode_help_00.tex": "请选择难度。",
    "mode_normal_01.tex": "普通模式",
    "mode_easy_01.tex": "新手模式",
}
TITLE = "难度选择"
# The diamond occupies x=1..9. The original first Japanese glyph begins at
# x=13; retaining a nominal 20px icon cell also retains half that glyph.
MODE_HELP_ICON_WIDTH = 10


def unpack_bundle(data: bytes) -> tuple[int, list[tuple[str, bytes]]]:
    count, marker = struct.unpack_from("<HH", data, 0)
    has_paths = marker == 0x8000
    sizes = struct.unpack_from("<" + "I" * count, data, 4)
    pos = (4 + 4 * count + 15) & ~15
    entries = []
    for index, size in enumerate(sizes):
        if has_paths:
            raw_name = data[pos:pos + 64]
            if len(raw_name) != 64:
                raise ValueError("truncated inner texture path")
            name = raw_name.split(b"\0", 1)[0].decode("shift_jis")
            pos += 64
        else:
            name = f"entry_{index:04d}.bin"
        payload = data[pos:pos + size]
        if len(payload) != size:
            raise ValueError(f"truncated inner texture {name}")
        entries.append((name, payload))
        pos += size
    if pos != len(data):
        raise ValueError(f"unexpected trailing data in texture bundle: {len(data) - pos} bytes")
    return has_paths, entries


def pack_bundle(entries: list[tuple[str, bytes]], has_paths: bool) -> bytes:
    out = bytearray(struct.pack("<HH", len(entries), 0x8000 if has_paths else 0))
    for _name, payload in entries:
        out.extend(struct.pack("<I", len(payload)))
    out.extend(b"\0" * ((-len(out)) & 15))
    for name, payload in entries:
        if has_paths:
            encoded = name.encode("shift_jis")
            if len(encoded) > 64:
                raise ValueError(f"inner path too long: {name}")
            out.extend(encoded + b"\0" * (64 - len(encoded)))
        out.extend(payload)
    return bytes(out)


def parse_cct(texture: bytes, pixel_offset: int, data_size: int) -> tuple[int, list[int]]:
    """Read the 32x32 chunk-composition table that follows the palette."""
    palette_offset = pixel_offset + data_size
    cct_offset = palette_offset + 16 + 64
    # The CCT metadata is 20 bytes: two ints, four shorts, then one int.
    if cct_offset + 20 > len(texture):
        raise ValueError("T4 texture has no CCT header")
    chunks_per_line, chunk_lines, count, chunk_size, unique_count, _reserved, _unknown = struct.unpack_from(
        "<IIHHHHI", texture, cct_offset
    )
    if chunk_size != 32:
        raise ValueError(f"unsupported T4 CCT chunk size: {chunk_size}")
    table_offset = cct_offset + 20
    table = list(struct.unpack_from("<" + "h" * count, texture, table_offset))
    if len(table) != count or unique_count * 512 != data_size:
        raise ValueError("inconsistent T4 CCT chunk table")
    if chunks_per_line * chunk_lines != count:
        raise ValueError("CCT dimensions do not match the chunk count")
    return chunk_size, table


def unpack_t4(data: bytes, width: int, padded_height: int, cct: list[int]) -> bytearray:
    """Decode Fate's 4bpp swizzled data, which is stored as CCT-mapped 32x32 tiles."""
    if width % 32 or padded_height % 32:
        raise ValueError(f"unsupported T4 CCT buffer size {width}x{padded_height}")
    tile_columns = width // 32
    tile_rows = padded_height // 32
    if len(cct) != tile_columns * tile_rows or len(data) != len(cct) * 512:
        raise ValueError("T4 pixel data does not match its CCT table")
    output = bytearray(width * padded_height)
    for logical_tile, stored_tile in enumerate(cct):
        if stored_tile == -1:
            continue
        if not 0 <= stored_tile < len(cct):
            raise ValueError(f"invalid CCT tile index: {stored_tile}")
        tile_x = logical_tile % tile_columns
        tile_y = logical_tile // tile_columns
        tile_offset = stored_tile * 512
        for y in range(32):
            row_offset = tile_offset + y * 16
            dst = (tile_y * 32 + y) * width + tile_x * 32
            for byte_index in range(16):
                value = data[row_offset + byte_index]
                output[dst + byte_index * 2] = value & 0x0F
                output[dst + byte_index * 2 + 1] = value >> 4
    return output


def pack_t4(pixels: bytes | bytearray, width: int, padded_height: int, cct: list[int]) -> bytes:
    if len(pixels) != width * padded_height:
        raise ValueError("T4 bitmap does not match its texture buffer")
    if width % 32 or padded_height % 32:
        raise ValueError(f"unsupported T4 CCT buffer size {width}x{padded_height}")
    tile_columns = width // 32
    tile_rows = padded_height // 32
    if len(cct) != tile_columns * tile_rows:
        raise ValueError("T4 bitmap dimensions do not match its CCT table")
    output = bytearray(len(cct) * 512)
    for logical_tile, stored_tile in enumerate(cct):
        if stored_tile == -1:
            continue
        if not 0 <= stored_tile < len(cct):
            raise ValueError(f"invalid CCT tile index: {stored_tile}")
        tile_x = logical_tile % tile_columns
        tile_y = logical_tile // tile_columns
        tile_offset = stored_tile * 512
        for y in range(32):
            row_offset = tile_offset + y * 16
            src = (tile_y * 32 + y) * width + tile_x * 32
            for byte_index in range(16):
                x = src + byte_index * 2
                output[row_offset + byte_index] = pixels[x] | (pixels[x + 1] << 4)
    return bytes(output)


def replace_texture_text(
    texture: bytes,
    glyphs: dict[str, bytes],
    text: str,
    x_offset: int = 0,
    preserve_icon: bool = False,
    title_bitmap: bytes | None = None,
) -> bytes:
    fmt, swizzled = struct.unpack_from("<HH", texture, 0x10)
    width, height, stride = struct.unpack_from("<HHH", texture, 0x14)
    data_size = struct.unpack_from("<I", texture, 0x1C)[0]
    if fmt != 4 or swizzled != 1:
        raise ValueError(f"unexpected texture format: format={fmt}, swizzled={swizzled}")
    padded_height = data_size * 2 // stride
    if stride != width or padded_height < height or data_size * 2 != stride * padded_height:
        raise ValueError("unexpected T4 texture stride/height")
    # Fate/Extra .tex data starts at 0x30. The 16-byte CLUT header follows
    # the pixel payload, then the palette itself. Starting at 0x40 silently
    # overwrites the CLUT header, which makes the game crash when loading TXB.
    pixel_offset = 0x30
    palette_offset = pixel_offset + data_size
    palette_header = texture[palette_offset:palette_offset + 16]
    palette = texture[palette_offset + 16:palette_offset + 80]
    if len(palette_header) != 16:
        raise ValueError("T4 texture has no CLUT header")
    if len(palette) != 64:
        raise ValueError("T4 texture has no 16-color palette")
    _chunk_size, cct = parse_cct(texture, pixel_offset, data_size)
    image = unpack_t4(texture[pixel_offset:pixel_offset + data_size], stride, padded_height, cct)

    replacement = bytearray(stride * padded_height)
    if preserve_icon:
        for y in range(min(16, height)):
            icon_width = min(MODE_HELP_ICON_WIDTH, width)
            replacement[y * stride:y * stride + icon_width] = image[y * stride:y * stride + icon_width]

    if title_bitmap is not None:
        if len(title_bitmap) != width * height:
            raise ValueError("title bitmap dimensions do not match texture")
        source_bitmap = title_bitmap
        x_start, y_start = 0, 0
        text_width = width
        text_height = height
        palette_base = 1
    else:
        source_bitmap = None
        text_width = len(text) * 16
        text_height = 16
        x_start = x_offset if preserve_icon else max(0, (width - text_width) // 2)
        y_start = max(0, (height - 16) // 2)
        palette_base = 3 if preserve_icon else 1

    for glyph_index, char in enumerate(text):
        bitmap = glyphs.get(char)
        if bitmap is None or len(bitmap) != 256:
            raise ValueError(f"missing rendered glyph {char!r}")
        for y in range(16):
            py = y_start + y
            if py >= height:
                continue
            for x in range(16):
                px = x_start + glyph_index * 16 + x
                if px >= width:
                    continue
                intensity = bitmap[y * 16 + x]
                if intensity:
                    if preserve_icon:
                        color_index = palette_base + (intensity * 12 + 127) // 255
                    else:
                        color_index = 1 + (intensity * 14 + 127) // 255
                    replacement[py * stride + px] = min(15, color_index)

    if title_bitmap is not None:
        replacement = bytearray(stride * padded_height)
        for y in range(height):
            for x in range(width):
                intensity = title_bitmap[y * width + x]
                if intensity:
                    replacement[y * stride + x] = min(15, 1 + (intensity * 14 + 127) // 255)

    out = bytearray(texture)
    out[pixel_offset:pixel_offset + data_size] = pack_t4(replacement, stride, padded_height, cct)
    return bytes(out)


def patch_message_table(data: bytes, glyph_map: dict[str, str]) -> tuple[bytes, int]:
    out = bytearray(data)
    pos = 0
    patched = 0
    while pos + 8 <= len(out):
        index, length = struct.unpack_from("<II", out, pos)
        if index not in MODE_TEXT or length > len(out) - pos - 8 or not length:
            break
        translated = "".join(glyph_map.get(ch, ch) for ch in MODE_TEXT[index]).encode("cp932")
        if len(translated) >= length:
            raise ValueError(f"mode-select message {index} no longer fits its {length}-byte slot")
        out[pos + 8:pos + 8 + length] = translated + b"\0" * (length - len(translated))
        patched += 1
        pos = (pos + 8 + length + 3) & ~3
    if patched != len(MODE_TEXT):
        raise ValueError(f"patched {patched} of {len(MODE_TEXT)} mode-select message entries")
    return bytes(out), patched


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract-root", type=Path, default=Path("work/extracted"))
    parser.add_argument("--build-root", type=Path, default=Path("work/build"))
    parser.add_argument("--glyph-map", type=Path, default=Path("work/translation/glyph-map.json"))
    parser.add_argument("--glyph-renderer", type=Path, default=Path("tools/render_font_glyphs.swift"))
    parser.add_argument("--title-renderer", type=Path, default=Path("tools/render_ui_title.swift"))
    args = parser.parse_args()

    source_dir = args.extract_root / "packages" / PACKAGE
    output_dir = args.build_root / "assets" / "packages" / PACKAGE
    output_dir.mkdir(parents=True, exist_ok=True)
    glyph_map = json.loads(args.glyph_map.read_text(encoding="utf-8"))

    message_data, message_count = patch_message_table((source_dir / "modeselect.bin").read_bytes(), glyph_map)
    (output_dir / "modeselect.bin").write_bytes(message_data)

    bundle = (source_dir / "modeselect.txb").read_bytes()
    has_paths, entries = unpack_bundle(bundle)
    tex_entries = dict(entries)
    needed_glyphs = set("".join(TEXTURES.values()))
    with tempfile.TemporaryDirectory(prefix="fate-mode-ui-") as temporary:
        tmp = Path(temporary)
        glyph_list = tmp / "glyphs.txt"
        glyph_raw = tmp / "glyphs.raw"
        glyph_list.write_text("\n".join(sorted(needed_glyphs)) + "\n", encoding="utf-8")
        subprocess.run(["swift", str(args.glyph_renderer), str(glyph_list), str(glyph_raw)], check=True)
        rendered = glyph_raw.read_bytes()
        count = struct.unpack_from("<I", rendered)[0]
        if count != len(needed_glyphs) or len(rendered) != 4 + count * 256:
            raise ValueError("small UI glyph renderer returned invalid data")
        glyphs = {
            char: rendered[4 + index * 256:4 + (index + 1) * 256]
            for index, char in enumerate(sorted(needed_glyphs))
        }

        title_raw = tmp / "title.raw"
        subprocess.run([
            "swift", str(args.title_renderer), TITLE, "192", "64", "Songti SC", "44", str(title_raw)
        ], check=True)
        title_bitmap = title_raw.read_bytes()
        if len(title_bitmap) != 192 * 64:
            raise ValueError("large UI title renderer returned invalid data")

    for name, text in TEXTURES.items():
        if name not in tex_entries:
            raise KeyError(f"mode-select texture missing: {name}")
        tex_entries[name] = replace_texture_text(
            tex_entries[name], glyphs, text,
            x_offset=24 if name == "mode_help_00.tex" else 0,
            preserve_icon=name == "mode_help_00.tex",
        )
    tex_entries["mode_ttl_00.tex"] = replace_texture_text(
        tex_entries["mode_ttl_00.tex"], {}, "", title_bitmap=title_bitmap
    )
    rebuilt = pack_bundle([(name, tex_entries[name]) for name, _ in entries], has_paths)
    (output_dir / "modeselect.txb").write_bytes(rebuilt)
    print(f"Translated {message_count} mode-select messages and 4 baked UI textures.")


if __name__ == "__main__":
    main()
