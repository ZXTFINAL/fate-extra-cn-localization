#!/usr/bin/env python3
"""Replace declared image-text regions while retaining TEX palette and CCT reuse.

Configuration is reviewable JSON: each entry has file/index and text blocks.
Only listed files are emitted. No ISO or CPK is changed by this tool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from fate_extra_texture import Bundle, Texture

FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"


def text_bitmap(text: str, width: int, height: int, size: int, color: tuple[int, ...],
                align: str = "left", spacing: int = 3, font_path: str = FONT,
                font_index: int = 2) -> Image.Image:
    scale = 4
    im = Image.new("RGBA", (width * scale, height * scale))
    draw = ImageDraw.Draw(im)
    font = ImageFont.truetype(font_path, size * scale, index=font_index)
    y = 0
    for line in text.split("\n"):
        measured = draw.textlength(line, font=font)
        if measured > width * scale + 0.5:
            raise ValueError(f"text wider than declared region: {line!r}, {measured / scale:g}>{width}")
        x = 0 if align == "left" else (width * scale - measured) / 2 if align == "center" else width * scale - measured
        draw.text((round(x), y), line, font=font, fill=color, anchor="lt")
        y += (size + spacing) * scale
    if y - spacing * scale > height * scale:
        raise ValueError("text exceeds declared region height")
    return im.resize((width, height), Image.Resampling.LANCZOS)


def palette_indices(image: Image.Image, palette: np.ndarray) -> np.ndarray:
    """Match RGBA in premultiplied space; palette bytes stay exactly original."""
    rgba = np.asarray(image, dtype=np.float32).reshape(-1, 4)
    p = palette.astype(np.float32).copy(); p[:, :3] *= p[:, 3:4] / 255
    rgba[:, :3] *= rgba[:, 3:4] / 255
    result = np.empty(len(rgba), dtype=np.uint8)
    # Bound peak memory for full-screen T8 textures.
    for start in range(0, len(rgba), 4096):
        distance = ((rgba[start:start + 4096, None, :] - p[None, :, :]) ** 2).sum(axis=2)
        result[start:start + 4096] = distance.argmin(axis=1)
    return result.reshape(image.height, image.width)


def apply_blocks(tex: Texture, blocks: list[dict]) -> tuple[bytes, Image.Image]:
    image = tex.image()
    original = image.copy()
    regions = []
    for block in blocks:
        x, y, width, height = map(int, block["box"])
        if min(x, y, width, height) < 0 or x + width > image.width or y + height > image.height:
            raise ValueError(f"region out of image: {block['box']}")
        background = block.get("background", [0, 0, 0, 255])
        if background == "row_median":
            # Restore a simple UI bar using its background-coloured pixels.
            data = np.asarray(original.crop((x, y, x + width, y + height))).copy()
            source = data[:, :, :3].astype(np.int16)
            # Ignore bright text and red emphasis; preserve the blue background.
            keep = (source.max(axis=2) < 155) & (source[:, :, 0] < source[:, :, 2] + 20)
            for row in range(height):
                good = data[row, keep[row]]
                fill = np.median(good, axis=0).astype(np.uint8) if len(good) else np.median(data[row], axis=0).astype(np.uint8)
                data[row] = fill
            bg = Image.fromarray(data, "RGBA")
        elif isinstance(background, dict) and "clear_rgb" in background:
            data = np.asarray(original.crop((x, y, x + width, y + height))).copy()
            color = np.asarray(background["clear_rgb"], dtype=np.int16)
            mask = np.max(np.abs(data[:, :, :3].astype(np.int16) - color), axis=2) <= background.get("tolerance", 0)
            data[mask] = [0, 0, 0, 0]
            bg = Image.fromarray(data, "RGBA")
        elif isinstance(background, dict) and "copy_box" in background:
            bx, by, bw, bh = map(int, background["copy_box"])
            bg = original.crop((bx, by, bx + bw, by + bh)).resize((width, height), Image.Resampling.NEAREST)
        elif background is None:
            bg = image.crop((x, y, x + width, y + height))
        else:
            bg = Image.new("RGBA", (width, height), tuple(background))
        if block.get("text"):
            color = block.get("color", [255, 255, 255, 255])
            if color == "palette_ink":
                if tex.palette is None:
                    color = [255, 255, 255, 255]
                else:
                    candidates = tex.palette[tex.palette[:, 3] >= 240]
                    if not len(candidates):
                        candidates = tex.palette[tex.palette[:, 3] == tex.palette[:, 3].max()]
                    color = candidates[candidates[:, :3].astype(np.int32).sum(axis=1).argmax()].tolist()
            bitmap = text_bitmap(block["text"], width, height, block.get("size", 14),
                                 tuple(color),
                                 block.get("align", "left"), block.get("spacing", 3),
                                 block.get("font", FONT), block.get("font_index", 2))
            bg = Image.alpha_composite(bg, bitmap)
        image.paste(bg, (x, y))
        regions.append((x, y, width, height))
    pixels = tex.canvas.copy()
    for x, y, width, height in regions:
        im = image.crop((x, y, x + width, y + height))
        values = np.asarray(im) if tex.format == 3 else palette_indices(im, tex.palette)
        pixels[y:y + height, x:x + width] = values
    encoded = tex.encode(pixels)
    check = Texture(encoded)
    if not np.array_equal(check.canvas, pixels):
        raise ValueError("encoded image differs from intended palette indices")
    if check.width != tex.width or check.height != tex.height:
        raise ValueError("TEX dimensions changed")
    if tex.palette is not None and not np.array_equal(check.palette, tex.palette):
        raise ValueError("TEX palette changed")
    return encoded, check.image()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--source", type=Path, default=Path("work/extracted/packages/pack"))
    parser.add_argument("--out", type=Path, default=Path("work/build/localization-v15/assets/packages/pack"))
    parser.add_argument("--previews", type=Path, default=Path("work/research/ui-localization-audit/translated"))
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf8"))
    grouped: dict[str, list[dict]] = {}
    for entry in config["entries"]:
        grouped.setdefault(entry["file"], []).append(entry)
    report = []
    for file, entries in grouped.items():
        source = args.source / file; bundle = Bundle.parse(source.read_bytes())
        payloads = list(bundle.payloads)
        for entry in entries:
            i = entry["index"]; tex = Texture(payloads[i])
            if tex.encode() != payloads[i]:
                raise ValueError(f"unmodified roundtrip mismatch: {file}#{i}")
            try:
                payloads[i], preview = apply_blocks(tex, entry["blocks"])
            except Exception as e:
                raise ValueError(f"{file}#{i} ({bundle.names[i]}): {e}") from e
            path = args.previews / file / f"{i:03d}-{Path(bundle.names[i]).stem}.png"
            path.parent.mkdir(parents=True, exist_ok=True); preview.save(path)
            report.append({"file": file, "index": i, "name": bundle.names[i], "preview": str(path),
                           "source_size": len(tex.source), "output_size": len(payloads[i]),
                           "source_cct_unique": getattr(tex, "cct_unique", None),
                           "output_cct_unique": getattr(Texture(payloads[i]), "cct_unique", None),
                           "source_sha256": hashlib.sha256(tex.source).hexdigest(),
                           "output_sha256": hashlib.sha256(payloads[i]).hexdigest()})
        output = args.out / file; output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(bundle.rebuild(payloads))
    copied = []
    for copy in config.get("copies", []):
        source = args.source / copy["source"]
        output = args.out / copy["source"]
        for target in copy["targets"]:
            if (args.source / target).read_bytes() != source.read_bytes():
                raise ValueError(f"copy source alias differs: {target}")
            path = args.out / target; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(output.read_bytes()); copied.append(target)
    args.previews.mkdir(parents=True, exist_ok=True)
    (args.previews / "patch-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"bundles": len(grouped), "copied_alias_bundles": len(copied), "textures": len(report), "output": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
