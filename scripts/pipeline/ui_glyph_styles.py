"""Style-specific raster glyph profiles for baked UI textures.

The generated atlas is a small bitmap font library for UI art, not a game
runtime font. Each profile keeps the source screen's style, while Han glyphs
use the source Japanese face where it contains the character. Only missing
characters use the weight-matched Chinese fallback. Production text is drawn
from vector outlines as a run, never enlarged from cropped atlas cells.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

CELL = 64
FONT_SIZE = 54
FALLBACK_GOTHIC = "/System/Library/Fonts/Hiragino Sans GB.ttc"
FALLBACK_GOTHIC_INDEX = 2  # W6, matching the compact source labels.
FALLBACK_MINCHO = "/System/Library/Fonts/Supplemental/Songti.ttc"
FALLBACK_MINCHO_INDEX = 6  # Songti SC Regular.
FALLBACK_MINCHO_BOLD_INDEX = 0  # Songti SC Black, matching heavy display Mincho.
PROFILES = {
    "ui_compact": {
        # Keep the Japanese UI's compact sans profile. Han glyphs use the
        # matching light Chinese face so shared Kanji do not mix typefaces.
        "font": "/System/Library/Fonts/ヒラギノ角ゴシック W5.ttc",
        "font_index": 0,
        "fallback_font": FALLBACK_GOTHIC,
        "fallback_index": FALLBACK_GOTHIC_INDEX,
        "effect": None,
    },
    "ui_mincho": {
        "font": "/System/Library/Fonts/ヒラギノ明朝 ProN.ttc",
        "font_index": 0,
        "fallback_font": FALLBACK_MINCHO,
        "fallback_index": FALLBACK_MINCHO_INDEX,
        "effect": None,
    },
    "matrix_tech": {
        "font": "/System/Library/Fonts/ヒラギノ明朝 ProN.ttc",
        "font_index": 2,
        "fallback_font": FALLBACK_MINCHO,
        "fallback_index": FALLBACK_MINCHO_BOLD_INDEX,
        "effect": None,
    },
    "display_mincho": {
        "font": "/System/Library/Fonts/ヒラギノ明朝 ProN.ttc",
        "font_index": 2,
        "fallback_font": FALLBACK_MINCHO,
        "fallback_index": FALLBACK_MINCHO_BOLD_INDEX,
        "effect": None,
    },
    "neon_mincho": {
        "font": "/System/Library/Fonts/ヒラギノ明朝 ProN.ttc",
        "font_index": 0,
        "fallback_font": FALLBACK_MINCHO,
        "fallback_index": FALLBACK_MINCHO_INDEX,
        "effect": {"color": [32, 225, 255, 190], "radius": 1.15, "spread": 1},
    },
    "neon_tech": {
        "font": "/System/Library/Fonts/ヒラギノ角ゴシック W5.ttc",
        "font_index": 0,
        "fallback_font": FALLBACK_GOTHIC,
        "fallback_index": FALLBACK_GOTHIC_INDEX,
        "effect": {"color": [30, 188, 255, 180], "radius": 1.0, "spread": 1},
    },
    "neon_magenta": {
        "font": "/System/Library/Fonts/ヒラギノ明朝 ProN.ttc",
        "font_index": 0,
        "fallback_font": FALLBACK_MINCHO,
        "fallback_index": FALLBACK_MINCHO_INDEX,
        "effect": {"color": [247, 76, 205, 180], "radius": 0.9, "spread": 1},
    },
    "neon_rank": {
        # Matrix skill grades use a pale yellow-green ink, distinct from the
        # magenta skill names in the original textures.
        "font": "/System/Library/Fonts/ヒラギノ明朝 ProN.ttc",
        "font_index": 0,
        "fallback_font": FALLBACK_MINCHO,
        "fallback_index": FALLBACK_MINCHO_INDEX,
        "effect": {"color": [237, 255, 181, 170], "radius": 0.8, "spread": 1},
    },
    "outlined_compact": {
        "font": "/System/Library/Fonts/ヒラギノ角ゴシック W5.ttc",
        "font_index": 0,
        "fallback_font": FALLBACK_GOTHIC,
        "fallback_index": FALLBACK_GOTHIC_INDEX,
        "effect": None,
        "stroke": {"color": [4, 8, 18, 230], "width": 0.85},
    },
    "outlined_mincho": {
        "font": "/System/Library/Fonts/ヒラギノ明朝 ProN.ttc",
        "font_index": 0,
        "fallback_font": FALLBACK_MINCHO,
        "fallback_index": FALLBACK_MINCHO_INDEX,
        "effect": None,
        "stroke": {"color": [4, 8, 18, 230], "width": 0.85},
    },
}

# These profiles are component-specific, not selected by language.
PROFILES["ui_compact"]["font"] = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
PROFILES["helper_gothic"] = dict(PROFILES["ui_compact"])
PROFILES["class_gothic"] = {
    "font": "/System/Library/Fonts/Supplemental/Arial Bold Italic.ttf",
    "font_index": 0,
    "fallback_font": FALLBACK_GOTHIC,
    "fallback_index": 2,
    "effect": {"color": [60, 200, 230, 100], "radius": 0.4},
}
# Tight source-like halos. Broad blur washes out small counters.
for _name in ("neon_mincho", "neon_magenta", "neon_rank"):
    PROFILES[_name]["font_index"] = 2
    PROFILES[_name]["fallback_index"] = 1
for _name in ("neon_mincho", "neon_tech", "neon_magenta", "neon_rank"):
    PROFILES[_name]["effect"]["radius"] = 0.3
    PROFILES[_name]["effect"]["color"][3] = 95


def glyph_characters(config: dict) -> dict[str, set[str]]:
    result = {name: set() for name in PROFILES}
    for entry in config.get("entries", []):
        for block in entry.get("blocks", []):
            text = block.get("text")
            style = block.get("style")
            if not text or not style:
                text = None
            elif style not in result:
                raise ValueError(f"unknown UI glyph style: {style}")
            elif text:
                result[style].update(char for char in text if not char.isspace())
            for segment in block.get("segments", []):
                segment_text = segment.get("text", "")
                segment_style = segment.get("style", style)
                if not segment_text:
                    continue
                if segment_style not in result:
                    raise ValueError(f"unknown UI glyph style: {segment_style}")
                result[segment_style].update(char for char in segment_text if not char.isspace())
    return {name: chars for name, chars in result.items() if chars}


def is_han(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x20000 <= codepoint <= 0x3134F
    )


def build_atlas(config: dict, output_png: Path, output_json: Path) -> dict:
    chars_by_style = glyph_characters(config)
    columns = 16
    rows = sum((len(chars) + columns - 1) // columns for chars in chars_by_style.values())
    if not rows:
        raise ValueError("no non-ASCII UI glyphs were assigned to a style profile")
    atlas = Image.new("L", (columns * CELL, rows * CELL), 0)
    records: dict[str, dict] = {}
    row_offset = 0
    for style, chars in chars_by_style.items():
        profile = PROFILES[style]
        font = ImageFont.truetype(profile["font"], FONT_SIZE, index=profile["font_index"])
        fallback = ImageFont.truetype(profile["fallback_font"], FONT_SIZE,
                                       index=profile["fallback_index"])
        missing = font.getmask(chr(0x10FFFF))
        records[style] = {}
        for number, char in enumerate(sorted(chars)):
            col = number % columns
            row = row_offset + number // columns
            tile_x, tile_y = col * CELL, row * CELL
            mask = Image.new("L", (CELL * 2, CELL * 2), 0)
            draw = ImageDraw.Draw(mask)
            # Center each font's own ink bounds in its cell. Per-glyph ink
            # aspect and advance are kept separately for accurate UI spacing.
            glyph_font = font
            # Fall back only when the source face lacks this glyph.
            glyph_fallback = False
            glyph_fallback = glyph_fallback or (
                font.getmask(char).size == missing.size
                and bytes(font.getmask(char)) == bytes(missing)
            )
            if glyph_fallback:
                glyph_font = fallback
            bbox = draw.textbbox((0, 0), char, font=glyph_font)
            bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
            px = CELL - (bbox[0] + bw / 2)
            py = CELL - (bbox[1] + bh / 2)
            draw.text((round(px), round(py)), char, font=glyph_font, fill=255)
            mask = mask.resize((CELL, CELL), Image.Resampling.LANCZOS)
            ink = mask.getbbox()
            atlas.paste(mask, (tile_x, tile_y))
            # Keep the crop centred for compact atlas storage, but retain the
            # glyph's real bearings and baseline. The renderer uses these for
            # Latin letters so lowercase characters and descenders are not
            # stretched to the full CJK line height.
            baseline_bbox = glyph_font.getbbox(char, anchor="ls")
            ascent, descent = glyph_font.getmetrics()
            ink_left = (baseline_bbox[0] + 2 * ink[0] - round(px))
            ink_top = (baseline_bbox[1] + 2 * ink[1] - round(py))
            records[style][char] = {
                "cell": [tile_x, tile_y, CELL, CELL],
                "ink": list(ink) if ink else [0, 0, CELL, CELL],
                "aspect": round((bw / max(bh, 1)), 6),
                "ink_aspect": round(((ink[2] - ink[0]) / max(1, ink[3] - ink[1])), 6),
                "advance_em": round(glyph_font.getlength(char) / FONT_SIZE, 6),
                "ink_width_em": round((2 * (ink[2] - ink[0])) / FONT_SIZE, 6),
                "ink_height_em": round((2 * (ink[3] - ink[1])) / FONT_SIZE, 6),
                "ink_left_em": round(ink_left / FONT_SIZE, 6),
                "ink_top_em": round(ink_top / FONT_SIZE, 6),
                "ascent_em": round(ascent / FONT_SIZE, 6),
                "descent_em": round(descent / FONT_SIZE, 6),
                "fallback_face": bool(glyph_fallback),
                "effect": profile.get("effect"),
                "stroke": profile.get("stroke"),
            }
        row_offset += (len(chars) + columns - 1) // columns
    output_png.parent.mkdir(parents=True, exist_ok=True)
    atlas.save(output_png, optimize=True)
    metadata = {
        "format": "grayscale-alpha-glyph-cells",
        "production_renderer": "vector-runs-shared-baseline-v2",
        "cell_size": CELL,
        "font_raster_size": FONT_SIZE,
        "profiles": {
            style: {
                "font_source": PROFILES[style]["font"],
                "font_index": PROFILES[style]["font_index"],
                "font_ascent_em": round(_face(PROFILES[style]["font"], PROFILES[style]["font_index"], FONT_SIZE).getmetrics()[0] / FONT_SIZE, 6),
                "font_descent_em": round(_face(PROFILES[style]["font"], PROFILES[style]["font_index"], FONT_SIZE).getmetrics()[1] / FONT_SIZE, 6),
                "fallback_source": PROFILES[style]["fallback_font"],
                "fallback_index": PROFILES[style]["fallback_index"],
                "stroke": PROFILES[style].get("stroke"),
                "effect": PROFILES[style].get("effect"),
                "character_count": len(chars),
                "glyphs": records[style],
            }
            for style, chars in chars_by_style.items()
        },
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"styles": len(records), "glyphs": sum(map(len, records.values())), "png": str(output_png), "metadata": str(output_json)}


def load_atlas(png_path: Path, metadata_path: Path) -> tuple[Image.Image, dict]:
    return Image.open(png_path).convert("L"), json.loads(metadata_path.read_text(encoding="utf-8"))


def _font(style: str, size: int, char: str):
    """Use real font coverage; common Han are not forced into a fallback."""
    from functools import lru_cache
    return _selected_font(style, size, char)


from functools import lru_cache


@lru_cache(maxsize=512)
def _face(path: str, index: int, size: int):
    return ImageFont.truetype(path, size, index=index)


@lru_cache(maxsize=8192)
def _selected_font(style: str, size: int, char: str):
    profile = PROFILES[style]
    face = _face(profile["font"], profile["font_index"], size)
    mask = face.getmask(char)
    missing = face.getmask(chr(0x10FFFF))
    if not char.isspace() and mask.size == missing.size and bytes(mask) == bytes(missing):
        face = _face(profile["fallback_font"], profile["fallback_index"], size)
        mask = face.getmask(char)
        missing = face.getmask(chr(0x10FFFF))
        if mask.size == missing.size and bytes(mask) == bytes(missing):
            raise ValueError(f"missing {char!r} in UI profile {style}")
    return face


def _line_bitmap(segments, width, height, size, color, align, default_style,
                 width_scale, output_scale):
    # Supersampling is performed once. HD outputs keep their vector resolution.
    raster = max(4, output_scale)
    pad = 4 * raster
    parsed = []
    x = 0.0
    top, bottom, left, right = 0.0, 0.0, 0.0, 0.0
    for segment in segments:
        style = segment.get("style", default_style)
        if style not in PROFILES:
            raise ValueError(f"unknown UI profile {style}")
        for char in segment.get("text", ""):
            font = _font(style, size * raster, char)
            bbox = font.getbbox(char, anchor="ls")
            if not char.isspace():
                left = min(left, x + bbox[0])
                right = max(right, x + bbox[2])
                top, bottom = min(top, bbox[1]), max(bottom, bbox[3])
            parsed.append((char, x, font, style, tuple(segment.get("color", color))))
            x += font.getlength(char)
    natural_width = max(x, right) - left
    # Use the component's reference baseline, independent of the particular
    # letters in this sentence. Otherwise identical CCT suffix tiles can get
    # different HD baselines when only the first word changes.
    reference = "H" if default_style == "class_gothic" else "国"
    reference_font = _font(default_style, size * raster, reference)
    top = reference_font.getbbox(reference, anchor="ls")[1]
    natural_height = size * raster
    # One scale for the entire line preserves bearings, relative letter sizes,
    # counters and a shared baseline (including Latin descenders).
    fit_y = min(1.0, size * raster / max(1, natural_height))
    target_w = natural_width * width_scale
    if target_w > width * raster + 0.5:
        raise ValueError(f"text wider than declared region: {target_w / raster:g}>{width}")
    canvas = Image.new("RGBA", (max(1, round(natural_width) + 2 * pad),
                                 max(1, round(natural_height) + 2 * pad)))
    for char, pen, font, style, ink in parsed:
        profile = PROFILES[style]
        mask = Image.new("L", canvas.size)
        ImageDraw.Draw(mask).text((pad + pen - left, pad - top), char,
                                  font=font, fill=255, anchor="ls")
        effect = profile.get("effect")
        if effect:
            glow = mask.filter(ImageFilter.GaussianBlur(effect["radius"] * raster))
            layer = Image.new("RGBA", canvas.size, tuple(effect["color"]))
            layer.putalpha(ImageChops_multiply(glow, effect["color"][3]))
            canvas = Image.alpha_composite(canvas, layer)
        stroke = profile.get("stroke")
        if stroke:
            radius = round(stroke["width"] * raster)
            outline = mask.filter(ImageFilter.MaxFilter(2 * radius + 1))
            layer = Image.new("RGBA", canvas.size, tuple(stroke["color"]))
            layer.putalpha(ImageChops_multiply(outline, stroke["color"][3]))
            canvas = Image.alpha_composite(canvas, layer)
        layer = Image.new("RGBA", canvas.size, ink)
        layer.putalpha(ImageChops_multiply(mask, ink[3]))
        canvas = Image.alpha_composite(canvas, layer)
    scaled = canvas.resize((max(1, round(canvas.width * width_scale)),
                            max(1, round(canvas.height * fit_y))), Image.Resampling.LANCZOS)
    used_width = natural_width * width_scale
    pen_x = 0 if align == "left" else (width * raster - used_width) / 2 if align == "center" else width * raster - used_width
    output = Image.new("RGBA", (width * raster, height * raster))
    output.alpha_composite(scaled, (round(pen_x - pad * width_scale), round(-pad * fit_y)))
    if output_scale != raster:
        output = output.resize((width * output_scale, height * output_scale), Image.Resampling.LANCZOS)
    return output


def style_text_bitmap(text: str, width: int, height: int, size: int,
                      color: tuple[int, ...], align: str, spacing: int,
                      style: str, atlas: Image.Image, metadata: dict,
                      fallback_font: str, fallback_index: int = 2,
                      width_scale: float = 1.0, output_scale: int = 1) -> Image.Image:
    lines = text.split("\n")
    if len(lines) * size + (len(lines) - 1) * spacing > height:
        raise ValueError("text exceeds declared region height")
    output = Image.new("RGBA", (width * output_scale, height * output_scale))
    for n, line in enumerate(lines):
        bitmap = _line_bitmap([{"text": line}], width, size, size, color, align,
                              style, width_scale, output_scale)
        output.alpha_composite(bitmap, (0, n * (size + spacing) * output_scale))
    return output


def style_rich_text_bitmap(segments: list[dict], width: int, height: int, size: int,
                           color: tuple[int, ...], align: str, spacing: int,
                           default_style: str, atlas: Image.Image, metadata: dict,
                           fallback_font: str, fallback_index: int = 2,
                           width_scale: float = 1.0, output_scale: int = 1) -> Image.Image:
    return _line_bitmap(segments, width, height, size, color, align, default_style,
                        width_scale, output_scale)


def ImageChops_multiply(mask: Image.Image, opacity: int) -> Image.Image:
    return mask.point(lambda value: value * opacity // 255)
