#!/usr/bin/env python3
"""Build HD PPSSPP replacements for Fate/EXTRA's separate ruby glyph atlases."""
from __future__ import annotations

import argparse
import json
import math
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from build_fate_extra_hd_pack import data_hash, palette_key, sha256_file
from extract_fate_extra import parse_cpk, read_cpk_entry, safe_relpath, unpack_pak
from fate_extra_texture import Bundle, Texture


PITCH = 9
COLUMNS = 14
PER_PAGE = COLUMNS * COLUMNS
SCALE = 8
FONTS = ["HiraginoSans-W6", "HiraginoSansGB-W6", "Apple Symbols"]


def load_preload(cpk: Path) -> tuple[bytes, bytes]:
    _meta, rows = parse_cpk(cpk)
    row = next((r for r in rows if safe_relpath(r.get("DirName", ""), r["FileName"]).as_posix().lower() == "pack/preload.pak"), None)
    if row is None:
        raise ValueError("source CPK has no pack/PRELOAD.pak")
    payload = read_cpk_entry(cpk, row)
    with tempfile.TemporaryDirectory(prefix="fate-ruby-preload-") as temporary:
        records = unpack_pak(payload, Path(temporary))
        wanted = {Path(r["path"]).name.lower(): Path(temporary) / r["path"] for r in records}
        if "ruby.bin" not in wanted or "ruby.txb" not in wanted:
            raise ValueError("PRELOAD.pak lacks ruby.bin or ruby.txb")
        return wanted["ruby.bin"].read_bytes(), wanted["ruby.txb"].read_bytes()


def decode_glyphs(data: bytes) -> list[str]:
    if len(data) < 4:
        raise ValueError("short ruby.bin")
    count = struct.unpack_from("<I", data)[0]
    end = 4 + count * 6
    if end > len(data) or any(data[end:]):
        raise ValueError("invalid ruby.bin size or padding")
    glyphs = []
    for i in range(count):
        label = data[4 + i * 6 + 2: 4 + i * 6 + 5].split(b"\0", 1)[0].decode("utf-8")
        if len(label) != 1:
            raise ValueError(f"invalid ruby glyph label at index {i}: {label!r}")
        glyphs.append(label)
    return glyphs


def render_alpha(glyphs: list[str], renderer: Path, output: Path) -> np.ndarray:
    cell = PITCH * SCALE
    glyph_list = output.with_suffix(".glyphs.txt")
    raw_path = output.with_suffix(".alpha.raw")
    glyph_list.parent.mkdir(parents=True, exist_ok=True)
    glyph_list.write_text("\n".join(glyphs) + "\n", encoding="utf-8")
    subprocess.run(
        ["swift", str(renderer), str(glyph_list), str(raw_path), str(cell), str(8 * SCALE), *FONTS],
        check=True,
    )
    raw = raw_path.read_bytes()
    if len(raw) != 4 + len(glyphs) * cell * cell or struct.unpack_from("<I", raw)[0] != len(glyphs):
        raise ValueError("HD ruby renderer returned an unexpected glyph atlas")
    # render_hd_font_glyphs.swift writes one alpha byte per pixel; the leading
    # uint32 is only the glyph count.
    alpha = np.frombuffer(raw, dtype=np.uint8, offset=4).reshape(len(glyphs), cell, cell).copy()
    empty = [glyphs[i] for i, glyph in enumerate(glyphs) if not glyph.isspace() and not alpha[i].any()]
    if empty:
        raise ValueError(f"empty ruby glyphs: {empty[:20]}")
    raw_path.unlink()
    glyph_list.unlink()
    return alpha


def update_ini(path: Path, mapping: dict[str, str], algorithm: str) -> int:
    text = path.read_text(encoding="utf-8") if path.exists() else "[options]\nversion = 1\nhash = xxh64\nignoreAddress = true\nignoreMipmap = true\nreduceHash = false\n\n[hashes]\n"
    lines = text.splitlines()
    existing = {}
    in_hashes = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            in_hashes = stripped.lower() == "[hashes]"
        elif in_hashes and "=" in stripped:
            key, value = stripped.split("=", 1)
            existing[key.strip()] = value.strip()
    conflicts = {key: (existing[key], value) for key, value in mapping.items() if key in existing and existing[key] != value}
    if conflicts:
        raise ValueError(f"ruby HD cache key collision in {path.name}: {list(conflicts.items())[:5]}")
    merged = dict(existing)
    merged.update(mapping)
    header = "[options]\nversion = 1\nhash = " + algorithm + "\nignoreAddress = true\nignoreMipmap = true\nreduceHash = false\n\n[hashes]\n"
    path.write_text(header + "\n".join(f"{k} = {v}" for k, v in sorted(merged.items())) + "\n", encoding="utf-8")
    return len(mapping)


def build(cpk: Path, pack_root: Path, renderer: Path, report_path: Path) -> dict:
    ruby_bin, ruby_txb = load_preload(cpk)
    glyphs = decode_glyphs(ruby_bin)
    bundle = Bundle.parse(ruby_txb)
    if len(glyphs) > len(bundle.payloads) * PER_PAGE:
        raise ValueError("ruby.bin requires more glyph slots than ruby.txb contains")
    if math.ceil(len(glyphs) / PER_PAGE) != len(bundle.payloads):
        raise ValueError("ruby.bin page count does not match ruby.txb")

    output_root = pack_root / "NPJH50247"
    image_dir = output_root / "CN_HD" / "FontsRuby"
    image_dir.mkdir(parents=True, exist_ok=True)
    all_alpha = render_alpha(glyphs, renderer, report_path.with_suffix(".tmp"))
    page_records = []
    mappings = {"xxh64": {}, "quick": {}}
    previews = report_path.parent / "ruby-hd-previews"
    previews.mkdir(parents=True, exist_ok=True)
    for page_index, (name, payload) in enumerate(zip(bundle.names, bundle.payloads)):
        tex = Texture(payload)
        if tex.format != 4 or not tex.swizzled or tex.width != 128 or tex.height > 136:
            raise ValueError(f"unexpected ruby page {name}: {tex.metadata()}")
        scale = SCALE
        high = Image.new("RGBA", (tex.width * scale, tex.height * scale), (255, 255, 255, 0))
        start = page_index * PER_PAGE
        stop = min(start + PER_PAGE, len(glyphs))
        for glyph_index in range(start, stop):
            local = glyph_index - start
            x, y = local % COLUMNS * PITCH, local // COLUMNS * PITCH
            alpha = Image.fromarray(all_alpha[glyph_index], "L")
            tile = Image.new("RGBA", (PITCH * scale, PITCH * scale), (255, 255, 255, 0))
            tile.putalpha(alpha)
            high.paste(tile, (x * scale, y * scale))
        # All four ruby pages use the same 128x128 CLUT key in PPSSPP. The
        # second page has a logical height of 130 pixels but a 136-row swizzled
        # buffer; using that logical height in palette_key() would be invalid
        # and does not match the runtime cache key. This key was confirmed from
        # PPSSPP's saved native texture dumps for pages 0 and 2, and from the
        # existing page-1 HD mapping.
        palette = palette_key(tex, 128, 128)
        page_keys = {}
        for algorithm in mappings:
            key = f"00000000{palette:08x}{data_hash(tex.pixel_data, algorithm):08x}"
            filename = f"{name.rsplit('.', 1)[0]}-{key[-8:]}.png"
            relative = f"CN_HD/FontsRuby/{filename}"
            target = output_root / relative
            high.save(target, optimize=True)
            mappings[algorithm][key] = relative
            page_keys[algorithm] = key
        preview = previews / f"ruby-page-{page_index:02d}.png"
        high.save(preview, optimize=True)
        page_records.append({
            "page": page_index,
            "source_texture": name,
            "source_dimensions": [tex.width, tex.height],
            "replacement_dimensions": list(high.size),
            "glyph_range": [start, stop],
            "cache_keys": page_keys,
        })

    added = {}
    for algorithm, rows in mappings.items():
        ini = output_root / ("textures.ini" if algorithm == "xxh64" else "textures-quick.ini")
        added[algorithm] = update_ini(ini, rows, algorithm)
        if algorithm == "xxh64":
            shutil.copy2(ini, output_root / "textures-xxh64.ini")
    manifest_path = pack_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest["ruby_hd"] = {
        "source_cpk_sha256": sha256_file(cpk),
        "font": FONTS,
        "scale": SCALE,
        "pitch": PITCH,
        "glyph_count": len(glyphs),
        "page_count": len(bundle.payloads),
        "pages": page_records,
        "runtime_test": "pending PPSSPP screenshot verification",
    }
    manifest["image_files"] = sum(1 for _ in (output_root / "CN_HD").rglob("*.png"))
    manifest["mappings"] = {
        "xxh64": sum(1 for line in (output_root / "textures.ini").read_text().splitlines() if line.strip() and "=" in line and not line.lstrip().startswith("[")),
        "quick": sum(1 for line in (output_root / "textures-quick.ini").read_text().splitlines() if line.strip() and "=" in line and not line.lstrip().startswith("[")),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {"glyph_count": len(glyphs), "page_count": len(bundle.payloads), "scale": SCALE, "font": FONTS, "replacement_mappings_added": added, "pages": page_records, "preview_dir": str(previews)}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-cpk", type=Path, required=True, help="final Chinese data.cpk containing expanded ruby.bin/ruby.txb")
    parser.add_argument("--pack-root", type=Path, required=True, help="texture pack root containing NPJH50247/")
    parser.add_argument("--renderer", type=Path, default=Path("scripts/pipeline/render_hd_font_glyphs.swift"))
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.source_cpk, args.pack_root, args.renderer, args.report), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
