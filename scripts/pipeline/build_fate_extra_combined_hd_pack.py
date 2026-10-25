#!/usr/bin/env python3
"""Combine the scene and Chinese UI PPSSPP texture packs into one config."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile


GAME = "NPJH50247"
KEY_RE = re.compile(r"^([0-9a-fA-F]{24})\s*=\s*(\S+)\s*$")


def parse_hashes(text: str, label: str) -> dict[str, str]:
    in_hashes = False
    result: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line.startswith("["):
            in_hashes = line.lower() == "[hashes]"
            continue
        if not in_hashes or not line:
            continue
        match = KEY_RE.fullmatch(line)
        if not match:
            raise ValueError(f"invalid hash mapping in {label}: {raw!r}")
        key, name = match.group(1).lower(), match.group(2)
        if key in result:
            raise ValueError(f"duplicate texture key {key} in {label}")
        if not (name.startswith("SceneHD/") or name.startswith("CN_HD/")):
            raise ValueError(f"unexpected texture path in {label}: {name}")
        result[key] = name
    if not result:
        raise ValueError(f"no texture mappings found in {label}")
    return result


def read_mapping(archive: zipfile.ZipFile, member: str) -> dict[str, str]:
    return parse_hashes(archive.read(member).decode("utf-8-sig"), f"{archive.filename}:{member}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


README_FULL = """# Fate/EXTRA 简体中文 v1.2 高清纹理合并包

本包把高清场景纹理与简体中文 UI/字库纹理合并到**唯一一份** `NPJH50247/textures.ini`，避免两个独立包的同名配置互相覆盖。哈希模式为 `xxh64`；同一纹理哈希同时命中时，中文 UI 映射优先，场景图不会盖回中文菜单、标题或字库。

## 安装

1. 完全退出 PPSSPP。
2. 解压本 ZIP，将里面的 `NPJH50247` 文件夹整体放到当前记忆棒的 `PSP/TEXTURES/` 下。最终路径应为 `PSP/TEXTURES/NPJH50247/textures.ini`。
3. 如果已有 `NPJH50247` 纹理目录，先备份并移走旧目录，再安装本包，避免旧配置和旧韩文纹理残留。请只使用这一份合并配置；不要再将独立场景包或 UI 包中的配置覆盖进来。
4. PPSSPP 1.15 或更新版本中启用「纹理替换」。为了看清高分辨率纹理，建议把「图形 → 渲染分辨率」设为 8 倍 PSP 分辨率，然后完全重启 PPSSPP。

本包只适用于 PPSSPP，不适用于实体 PSP。场景包中的 KTX2 纹理需要 PPSSPP 1.15+。PPSSPP 使用的记忆棒目录可在「设置 → 系统」中查看。

## 内容与优先级

- `SceneHD/`：日版场景、角色/模型与特效纹理。
- `CN_HD/`：简体中文 UI、标题开场、正文与注音字库纹理。
- 唯一 `textures.ini` 收录两者映射；场景与 UI 有哈希重叠时由中文 UI 映射优先，具体数量记录在包内 manifest。

如果你已经安装了其他纹理包，请先用干净的 `NPJH50247` 目录测试。署名：酱油馒头粥。原游戏及素材版权归各自权利人所有。
"""

README_MOBILE = """# Fate/EXTRA 简体中文 v1.2 高清纹理合并包（移动设备版）

本包把 PPSSPP 论坛作者 user555 发布的 50% 分辨率移动场景纹理，与本汉化的简体中文 UI、正文与注音字库合成到**唯一一份** `NPJH50247/textures.ini`。场景纹理边长为完整版的 50%（约为原版游戏的 2 倍），中文 UI 和字库保持相同的高清质量。

## 安装

1. 完全退出 PPSSPP。
2. 解压本 ZIP，将里面的 `NPJH50247` 文件夹整体放到当前记忆棒的 `PSP/TEXTURES/` 下。最终路径应为 `PSP/TEXTURES/NPJH50247/textures.ini`。
3. 如果已有 `NPJH50247` 纹理目录，先备份并移走旧目录，再安装本包，避免旧配置和旧韩文纹理残留。请只安装本移动版合并包，不要再叠加完整版场景包、独立 UI 包或其它 `textures.ini`。
4. PPSSPP 1.15 或更新版本中启用「纹理替换」。手持设备先用 2x 或 3x PSP 渲染分辨率；设备性能允许时再提高。完全重启 PPSSPP 后载入游戏。

本包只适用于 PPSSPP，不适用于实体 PSP。场景纹理使用 UASTC KTX2；PPSSPP 1.15+ 支持。该版本用于降低场景纹理的显存占用，不能保证修复所有设备或 ISO 的运行错误。

本 v1.2 UI 映射与合并配置已完成静态回读校验；此组合包尚未在 PPSSPP 逐项运行。低显存设备可能需要降低场景分辨率或改用 UI-only 包。

## 内容与来源

- `SceneHD/`：PPSSPP 论坛「Fate Extra Texture Pack」作者 user555 的实验性移动版场景纹理，保持日版 `xxh64` 哈希键，分辨率为完整版的一半。
- `CN_HD/`：本汉化的简体中文 UI、开场画面、正文与注音字库。
- 合并配置中如有同一哈希，中文 UI 映射优先。

如果仍出现黑纹理或卡顿，先降低渲染分辨率，并把 PPSSPP 图形后端切换为 OpenGL 测试。若出现 `PC = 00000000` 的 CPU 错误页，请另外记录 PPSSPP 版本、系统、后端和触发步骤；这类画面本身不能证明纹理包是根因。

汉化纹理映射与整合：酱油馒头粥。原游戏及素材版权归各自权利人所有。
"""


def copy_member(src: zipfile.ZipFile, name: str, dst: zipfile.ZipFile) -> tuple[int, str]:
    info = src.getinfo(name)
    out_info = zipfile.ZipInfo(name, date_time=info.date_time)
    out_info.compress_type = zipfile.ZIP_STORED
    out_info.external_attr = info.external_attr
    digest = hashlib.sha256()
    size = 0
    with src.open(info, "r") as reader, dst.open(out_info, "w", force_zip64=True) as writer:
        while True:
            chunk = reader.read(1 << 20)
            if not chunk:
                break
            writer.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def build(scene_zip: Path, ui_zip: Path, output: Path, variant: str = "full",
          version: str = "v1.2", runtime_test_note: str = "Static ZIP/INI/resource-reference checks only; PPSSPP runtime pending.") -> dict:
    if variant not in {"full", "mobile"}:
        raise ValueError(f"unsupported combined-pack variant: {variant}")
    with zipfile.ZipFile(scene_zip) as scene, zipfile.ZipFile(ui_zip) as ui:
        scene_map = read_mapping(scene, f"{GAME}/textures.ini")
        ui_map = read_mapping(ui, f"{GAME}/textures-xxh64.ini")
        scene_names = set(scene.namelist())
        ui_names = set(ui.namelist())
        for key, name in scene_map.items():
            member = f"{GAME}/{name}"
            if member not in scene_names:
                raise FileNotFoundError(f"scene mapping {key} references missing {member}")
        for key, name in ui_map.items():
            member = f"{GAME}/{name}"
            if member not in ui_names:
                raise FileNotFoundError(f"UI mapping {key} references missing {member}")

        overlap = set(scene_map) & set(ui_map)
        combined = dict(scene_map)
        combined.update(ui_map)  # Same precedence as installing scene first, then UI.
        ini_text = (
            "[options]\nversion = 1\nhash = xxh64\nignoreAddress = true\n"
            "ignoreMipmap = true\nreduceHash = false\n\n[hashes]\n"
            + "\n".join(f"{key} = {combined[key]}" for key in sorted(combined))
            + "\n"
        )

        scene_assets = sorted(n for n in scene_names if n.startswith(f"{GAME}/SceneHD/"))
        ui_assets = sorted(n for n in ui_names if n.startswith(f"{GAME}/CN_HD/"))
        if not scene_assets or not ui_assets:
            raise ValueError("one of the source archives has no mapped image directory")
        output.parent.mkdir(parents=True, exist_ok=True)
        copied: dict[str, dict] = {}
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as dst:
            for name in scene_assets:
                size, digest = copy_member(scene, name, dst)
                copied[name] = {"bytes": size, "sha256": digest}
            for name in ui_assets:
                if name in copied:
                    raise ValueError(f"duplicate output path across packs: {name}")
                size, digest = copy_member(ui, name, dst)
                copied[name] = {"bytes": size, "sha256": digest}
            dst.writestr(f"{GAME}/textures.ini", ini_text)
            readme = README_MOBILE if variant == "mobile" else README_FULL
            dst.writestr("README.md", readme.replace("v1.2", version))
            manifest = {
                "game_id": GAME,
                "version": version,
                "variant": variant,
                "hash": "xxh64",
                "scene_mapping_count": len(scene_map),
                "ui_mapping_count": len(ui_map),
                "overlapping_keys": len(overlap),
                "ui_override_keys": len(overlap),
                "combined_mapping_count": len(combined),
                "scene_image_count": len(scene_assets),
                "ui_image_count": len(ui_assets),
                "image_bytes": sum(v["bytes"] for v in copied.values()),
                "sources": {
                    "scene_pack_sha256": sha256_file(scene_zip),
                    "ui_pack_sha256": sha256_file(ui_zip),
                },
                "runtime_test": runtime_test_note,
            }
            dst.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    with zipfile.ZipFile(output) as check:
        if check.testzip() is not None:
            raise ValueError("ZIP CRC validation failed")
        back = read_mapping(check, f"{GAME}/textures.ini")
        if back != combined:
            raise ValueError("combined textures.ini readback mismatch")
        members = set(check.namelist())
        missing = [f"{GAME}/{name}" for name in back.values() if f"{GAME}/{name}" not in members]
        if missing:
            raise FileNotFoundError(f"combined archive references missing files: {missing[:5]}")
        manifests = json.loads(check.read("manifest.json"))
    manifests["zip"] = str(output)
    manifests["zip_bytes"] = output.stat().st_size
    manifests["zip_sha256"] = sha256_file(output)
    output.with_suffix(".build-report.json").write_text(
        json.dumps(manifests, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifests


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene-zip", type=Path, required=True, help="scene texture ZIP")
    parser.add_argument("--ui-zip", type=Path, required=True, help="v1.2 Chinese UI texture ZIP")
    parser.add_argument("--out", type=Path, required=True, help="combined texture ZIP output")
    parser.add_argument("--variant", choices=["full", "mobile"], default="full", help="README and manifest variant")
    parser.add_argument("--version", default="v1.2", help="release version written in README and manifest")
    parser.add_argument("--runtime-test-note", default="Static ZIP/INI/resource-reference checks only; PPSSPP runtime pending.",
                        help="runtime validation note written in manifest")
    args = parser.parse_args()
    print(json.dumps(build(args.scene_zip, args.ui_zip, args.out, args.variant, args.version,
                           args.runtime_test_note), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
