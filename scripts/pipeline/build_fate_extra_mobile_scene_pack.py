#!/usr/bin/env python3
"""Build a mobile/low-memory scene pack from the PPSSPP forum's 50% pack.

The official forum's experimental mobile archive keeps the same xxh64 keys as
the full pack while halving scene texture dimensions. This emits only the
non-language scene/model/effect mappings used by the Chinese release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct
import zipfile


GAME = "NPJH50247"
INCLUDE = {
    "effects",
    "textures_arena",
    "textures_character",
    "textures_enemy",
    "textures_location",
    "tiled_bg",
    "tiled_chara",
    "tiled_effects",
}
EXCLUDE_TILED_BG = {
    "title",
    "newgame_1",
    "newgame_2",
    "gameover",
    "result",
    "interlude_1",
    "spiritualhacking",
    "chapterstart",
    "ending_1",
    "ending_2",
    "phone",
}
KTX2_MAGIC = b"\xabKTX 20\xbb\r\n\x1a\n"


def parse_hashes(text: str) -> list[tuple[str, str]]:
    in_hashes = False
    rows = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line.startswith("["):
            in_hashes = line.lower() == "[hashes]"
            continue
        if not in_hashes or not line:
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{24})\s*=\s*(\S+)", line)
        if not match:
            if "=" in line and is_scene(line.split("=", 1)[1].strip()):
                raise ValueError(f"invalid scene mapping: {raw!r}")
            continue
        rows.append((match.group(1).lower(), match.group(2)))
    if not rows:
        raise ValueError("source textures.ini has no hash mappings")
    return rows


def is_scene(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if not parts or parts[0].lower() not in INCLUDE:
        return False
    return not (
        parts[0].lower() == "tiled_bg"
        and len(parts) > 1
        and parts[1].lower() in EXCLUDE_TILED_BG
    )


def ktx2_info(data: bytes, label: str) -> tuple[int, int]:
    if len(data) < 68 or data[:12] != KTX2_MAGIC:
        raise ValueError(f"invalid KTX2 header: {label}")
    vk_format, type_size, width, height, depth, layers, faces, levels, supercompression = struct.unpack_from("<9I", data, 12)
    dfd_offset, dfd_length = struct.unpack_from("<2I", data, 48)
    if vk_format != 0 or type_size != 1 or supercompression != 2:
        raise ValueError(f"unexpected KTX2 storage format in {label}: vk={vk_format}, type={type_size}, supercompression={supercompression}")
    if depth or layers or faces != 1 or levels < 1 or dfd_offset + dfd_length > len(data):
        raise ValueError(f"invalid KTX2 dimensions/DFD in {label}")
    dfd = data[dfd_offset:dfd_offset + dfd_length]
    if len(dfd) < 13 or dfd[12] != 166:
        raise ValueError(f"expected UASTC KTX2 in {label}")
    return width, height


def build(source_zip: Path, output: Path) -> dict:
    source_zip = source_zip.resolve()
    output = output.resolve()
    source_sha = hashlib.sha256(source_zip.read_bytes()).hexdigest()
    with zipfile.ZipFile(source_zip) as source:
        if source.testzip() is not None:
            raise ValueError("mobile source archive failed ZIP CRC validation")
        names = set(source.namelist())
        if "textures.ini" not in names:
            raise FileNotFoundError("mobile source archive has no root textures.ini")
        rows = [row for row in parse_hashes(source.read("textures.ini").decode("utf-8-sig", "replace")) if is_scene(row[1])]
        by_key: dict[str, tuple[str, bytes, tuple[int, int]]] = {}
        for key, rel in rows:
            if rel not in names:
                raise FileNotFoundError(f"mapping {key} references missing source image: {rel}")
            data = source.read(rel)
            size = ktx2_info(data, rel)
            previous = by_key.get(key)
            if previous is not None and previous[1] != data:
                raise ValueError(f"conflicting mobile scene images for hash {key}")
            by_key.setdefault(key, (rel, data, size))

        # Keep one output image per distinct source asset, while retaining all
        # hash aliases in the ini.
        game = f"{GAME}/"
        assets: dict[str, bytes] = {}
        config_rows = []
        for key, (rel, data, size) in sorted(by_key.items()):
            name = hashlib.sha256(rel.encode("utf-8")).hexdigest()[:20] + ".ktx2"
            target = f"SceneHD/{name}"
            existing = assets.get(target)
            if existing is not None and existing != data:
                raise ValueError(f"output filename collision: {target}")
            assets[target] = data
            config_rows.append(f"{key} = {target}")

    config = (
        "[options]\nversion = 1\nhash = xxh64\nignoreAddress = true\n"
        "ignoreMipmap = true\nreduceHash = false\n\n[hashes]\n"
        + "\n".join(config_rows)
        + "\n"
    )
    sizes = [size for _rel, _data, size in by_key.values()]
    max_width = max(w for w, _h in sizes)
    max_height = max(h for _w, h in sizes)
    readme = """# Fate/EXTRA v1.1 高清场景纹理包（移动设备版）

本包采用 PPSSPP 官方论坛 `Fate Extra Texture Pack` 作者发布的实验性移动版场景纹理，纹理边长为完整版的 50%，约为原版游戏的 2 倍。它保留了完整版对应的 xxh64 哈希键；中文 UI 与字库仍使用本汉化项目的高清 UI 包。

在 PPSSPP 中使用。若设备安装完整版时出现黑纹理、黑屏或明显卡顿，可改用本包与 `Fate_Extra_CN-v1.1-HD-UI-Pack.zip`；场景完整版和移动版二选一，不要叠装。

官方来源：PPSSPP 论坛「Fate Extra Texture Pack」，作者 user555。移动版仅作低显存设备的兼容选项。若仍黑屏，请先把图形渲染分辨率降到 2x 或 3x PSP，并确认 PPSSPP 版本为 1.15 或更高。

汉化纹理映射与整合：酱油馒头粥。原游戏与素材版权归各自权利人所有。
"""
    manifest = {
        "game_id": GAME,
        "version": "v1.1",
        "variant": "mobile-50-percent-scene-resolution",
        "hash": "xxh64",
        "source": "PPSSPP forums, Fate Extra Texture Pack by user555, experimental mobile archive",
        "source_url": "https://forums.ppsspp.org/showthread.php?tid=30052",
        "source_archive_sha256": source_sha,
        "mapping_count": len(config_rows),
        "image_count": len(assets),
        "image_bytes": sum(map(len, assets.values())),
        "max_dimensions": [max_width, max_height],
        "ktx2_format": "UASTC, Zstandard supercompression",
        "runtime_test": "Assets were validated in PPSSPP 1.20.4 macOS as part of the mobile combined pack using existing save slots 1 and 4; no black screen observed. Exact reporter scene/device not reproduced.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as dest:
        for rel, data in sorted(assets.items()):
            dest.writestr(game + rel, data)
        dest.writestr(game + "textures.ini", config)
        dest.writestr("README.md", readme)
        dest.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    with zipfile.ZipFile(output) as check:
        if check.testzip() is not None:
            raise ValueError("output ZIP CRC validation failed")
        actual = set(check.namelist())
        if len(config_rows) != len(by_key) or any(game + row.split(" = ", 1)[1] not in actual for row in config_rows):
            raise ValueError("output mapping readback failed")
    manifest["zip"] = str(output)
    manifest["zip_bytes"] = output.stat().st_size
    manifest["zip_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".build-report.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-zip", type=Path, required=True, help="PPSSPP forum mobile scene pack ZIP")
    parser.add_argument("--out", type=Path, required=True, help="output scene-only mobile texture pack ZIP")
    args = parser.parse_args()
    print(json.dumps(build(args.source_zip, args.out), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
