#!/usr/bin/env python3
"""Add HD replacements for the poem atlas and opening/title/menu UI.

The game stores animated poem captions in their own 14px-cell glyph atlas,
separate from the dialogue and ruby pages. This builder renders that atlas at
8x directly from the final text map, redraws the baked mode-select labels at
8x, and adds uncovered title/opening UI tiles to an existing PPSSPP texture
pack. Existing vector-rendered UI mappings take precedence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageFilter

from build_fate_extra_hd_pack import data_hash, palette_key, tile_records
from fate_extra_texture import Bundle, Texture
from patch_fate_extra_ui import MODE_HELP_ICON_WIDTH


POEM_CELL = 14
POEM_COLUMNS = 18
POEM_PER_PAGE = POEM_COLUMNS * POEM_COLUMNS
MODE_LABELS = {
    "mode_normal_01.tex": "普通模式",
    "mode_easy_01.tex": "新手模式",
    "mode_help_00.tex": "请选择难度。",
}
MODE_TITLE = "难度选择"
OPENING_PACKS = [
    "modeselect/interface/modeselect/modeselect.txb",
    "title/interface/title/0000.txb",
    "advice/interface/advice/0000.txb",
    "beginning/interface/beginning/0000.txb",
    "charsel/interface/charsel/svt_select.txb",
    "003016/interface/nameentry/0000.txb",
]


def read_hashes(path: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    in_hashes = False
    if not path.exists():
        return found
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("["):
            in_hashes = line.lower() == "[hashes]"
        elif in_hashes and "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            found[key.strip().lower()] = value.strip()
    return found


def write_hashes(path: Path, mapping: dict[str, str], algorithm: str) -> None:
    old = read_hashes(path)
    old.update(mapping)
    path.write_text(
        "[options]\nversion = 1\nhash = " + algorithm +
        "\nignoreAddress = true\nignoreMipmap = true\nreduceHash = false\n\n[hashes]\n" +
        "\n".join(f"{k} = {v}" for k, v in sorted(old.items())) + "\n",
        encoding="utf-8",
    )


def poem_rows(data: bytes) -> list[str]:
    if len(data) < 4:
        raise ValueError("short poem.bin")
    count = struct.unpack_from("<I", data)[0]
    end = 4 + count * 6
    if end > len(data) or any(data[end:]):
        raise ValueError("invalid poem.bin length or trailer")
    chars = []
    for i in range(count):
        raw = data[4 + i * 6 + 2: 4 + i * 6 + 5].split(b"\0", 1)[0]
        char = raw.decode("utf-8")
        if len(char) != 1:
            raise ValueError(f"invalid poem glyph row {i}: {char!r}")
        chars.append(char)
    return chars


def render_glyphs(chars: list[str], renderer: Path, tmp: Path, cell: int, size: int,
                  fonts: list[str]) -> list[bytes]:
    unique = list(dict.fromkeys(chars))
    glyph_list = tmp / "glyphs.txt"
    raw_path = tmp / "glyphs.raw"
    glyph_list.write_text("\n".join(unique) + "\n", encoding="utf-8")
    subprocess.run(["swift", str(renderer), str(glyph_list), str(raw_path), str(cell), str(size), *fonts], check=True)
    raw = raw_path.read_bytes()
    if len(raw) != 4 + len(unique) * cell * cell or struct.unpack_from("<I", raw)[0] != len(unique):
        raise ValueError("HD glyph renderer returned an unexpected atlas")
    bitmaps = [raw[4 + i * cell * cell: 4 + (i + 1) * cell * cell] for i in range(len(unique))]
    return [bitmaps[unique.index(char)] for char in chars]


def rgba_from_palette(alpha_image: Image.Image, palette, base: int = 1, top: int = 15) -> Image.Image:
    alpha = alpha_image.convert("L")
    src = alpha.load()
    colors = palette
    out = Image.new("RGBA", alpha.size, (0, 0, 0, 0))
    dst = out.load()
    span = top - base
    for y in range(alpha.height):
        for x in range(alpha.width):
            intensity = src[x, y]
            if not intensity:
                continue
            index = min(top, base + (intensity * span + 127) // 255)
            dst[x, y] = tuple(int(v) for v in colors[index])
    return out


def draw_mode_label(tex: Texture, text: str, scale: int, renderer: Path, tmp: Path) -> Image.Image:
    w, h = tex.width * scale, tex.height * scale
    cell = 16 * scale
    glyphs = render_glyphs(list(text), renderer, tmp, cell, 13 * scale,
                           ["HiraginoSansGB-W6", "PingFangSC-Semibold", "Apple Symbols"])
    alpha = Image.new("L", (w, h), 0)
    x0 = 24 if text == MODE_LABELS["mode_help_00.tex"] else max(0, (tex.width - len(text) * 16) // 2)
    y0 = max(0, (tex.height - 16) // 2)
    for index, raw in enumerate(glyphs):
        bitmap = Image.frombytes("L", (cell, cell), raw)
        alpha.paste(bitmap, (x0 * scale + index * cell, y0 * scale))
    ink = rgba_from_palette(alpha, tex.palette,
                            base=3 if text == MODE_LABELS["mode_help_00.tex"] else 1)
    if text == MODE_LABELS["mode_help_00.tex"]:
        native = tex.image()
        icon = native.crop((0, 0, min(MODE_HELP_ICON_WIDTH, tex.width), min(16, tex.height)))
        icon = icon.resize((icon.width * scale, icon.height * scale), Image.Resampling.NEAREST)
        ink.alpha_composite(icon, (0, 0))
    return ink


def draw_mode_title(tex: Texture, scale: int, renderer: Path, tmp: Path) -> Image.Image:
    raw_path = tmp / "mode-title.raw"
    width, height = tex.width * scale, tex.height * scale
    subprocess.run([
        "swift", str(renderer), MODE_TITLE, str(width), str(height),
        "Songti SC", str(44 * scale), str(raw_path),
    ], check=True)
    alpha_raw = raw_path.read_bytes()
    if len(alpha_raw) != width * height:
        raise ValueError("mode title raster has an unexpected size")
    alpha = Image.frombytes("L", (width, height), alpha_raw)
    return rgba_from_palette(alpha, tex.palette)


def sharpened_upscale(tex: Texture, scale: int) -> Image.Image:
    image = tex.image()
    high = image.resize((tex.width * scale, tex.height * scale), Image.Resampling.LANCZOS)
    # Mild edge restoration counters texture filtering without changing tile
    # content or inventing detail.
    return high.filter(ImageFilter.UnsharpMask(radius=max(1, scale // 2), percent=45, threshold=3))


def community_selection_map(root: Path | None) -> dict[str, Path]:
    if root is None or not (root / "textures.ini").exists():
        return {}
    rows = {}
    for raw in (root / "textures.ini").read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*([0-9a-fA-F]{24})\s*=\s*(.+?)\s*$", raw)
        if not match:
            continue
        relative = match.group(2).strip()
        # Only the Japanese/English-neutral blue selection frame is safe to
        # reuse; text-bearing English/Korean assets are never imported.
        if re.fullmatch(r"New_Game/Selection_[1-4]\.png", relative):
            rows[match.group(1).lower()] = root / relative
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overlay", type=Path, required=True, help="final translated package overlay")
    parser.add_argument("--source-pack", type=Path, required=True, help="original extracted pack directory")
    parser.add_argument("--pack-root", type=Path, required=True, help="existing HD UI pack root")
    parser.add_argument("--community-pack", type=Path, help="optional Fate-Extra-HD checkout, for frame tiles only")
    parser.add_argument("--scale", type=int, default=8, choices=[4, 8])
    parser.add_argument("--renderer", type=Path, default=Path("scripts/pipeline/render_hd_font_glyphs.swift"))
    parser.add_argument("--title-renderer", type=Path, default=Path("scripts/pipeline/render_ui_title.swift"))
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    scale = args.scale
    game = args.pack_root / "NPJH50247"
    image_root = game / "CN_HD"
    image_root.mkdir(parents=True, exist_ok=True)
    output_maps = {algorithm: {} for algorithm in ("xxh64", "quick")}
    old_maps = {algorithm: read_hashes(game / ("textures.ini" if algorithm == "xxh64" else "textures-quick.ini"))
                for algorithm in output_maps}
    for mapping in old_maps.values():
        for key, value in list(mapping.items()):
            if value.startswith(("CN_HD/FontsPoem/", "CN_HD/Opening/")):
                del mapping[key]
    cache: dict[str, str] = {}
    report = {"scale": scale, "poem": [], "mode_select": [], "opening_ui": [], "skipped_existing": 0,
              "community_graphics_reused": [], "uncovered_tiles_added": 0}

    def save_image(image: Image.Image, category: str) -> str:
        image = image.convert("RGBA")
        digest = hashlib.sha256(image.tobytes() + str(image.size).encode()).hexdigest()
        relative = f"CN_HD/{category}/{digest[:24]}.png"
        target = game / relative
        if relative not in cache:
            target.parent.mkdir(parents=True, exist_ok=True)
            image.save(target, optimize=True)
            cache[relative] = digest
        return relative

    def add_keys(tex: Texture, raw: bytes, width: int, height: int, relative: str,
                 *, overwrite: bool = False) -> dict[str, str]:
        keys = {}
        palette = palette_key(tex, width, height)
        for algorithm in output_maps:
            key = f"00000000{palette:08x}{data_hash(raw, algorithm):08x}"
            existing = old_maps[algorithm].get(key)
            if existing and not overwrite:
                report["skipped_existing"] += 1
                continue
            output_maps[algorithm][key] = relative
            keys[algorithm] = key
        return keys

    # The translated poem table and bitmap are used by the animated interlude
    # and by the same scene viewed from character selection.
    poem_root = args.overlay / "poem/interface/poem"
    poem_charsel = args.overlay / "charsel/interface/poem"
    poem_bin_path = poem_root / "poem.bin"
    poem_txb_path = poem_root / "poem_font.txb"
    if not poem_bin_path.exists() or not poem_txb_path.exists():
        raise FileNotFoundError("translated poem.bin/poem_font.txb are missing from overlay")
    glyphs = poem_rows(poem_bin_path.read_bytes())
    if len(glyphs) > 2 * POEM_PER_PAGE:
        raise ValueError(f"poem font atlas capacity exceeded: {len(glyphs)} glyphs")
    poem_bundle = Bundle.parse(poem_txb_path.read_bytes())
    if len(poem_bundle.payloads) != 2:
        raise ValueError("expected the two-page poem font atlas")
    with tempfile.TemporaryDirectory(prefix="fate-poem-hd-") as temporary:
        tmp = Path(temporary)
        cells = render_glyphs(glyphs, args.renderer, tmp, POEM_CELL * scale,
                              11 * scale, ["ToppanBunkyuMinchoPr6N-Regular", "Songti SC", "Apple Symbols"])
        for page, payload in enumerate(poem_bundle.payloads):
            tex = Texture(payload)
            if (tex.width, tex.height) != (256, 256) or tex.format != 4:
                raise ValueError(f"unexpected poem atlas page: {tex.metadata()}")
            high = Image.new("RGBA", (256 * scale, 256 * scale), (255, 255, 255, 0))
            first = page * POEM_PER_PAGE
            stop = min(first + POEM_PER_PAGE, len(glyphs))
            for index in range(first, stop):
                local = index - first
                x = (local % POEM_COLUMNS) * POEM_CELL * scale
                y = (local // POEM_COLUMNS) * POEM_CELL * scale
                alpha = Image.frombytes("L", (POEM_CELL * scale, POEM_CELL * scale), cells[index])
                glyph = Image.new("RGBA", alpha.size, (255, 255, 255, 0))
                glyph.putalpha(alpha)
                high.alpha_composite(glyph, (x, y))
            relative = save_image(high, "FontsPoem")
            keys = add_keys(tex, tex.pixel_data, 256, 256, relative)
            report["poem"].append({"page": page, "glyph_range": [first, stop],
                                   "source": [tex.width, tex.height], "replacement": list(high.size),
                                   "file": relative, "keys": keys})
    # Alias bundle is expected to use the exact same table and atlas. Verify it
    # rather than silently mapping a stale/independent character-select font.
    if poem_charsel.exists():
        alias_bin = poem_charsel / "poem.bin"
        alias_txb = poem_charsel / "poem_font.txb"
        if alias_bin.exists() and alias_txb.exists():
            alias_bundle = Bundle.parse(alias_txb.read_bytes())
            if poem_rows(alias_bin.read_bytes()) != glyphs or alias_bundle.payloads != poem_bundle.payloads:
                raise ValueError("poem/charsel poem font aliases have diverged")

    community = community_selection_map(args.community_pack)
    opening_sources: dict[str, Path] = {}
    for relative in OPENING_PACKS:
        final = args.overlay / relative
        original = args.source_pack / relative
        source = final if final.exists() else original
        if source.exists():
            opening_sources[relative] = source
    if "title/interface/title/0000.txb" not in opening_sources:
        raise FileNotFoundError("source title texture bundle is unavailable")

    for relative_bundle, path in opening_sources.items():
        bundle = Bundle.parse(path.read_bytes())
        bundle_report = {"bundle": relative_bundle, "textures": 0, "tiles": 0, "vector_labels": []}
        for index, (name, payload) in enumerate(zip(bundle.names, bundle.payloads)):
            if len(payload) < 48:
                continue
            tex = Texture(payload)
            if tex.format not in (4, 5) or tex.cct is None or not tex.swizzled:
                continue
            label_image = None
            if relative_bundle.startswith("modeselect/") and name in MODE_LABELS:
                label_image = draw_mode_label(tex, MODE_LABELS[name], scale, args.renderer, Path(tempfile.gettempdir()))
                bundle_report["vector_labels"].append({"texture": name, "text": MODE_LABELS[name]})
            elif relative_bundle.startswith("modeselect/") and name == "mode_ttl_00.tex":
                label_image = draw_mode_title(tex, scale, args.title_renderer, Path(tempfile.gettempdir()))
                bundle_report["vector_labels"].append({"texture": name, "text": MODE_TITLE})
            else:
                label_image = sharpened_upscale(tex, scale)
            if label_image.size != (tex.width * scale, tex.height * scale):
                raise ValueError(f"unexpected HD dimensions for {relative_bundle}::{name}: {label_image.size}")
            for logical, raw, width, height, tile in tile_records(
                    tex, label_image, scale, [(0, 0, tex.width, tex.height)]):
                # For the mode-selection frame, reuse only the community pack's
                # exact quick-hash graphics, never its embedded English text.
                quick_key = f"00000000{palette_key(tex, width, height):08x}{data_hash(raw, 'quick'):08x}"
                source_png = community.get(quick_key) if name == "mode_bg_01.tex" else None
                if source_png and source_png.exists():
                    tile = Image.open(source_png).convert("RGBA").resize(
                        (width * scale, height * scale), Image.Resampling.LANCZOS)
                    report["community_graphics_reused"].append({"bundle": relative_bundle,
                        "texture": name, "tile": logical, "source": source_png.name})
                relative = save_image(tile, "Opening")
                keys = add_keys(tex, raw, width, height, relative,
                                overwrite=relative_bundle.startswith("modeselect/") and
                                name in (set(MODE_LABELS) | {"mode_ttl_00.tex"}))
                if keys:
                    bundle_report["tiles"] += 1
                    report["uncovered_tiles_added"] += 1
                if keys or source_png:
                    bundle_report["textures"] += 1
        report["opening_ui"].append(bundle_report)

    for algorithm, mapping in output_maps.items():
        write_hashes(game / ("textures.ini" if algorithm == "xxh64" else "textures-quick.ini"), mapping, algorithm)
        if algorithm == "xxh64":
            shutil.copy2(game / "textures.ini", game / "textures-xxh64.ini")
    # Remove newly unreferenced images only from the categories this builder
    # owns; preserve the older UI/font outputs in the same pack.
    referenced = set(old_maps["xxh64"].values()) | set(old_maps["quick"].values())
    referenced.update(output_maps["xxh64"].values())
    referenced.update(output_maps["quick"].values())
    for category in ("FontsPoem", "Opening"):
        for path in (image_root / category).glob("*.png"):
            if path.relative_to(game).as_posix() not in referenced:
                path.unlink()
    report["poem_glyph_count"] = len(glyphs)
    report["images_added"] = len(cache)
    report["mappings_added"] = {k: len(v) for k, v in output_maps.items()}
    report["community_frame_tiles"] = len(report["community_graphics_reused"])
    report["runtime_test"] = "pending PPSSPP opening/mode/poem/ruby visual verification"
    manifest_path = args.pack_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest["poem_hd"] = {
        "glyph_count": len(glyphs), "page_count": len(poem_bundle.payloads), "scale": scale,
        "cell_pitch": POEM_CELL, "font_fallback": ["ToppanBunkyuMinchoPr6N-Regular", "Songti SC", "Apple Symbols"],
        "pages": report["poem"], "runtime_test": report["runtime_test"],
    }
    manifest["opening_ui_hd"] = {
        "scale": scale, "bundles": report["opening_ui"],
        "community_frame_tiles": report["community_frame_tiles"],
        "runtime_test": report["runtime_test"],
    }
    manifest["image_files"] = sum(1 for _ in image_root.rglob("*.png"))
    manifest["mappings"] = {
        algorithm: len(read_hashes(game / ("textures.ini" if algorithm == "xxh64" else "textures-quick.ini")))
        for algorithm in output_maps
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"poem_glyph_count": report["poem_glyph_count"],
                      "images_added": report["images_added"],
                      "mappings_added": report["mappings_added"],
                      "community_frame_tiles": report["community_frame_tiles"],
                      "uncovered_tiles_added": report["uncovered_tiles_added"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
