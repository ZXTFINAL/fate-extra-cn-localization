#!/usr/bin/env python3
"""Install the Japanese-release scene HD pack into a PPSSPP texture folder."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil


BEGIN = "# BEGIN FATE EXTRA SCENE HD v1.1"
END = "# END FATE EXTRA SCENE HD v1.1"


def install(pack: Path, target: Path) -> dict:
    game = pack / "NPJH50247" if (pack / "NPJH50247").is_dir() else pack
    source_ini = game / "textures.ini"
    if not source_ini.is_file():
        raise FileNotFoundError(f"scene pack textures.ini not found: {source_ini}")
    fragment = source_ini.read_text(encoding="utf-8-sig")
    mapping = re.findall(r"(?im)^([0-9a-f]{24})\s*=\s*(SceneHD/[^\r\n]+)", fragment)
    if not mapping or len(dict(mapping)) != len(mapping):
        raise ValueError("scene pack has missing or duplicate mappings")

    for _, name in mapping:
        image = (game / name).resolve()
        if not image.is_relative_to(game.resolve()) or not image.is_file():
            raise FileNotFoundError(f"mapped scene image missing or unsafe: {name}")

    target.mkdir(parents=True, exist_ok=True)
    ini = target / "textures.ini"
    before = ini.read_bytes() if ini.exists() else None
    if before:
        text = before.decode("utf-8-sig")
        options = re.search(r"(?ims)^\[options\]\s*$(.*?)(?=^\[|\Z)", text)
        hash_match = re.search(r"(?im)^\s*hash\s*=\s*(\w+)", options[1]) if options else None
        algorithm = hash_match[1].lower() if hash_match else "quick"
        if algorithm != "xxh64":
            raise ValueError(f"scene pack needs hash=xxh64; found {algorithm!r}. No files changed.")
    else:
        text = fragment
        algorithm = "xxh64"

    text = re.sub(r"(?ms)^" + re.escape(BEGIN) + r"\n.*?^" + re.escape(END) + r"\n?", "", text)
    own_keys = {key for key, _ in mapping}
    lines: list[str] = []
    removed = 0
    for line in text.splitlines():
        match = re.match(r"^\s*([0-9a-fA-F]{24})\s*=", line)
        if match and match[1].lower() in own_keys:
            removed += 1
            continue
        lines.append(line)
    text = "\n".join(lines) + "\n"
    section = re.search(r"(?im)^\[hashes\]\s*$", text)
    if not section:
        text += "\n[hashes]\n"
        section = re.search(r"(?im)^\[hashes\]\s*$", text)
    block = "\n" + BEGIN + "\n" + "\n".join(f"{key} = {name}" for key, name in mapping) + "\n" + END + "\n"
    text = text[:section.end()] + block + text[section.end():]

    backup = None
    if before:
        backup = target / f"textures.ini.before-scene-hd-{datetime.now():%Y%m%d-%H%M%S}.bak"
        backup.write_bytes(before)
    shutil.copytree(game / "SceneHD", target / "SceneHD", dirs_exist_ok=True)
    temp = ini.with_suffix(".ini.scene-hd-tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(ini)

    installed_text = ini.read_text(encoding="utf-8-sig")
    missing = [key for key, name in mapping if f"{key} = {name}" not in installed_text or not (target / name).is_file()]
    if missing:
        raise ValueError(f"scene install readback failed: {missing[:5]}")
    report = {
        "target": str(target),
        "hash": algorithm,
        "mappings": len(mapping),
        "replaced_matching_keys": removed,
        "backup": str(backup) if backup else None,
        "ini_sha256": hashlib.sha256(ini.read_bytes()).hexdigest(),
        "runtime_test": "not run; restart PPSSPP to reload textures",
    }
    report_path = target / "SceneHD/install-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pack", type=Path, default=Path(__file__).resolve().parent, help="Unpacked scene pack directory")
    ap.add_argument("--target", type=Path, required=True, help="Existing PSP/TEXTURES/NPJH50247 folder")
    args = ap.parse_args()
    print(json.dumps(install(args.pack, args.target), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
