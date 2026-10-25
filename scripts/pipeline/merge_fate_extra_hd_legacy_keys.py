#!/usr/bin/env python3
"""Preserve legacy PPSSPP cache-key aliases without replacing current HD maps."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath

GAME = "NPJH50247"


def read_mapping(text: str) -> dict[str, str]:
    result = {}
    in_hashes = False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            in_hashes = line.lower() == "[hashes]"
        elif in_hashes and "=" in line and not line.startswith("#"):
            key, value = (part.strip() for part in line.split("=", 1))
            relative = PurePosixPath(value)
            if not re.fullmatch(r"[0-9a-fA-F]{24}", key):
                raise ValueError(f"invalid texture key: {key}")
            if relative.is_absolute() or ".." in relative.parts or not value.startswith("CN_HD/"):
                raise ValueError(f"invalid CN texture path: {value}")
            if key.lower() in result and result[key.lower()] != value:
                raise ValueError(f"duplicate texture key: {key}")
            result[key.lower()] = value
    return result


def write_mapping(path: Path, mapping: dict[str, str], algorithm: str) -> None:
    path.write_text(
        f"[options]\nversion = 1\nhash = {algorithm}\nignoreAddress = true\n"
        "ignoreMipmap = true\nreduceHash = false\n\n[hashes]\n"
        + "\n".join(f"{key} = {value}" for key, value in sorted(mapping.items())) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-zip", type=Path, required=True, help="previously verified UI ZIP")
    parser.add_argument("--pack-root", type=Path, required=True, help="new UI pack root containing NPJH50247")
    parser.add_argument("--report", type=Path, required=True, help="JSON merge and readback report")
    args = parser.parse_args()
    game = args.pack_root / GAME
    report = {"legacy_zip": args.legacy_zip.name, "current_mappings_take_precedence": True,
              "algorithms": {}, "copied_images": 0}
    copied = set()
    with zipfile.ZipFile(args.legacy_zip) as source:
        for algorithm in ("xxh64", "quick"):
            filename = f"textures-{algorithm}.ini"
            current = read_mapping((game / filename).read_text(encoding="utf-8"))
            legacy = read_mapping(source.read(f"{GAME}/{filename}").decode("utf-8"))
            added = {key: value for key, value in legacy.items() if key not in current}
            for value in set(added.values()):
                payload = source.read(f"{GAME}/{value}")
                target = game / value
                if target.exists():
                    if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(payload).digest():
                        raise ValueError(f"image path collision: {value}")
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(payload)
                    copied.add(value)
            shared_different = sum(current[key] != legacy[key] for key in current.keys() & legacy.keys())
            current.update(added)
            write_mapping(game / filename, current, algorithm)
            if algorithm == "xxh64":
                write_mapping(game / "textures.ini", current, algorithm)
            back = read_mapping((game / filename).read_text(encoding="utf-8"))
            if back != current or any(not (game / value).is_file() for value in back.values()):
                raise ValueError(f"mapping readback failed: {algorithm}")
            report["algorithms"][algorithm] = {"legacy_aliases_added": len(added),
                "current_overrides_preserved": shared_different, "total_mappings": len(current)}
    report["copied_images"] = len(copied)
    manifest_path = args.pack_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = "v1.2"
    manifest["legacy_aliases"] = report
    manifest["image_files"] = sum(1 for _ in (game / "CN_HD").rglob("*.png"))
    manifest["mappings"] = {key: value["total_mappings"] for key, value in report["algorithms"].items()}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
