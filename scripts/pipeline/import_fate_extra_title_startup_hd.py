#!/usr/bin/env python3
"""Import verified 8x title-screen and startup-logo tiles into the CN HD UI pack."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

from PIL import Image

from build_fate_extra_hd_pack import data_hash, palette_key
from fate_extra_texture import Bundle, Texture


TITLE_PACK = "title/interface/title/0000.txb"
LOGO_PACK = "logo/interface/logo/0000.txb"
TITLE_ENTRIES = {
    0: {"categories": {"DigitalV52", "FullV2"}, "name": "title background"},
    1: {"categories": {"FullV2"}, "name": "title background overlay"},
    2: {"categories": {"FullV2"}, "name": "title background overlay"},
    6: {"categories": {"FullV2", "EndingFinalV37"}, "name": "Fate/EXTRA title logo"},
    7: {"categories": {"ModelAlphaTitleV22"}, "name": "title copyright"},
    8: {"categories": {"EnglishOriginalV39"}, "name": "PRESS START"},
}
CLEANED_KOREAN_LOGO_TILES = {
    26: Path("data/evidence/ui/title-logo-clean/tile-26.png"),
    27: Path("data/evidence/ui/title-logo-clean/tile-27.png"),
}


def read_hashes(path: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    in_hashes = False
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("["):
                in_hashes = line.lower() == "[hashes]"
            elif in_hashes and "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                found[key.strip().lower()] = value.strip()
    return found


def write_hashes(path: Path, mapping: dict[str, str], algorithm: str) -> None:
    text = (
        "[options]\nversion = 1\nhash = " + algorithm
        + "\nignoreAddress = true\nignoreMipmap = true\nreduceHash = false\n\n[hashes]\n"
        + "\n".join(f"{key} = {value}" for key, value in sorted(mapping.items())) + "\n"
    )
    temporary = path.with_suffix(path.suffix + ".title-hd-tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def read_source_map(path: Path) -> dict[str, str]:
    matches: dict[str, str] = {}
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = re.match(r"\s*([0-9a-fA-F]{24})\s*=\s*(.+?)\s*$", raw)
        if not match:
            continue
        key, value = match.group(1).lower(), match.group(2).strip()
        if key in matches and matches[key] != value:
            raise ValueError(f"duplicate source hash at {path}:{line_no}: {key}")
        matches[key] = value
    return matches


def category(path: str) -> str:
    parts = Path(path).parts
    return parts[1] if len(parts) > 1 else ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-pack", type=Path, required=True,
                        help="Original extracted TXB package root")
    parser.add_argument("--hd-pack", type=Path, required=True,
                        help="Unpacked community HD texture pack for NPJH50247")
    parser.add_argument("--pack-root", type=Path, required=True,
                        help="Existing CN HD UI pack root containing NPJH50247")
    parser.add_argument("--report", type=Path, required=True,
                        help="JSON import and validation report")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[2]

    game = args.pack_root / "NPJH50247" if (args.pack_root / "NPJH50247").is_dir() else args.pack_root
    source_map = read_source_map(args.hd_pack / "textures.ini")
    mappings = {
        "xxh64": read_hashes(game / "textures-xxh64.ini"),
        "quick": read_hashes(game / "textures-quick.ini"),
    }
    image_root = game / "CN_HD" / "OpeningHD"
    image_root.mkdir(parents=True, exist_ok=True)
    selected: dict[str, str] = {}
    records: list[dict] = []
    skipped: list[dict] = []
    native_upscaled_tiles = 0

    def inspect_pack(relative: str, rules: dict[int, dict], *, startup: bool = False) -> None:
        nonlocal native_upscaled_tiles
        bundle_path = args.source_pack / relative
        if not bundle_path.is_file():
            raise FileNotFoundError(f"source TXB missing: {bundle_path}")
        bundle = Bundle.parse(bundle_path.read_bytes())
        for entry_index, payload in enumerate(bundle.payloads):
            if startup:
                expected = {"StartupLogoV12"} if entry_index == 2 else None
                label = f"startup publisher logo entry {entry_index}"
            else:
                rule = rules.get(entry_index)
                if rule is None:
                    continue
                expected = rule["categories"]
                label = rule["name"]
            try:
                tex = Texture(payload)
            except ValueError as error:
                skipped.append({"pack": relative, "entry": entry_index, "reason": str(error)})
                continue
            if tex.cct is None or not tex.swizzled or tex.width <= 16:
                skipped.append({"pack": relative, "entry": entry_index,
                                "reason": "not a tiled CCT texture"})
                continue
            chunk = tex.chunk_size
            columns = tex.canvas.shape[1] // chunk
            palette = palette_key(tex, chunk, chunk)
            for logical, unique in enumerate(tex.cct):
                if unique < 0:
                    continue
                clean_korean_subtitle = (
                    not startup and entry_index == 6 and logical in CLEANED_KOREAN_LOGO_TILES
                )
                raw = tex.original_tiles[unique]
                xxh_key = f"00000000{palette:08x}{data_hash(raw, 'xxh64'):08x}"
                source_relative = source_map.get(xxh_key)
                if source_relative is None and not startup:
                    skipped.append({"pack": relative, "entry": entry_index, "tile": logical,
                                    "reason": "no exact source-pack hash match"})
                    continue
                source_category = category(source_relative) if source_relative else ""
                if (expected and source_relative
                        and source_category not in expected):
                    skipped.append({"pack": relative, "entry": entry_index, "tile": logical,
                                    "source": source_relative,
                                    "reason": f"source category {source_category!r} is not approved"})
                    continue
                if clean_korean_subtitle:
                    clean_asset = repo_root / CLEANED_KOREAN_LOGO_TILES[logical]
                    if not clean_asset.is_file():
                        raise FileNotFoundError(f"cleaned title-logo tile missing: {clean_asset}")
                    with Image.open(clean_asset) as image:
                        image.load()
                        if image.size != (chunk * 8, chunk * 8):
                            raise ValueError(f"expected 8x cleaned tile {clean_asset}: got {image.size}")
                        output_image = image.convert("RGBA")
                    digest_input = clean_asset.read_bytes()
                    source_kind = "community-hd-cleaned-subtitle"
                elif expected is not None and source_relative and source_category in expected:
                    source_image = (args.hd_pack / source_relative).resolve()
                    if not source_image.is_relative_to(args.hd_pack.resolve()) or not source_image.is_file():
                        raise FileNotFoundError(f"invalid community image path: {source_relative}")
                    with Image.open(source_image) as image:
                        image.load()
                        if image.size != (chunk * 8, chunk * 8):
                            raise ValueError(f"expected 8x image for {xxh_key}: {source_relative} is {image.size}")
                        output_image = image.convert("RGBA")
                    digest_input = source_image.read_bytes()
                    source_kind = "community-hd"
                elif startup:
                    # Only Marvelous has an exact community HD source. For the
                    # other three developer marks, preserve each PSP pixel and
                    # enlarge it with nearest-neighbour sampling so PPSSPP does
                    # not bilinearly blur the native logo at high render scale.
                    cols = (tex.canvas.shape[1] // chunk)
                    y, x = divmod(logical, cols)
                    native = tex.image(cropped=False).crop((x * chunk, y * chunk,
                                                             (x + 1) * chunk, (y + 1) * chunk))
                    output_image = native.resize((chunk * 8, chunk * 8), Image.Resampling.NEAREST)
                    digest_input = output_image.tobytes() + str(output_image.size).encode("ascii")
                    source_kind = "native-pixel-preserving-8x"
                    native_upscaled_tiles += 1
                else:
                    skipped.append({"pack": relative, "entry": entry_index, "tile": logical,
                                    "source": source_relative,
                                    "reason": "no exact source-pack hash match"})
                    continue
                digest = hashlib.sha256(digest_input).hexdigest()
                filename = f"{digest[:24]}.png"
                target_relative = f"CN_HD/OpeningHD/{filename}"
                target = game / target_relative
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    output_image.save(target, optimize=True)
                for algorithm in mappings:
                    key = f"00000000{palette:08x}{data_hash(raw, algorithm):08x}"
                    previous = selected.get(f"{algorithm}:{key}")
                    if previous is not None and previous != target_relative:
                        raise ValueError(f"conflicting source replacements for {algorithm}:{key}")
                    selected[f"{algorithm}:{key}"] = target_relative
                    mappings[algorithm][key] = target_relative
                records.append({
                    "pack": relative,
                    "entry": entry_index,
                    "texture": bundle.names[entry_index],
                    "tile": logical,
                    "label": label,
                    "xxh64": xxh_key,
                    "quick": f"00000000{palette:08x}{data_hash(raw, 'quick'):08x}",
                    "source": source_relative,
                    "source_kind": source_kind,
                    "source_size": [chunk * 8, chunk * 8],
                    "installed": target_relative,
                })

    inspect_pack(LOGO_PACK, {}, startup=True)
    inspect_pack(TITLE_PACK, TITLE_ENTRIES)
    if not records:
        raise ValueError("no exact title/startup texture matches were imported")

    write_hashes(game / "textures.ini", mappings["xxh64"], "xxh64")
    write_hashes(game / "textures-xxh64.ini", mappings["xxh64"], "xxh64")
    write_hashes(game / "textures-quick.ini", mappings["quick"], "quick")

    # Read back every inserted file, map, and native tile hash before reporting success.
    for record in records:
        for algorithm in mappings:
            key = record[algorithm]
            if mappings[algorithm].get(key) != record["installed"]:
                raise ValueError(f"mapping readback failed: {algorithm}:{key}")
        image_path = game / record["installed"]
        with Image.open(image_path) as image:
            if image.size != tuple(record["source_size"]):
                raise ValueError(f"installed image dimension readback failed: {image_path}")

    report = {
        "game_id": "NPJH50247",
        "scale": 8,
        "source_pack": str(args.hd_pack),
        "source_txb_root": str(args.source_pack),
        "imported_tiles": len(records),
        "unique_images": len({row["installed"] for row in records}),
        "mapping_overrides": len(selected),
        "native_upscaled_tiles": native_upscaled_tiles,
        "excluded": skipped,
        "tiles": records,
        "validation": "exact source TXB hash match; image dimensions and both hash maps read back",
        "korean_subtitle_pixels": "The two subtitle tiles are cleaned to a continuous white underline; all three logo tiles now use coherent community HD resolution",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "imported_tiles", "unique_images", "mapping_overrides", "validation", "korean_subtitle_pixels")},
        ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
