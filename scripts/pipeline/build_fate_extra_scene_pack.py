#!/usr/bin/env python3
"""Build a scene-only PPSSPP texture pack from an installed NPJH50247 pack.

Only non-language scene/model/effect groups are copied. UI, dialogue fonts,
tutorial screenshots, Korean text, and title/menu lettering are excluded.
The source keys are the Japanese release's xxh64 keys.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


INCLUDE = {
    "Effects",
    "Textures_Arena",
    "Textures_Character",
    "Textures_Enemy",
    "Textures_Location",
    "Tiled_BG",
    "Tiled_Chara",
    "Tiled_Effects",
}
EXCLUDE_TILED_BG = {
    "Title",
    "NewGame_1",
    "NewGame_2",
    "GAMEOVER",
    "Result",
    "Interlude_1",
    "SpiritualHacking",
    "ChapterStart",
    "Ending_1",
    "Ending_2",
    "Phone",
}


def parse_ini(path: Path) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    in_hashes = False
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line.startswith("["):
            in_hashes = line.lower() == "[hashes]"
            continue
        if not in_hashes:
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{24})\s*=\s*(\S+)", line)
        if match:
            out.append((match.group(1).lower(), match.group(2)))
    return out


def build(source: Path, output: Path) -> dict:
    source = source.resolve()
    output = output.resolve()
    ini = source / "textures.ini"
    if not ini.is_file():
        raise FileNotFoundError(f"source textures.ini not found: {ini}")

    selected: list[tuple[str, str, Path]] = []
    for key, original_path in parse_ini(ini):
        rel = Path(original_path)
        if not rel.parts or rel.parts[0] not in INCLUDE:
            continue
        if rel.parts[0] == "Tiled_BG" and len(rel.parts) > 1 and rel.parts[1] in EXCLUDE_TILED_BG:
            continue
        original = (source / rel).resolve()
        if not original.is_relative_to(source) or not original.is_file():
            raise FileNotFoundError(f"mapped source image missing or unsafe: {original_path}")
        selected.append((key, original_path, original))

    # Reject duplicate keys that point at different source images.
    by_key: dict[str, tuple[str, str, Path]] = {}
    for row in selected:
        key = row[0]
        if key in by_key and by_key[key][2].read_bytes() != row[2].read_bytes():
            raise ValueError(f"conflicting scene source mappings for {key}")
        by_key.setdefault(key, row)

    game = output / "NPJH50247"
    scene_dir = game / "SceneHD"
    scene_dir.mkdir(parents=True, exist_ok=True)
    hashes: list[str] = []
    copied: dict[str, str] = {}
    categories: dict[str, int] = {}
    total_bytes = 0
    for key, original_path, original in sorted(by_key.values()):
        suffix = original.suffix.lower()
        name = hashlib.sha256(original_path.encode("utf-8")).hexdigest()[:20] + suffix
        relative = f"SceneHD/{name}"
        destination = game / relative
        if name not in copied:
            shutil.copy2(original, destination)
            copied[name] = original_path
            total_bytes += destination.stat().st_size
        hashes.append(f"{key} = {relative}")
        category = Path(original_path).parts[0]
        categories[category] = categories.get(category, 0) + 1

    config = (
        "[options]\n"
        "version = 1\n"
        "hash = xxh64\n"
        "ignoreAddress = true\n"
        "ignoreMipmap = true\n"
        "reduceHash = false\n\n"
        "[hashes]\n"
        + "\n".join(hashes)
        + "\n"
    )
    (game / "textures.ini").write_text(config, encoding="utf-8")
    report = {
        "game_id": "NPJH50247",
        "hash": "xxh64",
        "source": str(source),
        "mapping_count": len(hashes),
        "image_count": len(copied),
        "image_bytes": total_bytes,
        "included_categories": categories,
        "excluded_categories": ["UI", "UI_Battle", "Fonts", "Tutorials", "Icons", "NewGame", "Fate-Extra-HD"],
        "excluded_tiled_background_groups": sorted(EXCLUDE_TILED_BG),
        "runtime_test": "not run",
    }
    (output / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, required=True, help="NPJH50247 folder with installed textures.ini and referenced files")
    ap.add_argument("--out", type=Path, required=True, help="New output folder for the clean scene pack")
    args = ap.parse_args()
    print(json.dumps(build(args.source, args.out), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
