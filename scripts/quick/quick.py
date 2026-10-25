#!/usr/bin/env python3
"""Fate/Extra 简体中文——一键重建与快速编辑工具。

设计目标：任何人拿到本仓库 + 自备正版 ISO，两条命令就能产出可运行的中文 ISO；
日常改几句话、换几张图，再跑一次增量重建即可，不必重跑全部解包/补字/审计。

用法（在仓库根目录执行）：

    python3 scripts/quick/quick.py bootstrap --iso iso/original.iso
    python3 scripts/quick/quick.py rebuild

    python3 scripts/quick/quick.py text find "セイバー"
    python3 scripts/quick/quick.py text set --id 1a2b3c4d5e6f7788 --zh "欢迎来到月之圣杯"
    python3 scripts/quick/quick.py rebuild

    python3 scripts/quick/quick.py image decode --package pack/000001/interface/shop/shop_00.txb
    python3 scripts/quick/quick.py image apply --config data/evidence/ui/ui-text-patches.json
    python3 scripts/quick/quick.py status
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work"
EXTRACT = WORK / "extracted"
TRANS = WORK / "translation"
BUILD = WORK / "build"
ASSETS = BUILD / "assets"
SOURCE_DIR = WORK / "source"
SOURCE_CPK = SOURCE_DIR / "data.cpk"
STATE = WORK / ".quick-state.json"

PIPELINE = ROOT / "scripts" / "pipeline"
REPO_TEXT = ROOT / "data" / "translation" / "text.jsonl"
REPO_GLYPH = ROOT / "data" / "translation" / "glyph-map.json"
REPO_POEM_GLYPH = ROOT / "data" / "translation" / "poem-glyph-map.json"
REPO_REMAINING_JAPANESE_FIXES = ROOT / "data" / "review" / "remaining-japanese-fixes.jsonl"
REPO_REVIEW_LEDGER_DIR = ROOT / "data" / "review"
REPO_BUILD_LAYOUT_FIXES = REPO_REVIEW_LEDGER_DIR / "dialogue-layout-fixes.jsonl"
REPO_BUILD_REVIEW_LEDGERS = (
    "merged-initial-fixes.jsonl",
    "context-opening-fixes.jsonl",
    "context-extra-fixes.jsonl",
    "context-lane-1-fixes.jsonl",
    "context-lane-2-fixes.jsonl",
    "lane2-noise-fixes.json",
    "context-lane-3-fixes.jsonl",
    "context-lane-4-fixes.jsonl",
    "control-restoration-fixes.jsonl",
    "root-manual-fixes.jsonl",
    "ruby-fixes.jsonl",
    "consistency-fixes.jsonl",
    "remaining-japanese-fixes.jsonl",
)
REPO_SERVANT_DIALOGUE_FIXES = ROOT / "data" / "review" / "servant-dialogue-fixes.jsonl"
REPO_SERVANT_DIALOGUE_REFERENCES = ROOT / "data" / "evidence" / "servant-dialogue-references.jsonl"

RUBY_PAIR_RE = re.compile(r"#RUBS(.*?)#RUBE(.*?)#REND", re.S)

ISO_MEMBER = "PSP_GAME/USRDIR/data.cpk"
ISO_MEMBER_FALLBACKS = ("PSP_GAME/USRDIR/DATA.CPK", "PSP_GAME/USRDIR/data.CPK")

# 日版原盘（NPJH-50247）已知校验和。仅用于提示"你用的不是工程基准盘"，不阻断。
KNOWN_ISO_SHA256 = {
    "60399d610cbcda96601374a2e621a22bb58505c403c6fa4221eec5e87235667b":
        "Fate/Extra (NPJH-50247) 日版原盘",
}

SECTOR = 2048
PVD_SECTOR = 16


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #

def log(message: str) -> None:
    print(f"[quick] {message}", flush=True)


def die(message: str, code: int = 1) -> None:
    print(f"[quick] 错误：{message}", file=sys.stderr, flush=True)
    raise SystemExit(code)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


def run(command: list[str], cwd: Path | None = None) -> None:
    log("$ " + " ".join(command))
    started = time.time()
    result = subprocess.run(command, cwd=str(cwd or ROOT))
    if result.returncode != 0:
        die(f"命令失败（退出码 {result.returncode}）：{' '.join(command)}")
    log(f"  完成，用时 {time.time() - started:.1f}s")


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    temporary.replace(path)


def read_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_state(**updates) -> None:
    state = read_state()
    state.update(updates)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# ISO9660：从自备 ISO 里取出 data.cpk，不需要挂载
# --------------------------------------------------------------------------- #

def _read_dir(image, extent: int, size: int):
    image.seek(extent * SECTOR)
    data = image.read(size)
    position = 0
    while position < size:
        length = data[position]
        if length == 0:
            position = (position // SECTOR + 1) * SECTOR
            continue
        record = data[position:position + length]
        if len(record) < 34:
            break
        entry_extent = struct.unpack_from("<I", record, 2)[0]
        entry_size = struct.unpack_from("<I", record, 10)[0]
        flags = record[25]
        name_length = record[32]
        name = record[33:33 + name_length].decode("latin-1")
        if name not in ("\x00", "\x01"):
            yield name.split(";")[0], entry_extent, entry_size, bool(flags & 2)
        position += length


def _resolve(image, path: str):
    image.seek(PVD_SECTOR * SECTOR)
    pvd = image.read(SECTOR)
    if pvd[0] != 1 or pvd[1:6] != b"CD001":
        die("这不是有效的 ISO9660 镜像")
    root_extent = struct.unpack_from("<I", pvd, 158)[0]
    root_size = struct.unpack_from("<I", pvd, 166)[0]
    extent, size = root_extent, root_size
    for part in [p for p in path.split("/") if p]:
        found = None
        for name, entry_extent, entry_size, is_dir in _read_dir(image, extent, size):
            if name.lower() == part.lower():
                found = (entry_extent, entry_size, is_dir)
                break
        if found is None:
            return None
        extent, size, is_dir = found
        if part != path.split("/")[-1] and not is_dir:
            return None
    return extent, size


def extract_from_iso(iso: Path, member: str, destination: Path) -> int:
    with iso.open("rb") as image:
        located = _resolve(image, member)
        if located is None:
            for alternative in ISO_MEMBER_FALLBACKS:
                located = _resolve(image, alternative)
                if located is not None:
                    member = alternative
                    break
        if located is None:
            die(f"ISO 内找不到 {ISO_MEMBER}；请确认这是日版《Fate/Extra》(NPJH-50247)")
        extent, size = located
        image.seek(extent * SECTOR)
        destination.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with destination.open("wb") as out:
            remaining = size
            while remaining > 0:
                chunk = image.read(min(1 << 20, remaining))
                if not chunk:
                    die("读取 ISO 时提前结束")
                out.write(chunk)
                written += len(chunk)
                remaining -= len(chunk)
    return written


# --------------------------------------------------------------------------- #
# bootstrap / rebuild
# --------------------------------------------------------------------------- #

def find_iso(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            die(f"找不到 ISO：{path}")
        return path
    candidates = sorted((ROOT / "iso").glob("*.iso")) + sorted((ROOT / "iso").glob("*.ISO"))
    if not candidates:
        die("没有指定 ISO。把正版镜像放到 iso/ 下，或用 --iso 指定路径")
    if len(candidates) > 1:
        log(f"iso/ 下有多个镜像，使用第一个：{candidates[0].name}")
    return candidates[0]


def ensure_source_cpk(iso: Path | None) -> Path:
    if SOURCE_CPK.exists() and SOURCE_CPK.stat().st_size > 1_000_000:
        return SOURCE_CPK
    image = find_iso(str(iso) if iso else None)
    log(f"从 {image.name} 提取 {ISO_MEMBER}（不挂载、不修改原盘）")
    size = extract_from_iso(image, ISO_MEMBER, SOURCE_CPK)
    save_state(iso=str(image), iso_sha256=sha256(image), source_cpk_bytes=size)
    log(f"已提取，{human(size)}")
    return SOURCE_CPK


def ensure_extracted() -> None:
    manifest = EXTRACT / "manifest.json"
    if manifest.exists():
        return
    run([sys.executable, str(PIPELINE / "extract_fate_extra.py"), "extract",
         str(SOURCE_CPK), "--output", str(EXTRACT)])


def ensure_translations() -> None:
    TRANS.mkdir(parents=True, exist_ok=True)
    target = TRANS / "text.jsonl"
    if not target.exists():
        if not REPO_TEXT.exists():
            die("仓库里没有 data/translation/text.jsonl，无法初始化译文")
        shutil.copyfile(REPO_TEXT, target)
        log(f"译文主表已就位：{target}")
    glyph = TRANS / "glyph-map.json"
    if not glyph.exists() and REPO_GLYPH.exists():
        shutil.copyfile(REPO_GLYPH, glyph)
    poem = TRANS / "poem-glyph-map.json"
    if not poem.exists() and REPO_POEM_GLYPH.exists():
        shutil.copyfile(REPO_POEM_GLYPH, poem)
    refs = TRANS / "refs.jsonl"
    if not refs.exists():
        log("生成引用表 refs.jsonl（ID → 文件/偏移/指针），首次较慢")
        run([sys.executable, str(PIPELINE / "dump_fate_extra_text.py"),
             str(EXTRACT / "packages" / "pack" if (EXTRACT / "packages" / "pack").is_dir() else EXTRACT / "packages"),
             "--day-input", str(EXTRACT / "cpk" / "day"),
             "--output", str(target),
             "--references", str(refs)])
        # dump 会用空译文覆盖主表，重新写回仓库译文
        shutil.copyfile(REPO_TEXT, target)


def prepare_build_translations() -> tuple[Path, Path]:
    """Apply reviewed text fixes, then the final dialogue layout ledger."""
    main_path = TRANS / "text.jsonl"
    rows = load_jsonl(main_path)
    by_id = {row["id"]: row for row in rows}
    if len(by_id) != len(rows):
        die("译文主表存在重复 ID，无法准备构建输入")

    applied_by_ledger: dict[str, int] = {}
    for ledger_name in REPO_BUILD_REVIEW_LEDGERS:
        ledger = REPO_REVIEW_LEDGER_DIR / ledger_name
        if not ledger.is_file():
            continue
        if ledger.suffix == ".json":
            payload = json.loads(ledger.read_text(encoding="utf-8"))
            fixes = payload.get("fixes", []) if isinstance(payload, dict) else payload
        else:
            fixes = load_jsonl(ledger)
        if not isinstance(fixes, list):
            die(f"审校文件格式错误：{ledger}")
        applied = 0
        for fix in fixes:
            row = by_id.get(fix["id"])
            if row is None:
                die(f"审校修正的 ID 不在主表中：{ledger.name}: {fix['id']}")
            if "zh_cn" not in fix:
                die(f"审校修正缺少 zh_cn：{ledger.name}: {fix['id']}")
            row["zh_cn"] = fix["zh_cn"]
            applied += 1
        applied_by_ledger[ledger.name] = applied

    # A reading that merely repeats the Chinese base adds visual noise and can
    # create tiny, blurred superscripts. Keep semantic/foreign readings.
    duplicate_rubies = 0
    for row in rows:
        text = row.get("zh_cn", "")
        def remove_duplicate(match):
            nonlocal duplicate_rubies
            upper, base = match.groups()
            if upper == base:
                duplicate_rubies += 1
                return base
            return match.group(0)
        row["zh_cn"] = RUBY_PAIR_RE.sub(remove_duplicate, text)
    write_jsonl(main_path, rows)
    review_report = {
        "translation_rows": len(rows),
        "applied_by_ledger": applied_by_ledger,
        "applied_fixes": sum(applied_by_ledger.values()),
        "removed_identical_ruby_pairs": duplicate_rubies,
        "precedence": list(REPO_BUILD_REVIEW_LEDGERS),
    }
    report_path = BUILD / "review-ledger-v12.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(review_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"审校修正已应用：{review_report['applied_fixes']} 条；移除重复注音 {duplicate_rubies} 处")

    servant_fixes = load_jsonl(REPO_SERVANT_DIALOGUE_FIXES) if REPO_SERVANT_DIALOGUE_FIXES.exists() else []
    servant_refs = load_jsonl(REPO_SERVANT_DIALOGUE_REFERENCES) if REPO_SERVANT_DIALOGUE_REFERENCES.exists() else []
    servant_fix_by_id = {row["id"]: row for row in servant_fixes}
    servant_ref_by_id = {row["id"]: row for row in servant_refs}
    if servant_fix_by_id.keys() != servant_ref_by_id.keys():
        die("从者对白译文与来源指针清单的 ID 不一致")

    build_rows = list(rows)
    main_ids = set(by_id)
    for ref in servant_refs:
        if ref["id"] in main_ids:
            die(f"从者对白 ID 与主剧情 ID 冲突：{ref['id']}")
        fix = servant_fix_by_id[ref["id"]]
        build_rows.append({
            "id": ref["id"],
            "jp": ref["jp"],
            "jp_bytes_hex": ref["jp_bytes_hex"],
            "zh_cn": fix["zh_cn"],
            "reference_count": ref.get("reference_count", 1),
        })

    # Semantic review ledgers can replace already-wrapped source rows. Apply
    # the reviewed layout ledger last so these edits cannot reintroduce long
    # lines or one-character orphan lines into the actual build input.
    layout_fixes = load_jsonl(REPO_BUILD_LAYOUT_FIXES) if REPO_BUILD_LAYOUT_FIXES.is_file() else []
    build_by_id = {row["id"]: row for row in build_rows}
    if len(build_by_id) != len(build_rows):
        die("合并后的构建译文存在重复 ID，无法应用最终排版修正")
    for fix in layout_fixes:
        row = build_by_id.get(fix["id"])
        if row is None:
            die(f"最终排版修正的 ID 不在构建译文中：{fix['id']}")
        if "zh_cn" not in fix:
            die(f"最终排版修正缺少 zh_cn：{fix['id']}")
        row["zh_cn"] = fix["zh_cn"]
    if layout_fixes:
        write_jsonl(main_path, rows)
    review_report["post_layout_ledger"] = REPO_BUILD_LAYOUT_FIXES.name
    review_report["post_layout_fixes"] = len(layout_fixes)
    report_path.write_text(json.dumps(review_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if layout_fixes:
        log(f"最终对话排版修正已应用：{len(layout_fixes)} 条")

    main_refs = load_jsonl(TRANS / "refs.jsonl")
    build_refs = list(main_refs)
    existing_ref_keys = {(r["id"], r["file"], r["text_offset"]) for r in main_refs}
    for ref in servant_refs:
        key = (ref["id"], ref["file"], ref["text_offset"])
        if key in existing_ref_keys:
            continue
        build_refs.append({
            "id": ref["id"],
            "file": ref["file"],
            "text_offset": ref["text_offset"],
            "pointer_offsets": ref["pointer_offsets"],
            "categories": ["servant_dialogue"],
            "kinds": ["character_dialogue"],
        })
        existing_ref_keys.add(key)

    build_text_path = TRANS / "build-text.jsonl"
    build_refs_path = TRANS / "build-refs.jsonl"
    write_jsonl(build_text_path, build_rows)
    write_jsonl(build_refs_path, build_refs)
    log(f"构建译文已合并：主剧情 {len(rows)} 条 + 从者对白 {len(servant_refs)} 条；引用 {len(build_refs)} 条")
    return build_text_path, build_refs_path


def verify_inventory(strict: bool = False) -> None:
    """把本地解包树与 data/inventory 的清单逐文件比对。"""
    import gzip

    manifest = ROOT / "data" / "inventory" / "extracted-tree.jsonl.gz"
    if not manifest.exists() or not (EXTRACT / "manifest.json").exists():
        return
    missing, mismatch = [], []
    total = 0
    with gzip.open(manifest, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            total += 1
            path = EXTRACT / row["path"]
            if not path.exists():
                missing.append(row["path"])
                continue
            if path.stat().st_size != row["size"]:
                mismatch.append(row["path"])
                continue
            if sha256(path)[:16] != row["sha256"]:
                mismatch.append(row["path"])
    print(f"[quick] 解包核对：{total} 个文件，缺失 {len(missing)}，校验和不符 {len(mismatch)}")
    for path in (missing + mismatch)[:10]:
        print(f"[quick]   {path}")
    if missing and strict:
        die("解包树与工程基准不一致（文件缺失）")
    if missing:
        log("⚠ 解包树与基准有差异；若游戏能正常解包，通常是区域版本不同，可继续")


def cmd_bootstrap(args) -> None:
    started = time.time()
    image = find_iso(args.iso)
    log(f"镜像：{image}（{human(image.stat().st_size)}）")
    digest = sha256(image)
    log(f"SHA-256：{digest}")
    save_state(iso=str(image), iso_sha256=digest)

    ensure_source_cpk(image)
    log(f"data.cpk SHA-256：{sha256(SOURCE_CPK)}")
    ensure_extracted()
    ensure_translations()

    if not args.skip_inventory:
        verify_inventory()
    save_state(bootstrapped_at=time.strftime("%Y-%m-%dT%H:%M:%S"), bootstrap_seconds=round(time.time() - started, 1))
    log(f"bootstrap 完成，用时 {time.time() - started:.1f}s。下一步：python3 scripts/quick/quick.py rebuild")


def overlay_root(explicit: str | None) -> Path | None:
    candidates = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates += [ROOT / "data" / "overlay", ROOT / "overlay"]
    for candidate in candidates:
        if (candidate / "manifest.json").exists() or (candidate / "packages").is_dir():
            return candidate
    return None


def cmd_rebuild(args) -> None:
    started = time.time()
    ensure_source_cpk(Path(args.iso).expanduser() if args.iso else None)
    ensure_extracted()
    ensure_translations()
    build_text_path, build_refs_path = prepare_build_translations()

    overlay = overlay_root(args.overlay)
    if overlay is None:
        log("未找到 overlay/（变更集）。将只重建文本与字库映射相关的包")
    else:
        log(f"应用变更集：{overlay}")
        target = ASSETS / "packages"
        target.mkdir(parents=True, exist_ok=True)
        copied = 0
        for source in sorted((overlay / "packages").rglob("*")):
            if not source.is_file():
                continue
            destination = ASSETS / source.relative_to(overlay)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            copied += 1
        log(f"已同步 {copied} 个文件到 {target}")

    output_cpk = BUILD / "data.cpk"
    build_cmd = [sys.executable, str(PIPELINE / "build_fate_extra.py"),
                 "--translations", str(build_text_path),
                 "--references", str(build_refs_path),
                 "--glyph-map", str(TRANS / "glyph-map.json"),
                 "--extract-root", str(EXTRACT),
                 "--manifest", str(EXTRACT / "manifest.json"),
                 "--source-cpk", str(SOURCE_CPK),
                 "--output-cpk", str(output_cpk)]
    poem = TRANS / "poem-glyph-map.json"
    if poem.exists():
        # 章节卡动画字与正文不是同一套字形别名，必须分开传
        build_cmd += ["--motion-glyph-map", str(poem)]
    run(build_cmd)

    # 固定动作表（話す/調べる/前往…）不在 text.jsonl 里，按 24 槽表单独注入。
    # 补丁脚本产出的是 DAT 覆盖层，不是 CPK；必须再用 revision 把覆盖层压进 CPK。
    # 顺序不能反：先文本、后动作表，否则文本重建会把它覆盖回日文。
    interaction_overlay = BUILD / "interaction-overlay"
    interaction_report = BUILD / "interaction-report.json"
    # 覆盖层原地重写：补丁每次都会扫描全部 field 包，写入的集合是确定的。
    # 这里不清空目录——批量删除既慢又容易被安全策略拦截；改为写完核对文件数。
    interaction_overlay.mkdir(parents=True, exist_ok=True)
    run([sys.executable, str(PIPELINE / "patch_fate_extra_interaction.py"),
         "--source-cpk", str(output_cpk),
         "--manifest", str(EXTRACT / "manifest.json"),
         "--glyph-map", str(TRANS / "glyph-map.json"),
         "--out", str(interaction_overlay),
         "--report", str(interaction_report)])

    produced = sum(1 for path in interaction_overlay.rglob("*") if path.is_file())
    expected = None
    if interaction_report.exists():
        try:
            expected = json.loads(interaction_report.read_text(encoding="utf-8")).get("affected_dat_files")
        except json.JSONDecodeError:
            expected = None
    if expected and produced != expected:
        log(f"注意：动作表覆盖层有 {produced} 个文件，报告记录 {expected} 个；"
            f"多出的可能来自旧版本，可手动清理 {interaction_overlay}")

    final_dir = BUILD / "data.final"
    final_cpk = final_dir / "data.cpk"
    revision_args = [sys.executable, str(PIPELINE / "stage_fate_extra_revision.py"),
                     "--source-cpk", str(output_cpk),
                     "--previous-translations", str(build_text_path),
                     "--translations", str(build_text_path),
                     "--previous-glyph-map", str(TRANS / "glyph-map.json"),
                     "--glyph-map", str(TRANS / "glyph-map.json"),
                     "--references", str(build_refs_path),
                     "--manifest", str(EXTRACT / "manifest.json"),
                     "--overlay", str(interaction_overlay),
                     "--out", str(final_dir)]
    if poem.exists():
        revision_args += ["--poem-glyph-map", str(poem)]
    else:
        revision_args += ["--poem-glyph-map", str(TRANS / "glyph-map.json")]
    run(revision_args)
    output_cpk = final_cpk

    report = {
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source_cpk": str(SOURCE_CPK),
        "source_cpk_sha256": sha256(SOURCE_CPK),
        "text_stage_cpk": str(BUILD / "data.cpk"),
        "interaction_report": str(interaction_report),
        "revision_report": str(final_dir / "build-report.json"),
        "output_cpk": str(output_cpk),
        "output_cpk_bytes": output_cpk.stat().st_size,
        "output_cpk_sha256": sha256(output_cpk),
        "translations_sha256": sha256(build_text_path),
        "main_translation_sha256": sha256(TRANS / "text.jsonl"),
        "build_references_sha256": sha256(build_refs_path),
        "glyph_map_sha256": sha256(TRANS / "glyph-map.json"),
        "overlay": str(overlay) if overlay else None,
    }

    if args.no_embed:
        log("按 --no-embed 跳过 ISO 嵌入")
    else:
        recorded = read_state().get("iso")
        image = Path(args.iso).expanduser() if args.iso else (Path(recorded) if recorded else None)
        if image is None or not image.is_file():
            image = find_iso(None)
        output_iso = Path(args.out).expanduser() if args.out else BUILD / "Fate_Extra_CN.iso"
        if output_iso.resolve() == Path(image).resolve():
            die("输出 ISO 不能覆盖原盘；请换一个 --out")
        run([sys.executable, str(PIPELINE / "embed_fate_extra_cpk.py"),
             "--source-iso", str(image),
             "--cpk", str(output_cpk),
             "--output-iso", str(output_iso),
             "--allow-volume-growth"])
        report["output_iso"] = str(output_iso)
        report["output_iso_bytes"] = output_iso.stat().st_size
        report["output_iso_sha256"] = sha256(output_iso)

    (BUILD / "quick-build-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    save_state(last_rebuild=report["built_at"], last_output_iso=report.get("output_iso"))
    log(f"重建完成，用时 {time.time() - started:.1f}s")
    log(f"报告：{BUILD / 'quick-build-report.json'}")
    if report.get("output_iso"):
        log(f"产物：{report['output_iso']}（{human(report['output_iso_bytes'])}）")


# --------------------------------------------------------------------------- #
# 文本编辑
# --------------------------------------------------------------------------- #

def load_text() -> list[dict]:
    if not (TRANS / "text.jsonl").exists():
        die("还没有工作译文表，先运行 bootstrap")
    return load_jsonl(TRANS / "text.jsonl")


def cmd_text(args) -> None:
    rows = load_text()
    action = args.action

    if action == "list":
        subset = rows
        if args.grep:
            subset = [r for r in subset if args.grep in (r.get("jp") or "") or args.grep in (r.get("zh_cn") or "")]
        for row in subset[: args.limit]:
            print(f"{row['id']}  {row.get('zh_cn','') or '(未译)'}\n    JP: {row.get('jp','')}")
        print(f"--- 共 {len(subset)} 条，显示 {min(len(subset), args.limit)} 条")
        return

    if action == "find":
        query = " ".join(args.query)
        hits = [r for r in rows if query in (r.get("jp") or "") or query in (r.get("zh_cn") or "")]
        if not hits:
            die(f"没有匹配「{query}」的条目")
        for row in hits[: args.limit]:
            print(f"{row['id']}\n  JP: {row.get('jp','')}\n  ZH: {row.get('zh_cn','') or '(未译)'}  refs={row.get('reference_count')}")
        print(f"--- 命中 {len(hits)} 条")
        return

    if action == "set":
        target = next((r for r in rows if r["id"] == args.id), None)
        if target is None and len(args.id) >= 6:
            target = next((r for r in rows if r["id"].startswith(args.id)), None)
        if target is None:
            die(f"找不到 ID {args.id}；用 text find 先定位")
        before = target.get("zh_cn", "")
        target["zh_cn"] = args.zh
        write_jsonl(TRANS / "text.jsonl", rows)
        print(f"{target['id']}\n  旧: {before}\n  新: {args.zh}")
        warn_encoding([args.zh], quiet=False)
        return

    if action == "replace":
        hits = [r for r in rows if (r.get("jp") or "") == args.jp]
        if not hits:
            die("没有完全匹配的原日文；改用 text find 模糊搜索，再用 set --id")
        if len(hits) > 1 and not args.all:
            die(f"有 {len(hits)} 条同名原文，确认要全部替换请加 --all")
        for row in hits:
            row["zh_cn"] = args.zh
        write_jsonl(TRANS / "text.jsonl", rows)
        print(f"已替换 {len(hits)} 条：{args.jp} → {args.zh}")
        warn_encoding([args.zh], quiet=False)
        return

    if action == "check":
        rows_with_text = [r for r in rows if (r.get("zh_cn") or "").strip()]
        print(f"条目 {len(rows)}，已译 {len(rows_with_text)}，未译 {len(rows) - len(rows_with_text)}")
        warn_encoding([r["zh_cn"] for r in rows_with_text], quiet=False)
        long_rows = [r for r in rows_with_text
                     if len(r["zh_cn"]) > max(12, int(len(r.get("jp", "")) * 1.8))]
        print(f"疑似过长（可能撑破排版）：{len(long_rows)} 条")
        for row in long_rows[:10]:
            print(f"  {row['id']}  JP({len(row.get('jp',''))}) → ZH({len(row['zh_cn'])}): {row['zh_cn'][:40]}")
        return

    if action == "diff":
        baseline = {r["id"]: r.get("zh_cn", "") for r in load_jsonl(REPO_TEXT)}
        changed = [(r["id"], baseline.get(r["id"], ""), r.get("zh_cn", "")) for r in rows
                   if baseline.get(r["id"], "") != r.get("zh_cn", "")]
        print(f"相对仓库主表改动 {len(changed)} 条")
        for ident, old, new in changed[: args.limit]:
            print(f"{ident}\n  旧: {old}\n  新: {new}")
        return

    die(f"未知子命令 {action}")


def warn_encoding(texts: list[str], quiet: bool) -> None:
    glyph_map = {}
    glyph_path = TRANS / "glyph-map.json"
    if glyph_path.exists():
        glyph_map = json.loads(glyph_path.read_text(encoding="utf-8"))
    missing = set()
    for text in texts:
        for char in text:
            if char in ("\n", "\r", "\t"):
                continue
            if char in glyph_map:
                continue
            try:
                char.encode("cp932")
            except UnicodeEncodeError:
                missing.add(char)
    if missing:
        print(f"⚠ 有 {len(missing)} 个字既不进 CP932、也不在 glyph-map 里，游戏中会显示空白：")
        print("   " + " ".join(sorted(missing)))
        print("   → 需要先为该字分配别名（见 docs/04-font-pipeline.md 的补字流程），否则不要提交")
    elif not quiet:
        print("编码检查通过：所有字符都能落到字库")


# --------------------------------------------------------------------------- #
# 图片
# --------------------------------------------------------------------------- #

def cmd_image(args) -> None:
    if args.action == "apply":
        config = Path(args.config).expanduser()
        if not config.is_file():
            die(f"找不到配置：{config}")
        destination = ASSETS / "packages" / "pack"
        run([sys.executable, str(PIPELINE / "patch_fate_extra_image_text.py"), str(config),
             "--source", str(EXTRACT / "packages" / "pack"),
             "--out", str(destination),
             "--previews", str(WORK / "previews")])
        log(f"图片已写入 {destination}；跑一次 rebuild 即可生效")
        return

    if args.action == "decode":
        package = EXTRACT / "packages" / args.package
        if not package.exists():
            die(f"找不到包：{package}")
        output = WORK / "previews" / Path(args.package).stem
        run([sys.executable, str(PIPELINE / "fate_extra_texture.py"), str(package),
             "--out", str(output), "--root", str(EXTRACT / "packages"), "--roundtrip"])
        log(f"预览图：{output}")
        return

    if args.action == "list":
        manifest = ROOT / "data" / "overlay" / "manifest.json"
        if not manifest.exists():
            die("没有变更集清单")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        rows = data["files"]
        if args.grep:
            rows = [r for r in rows if args.grep in r["path"]]
        for row in rows[: args.limit]:
            print(f"{human(row['size']):>9}  {row['path']}")
        print(f"--- {len(rows)} 个文件 / {human(sum(r['size'] for r in rows))}")
        return

    die(f"未知子命令 {args.action}")


# --------------------------------------------------------------------------- #
# 状态与体检
# --------------------------------------------------------------------------- #

def cmd_status(args) -> None:
    state = read_state()
    print("== 工作区 ==")
    for label, path in (("ISO", Path(state.get("iso", "")) if state.get("iso") else None),
                        ("data.cpk", SOURCE_CPK),
                        ("解包树", EXTRACT / "manifest.json"),
                        ("译文表", TRANS / "text.jsonl"),
                        ("引用表", TRANS / "refs.jsonl"),
                        ("变更集", ROOT / "overlay" / "manifest.json"),
                        ("产物 ISO", BUILD / "Fate_Extra_CN.iso")):
        if path is None:
            print(f"  {label:<10} —")
        elif path.exists():
            size = path.stat().st_size if path.is_file() else sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
            print(f"  {label:<10} ✓ {human(size):>10}  {path}")
        else:
            print(f"  {label:<10} ✗ 缺失")

    if (TRANS / "text.jsonl").exists():
        rows = load_jsonl(TRANS / "text.jsonl")
        done = sum(1 for r in rows if (r.get("zh_cn") or "").strip())
        print(f"\n== 译文 ==\n  {done:,} / {len(rows):,} 条非空（{done / max(len(rows), 1) * 100:.2f}%）")

    if state.get("last_rebuild"):
        report = BUILD / "quick-build-report.json"
        print(f"\n== 上次重建 ==\n  {state['last_rebuild']}")
        if report.exists():
            data = json.loads(report.read_text(encoding="utf-8"))
            print(f"  CPK {human(data.get('output_cpk_bytes', 0))}  sha256={data.get('output_cpk_sha256','')[:16]}…")
            if data.get("output_iso"):
                print(f"  ISO {human(data.get('output_iso_bytes', 0))}  sha256={data.get('output_iso_sha256','')[:16]}…")


def cmd_verify(args) -> None:
    ok = True
    report = BUILD / "quick-build-report.json"
    if report.exists():
        data = json.loads(report.read_text(encoding="utf-8"))
        cpk = Path(data["output_cpk"])
        if cpk.exists():
            actual = sha256(cpk)
            same = actual == data["output_cpk_sha256"]
            ok &= same
            print(f"{'✓' if same else '✗'} 构建 CPK 校验和 {'一致' if same else '不一致'}")
        iso = data.get("output_iso")
        if iso and Path(iso).exists():
            actual = sha256(Path(iso))
            same = actual == data.get("output_iso_sha256")
            ok &= same
            print(f"{'✓' if same else '✗'} 产物 ISO 校验和 {'一致' if same else '不一致'}（{human(Path(iso).stat().st_size)}）")
    else:
        print("✗ 还没有构建报告，先运行 rebuild")

    validator = ROOT / "scripts" / "validate_repo.py"
    if validator.exists():
        result = subprocess.run([sys.executable, str(validator)], cwd=str(ROOT))
        ok &= result.returncode == 0

    print("结论：" + ("全部通过" if ok else "有问题，见上"))
    raise SystemExit(0 if ok else 1)


def cmd_overlay(args) -> None:
    root = overlay_root(args.overlay) or (ROOT / "data" / "overlay")
    manifest_path = root / "manifest.json"
    if args.action == "sync":
        rows = []
        for path in sorted((root / "packages").rglob("*")):
            if not path.is_file() or path.name == ".DS_Store":
                continue
            data = path.read_bytes()
            rows.append({"path": path.relative_to(root).as_posix(),
                         "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        manifest.update({"file_count": len(rows),
                         "total_bytes": sum(r["size"] for r in rows),
                         "files": rows})
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"清单已更新：{len(rows)} 个文件 / {human(manifest['total_bytes'])}")
        return

    if args.action == "verify":
        if not manifest_path.exists():
            die("没有 manifest.json，先跑 overlay sync")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        missing, mismatch = [], []
        for row in manifest["files"]:
            path = root / row["path"]
            if not path.exists():
                missing.append(row["path"])
            elif sha256(path) != row["sha256"]:
                mismatch.append(row["path"])
        print(f"文件 {manifest['file_count']}，缺失 {len(missing)}，校验和不符 {len(mismatch)}")
        for path in (missing + mismatch)[:20]:
            print("  " + path)
        raise SystemExit(0 if not (missing or mismatch) else 1)
    die(f"未知子命令 {args.action}")


# --------------------------------------------------------------------------- #

def main() -> None:
    parser = argparse.ArgumentParser(description="Fate/Extra CN 一键重建与快速编辑")
    sub = parser.add_subparsers(dest="command", required=True)

    p_boot = sub.add_parser("bootstrap", help="从自备 ISO 解出 data.cpk 并展开工作区")
    p_boot.add_argument("--iso", help="日版 ISO 路径；缺省读 iso/*.iso")
    p_boot.add_argument("--skip-inventory", action="store_true", help="跳过解包清单核对")
    p_boot.set_defaults(func=cmd_bootstrap)

    p_build = sub.add_parser("rebuild", help="应用变更集并重建 CPK/ISO")
    p_build.add_argument("--iso", help="源 ISO（默认沿用 bootstrap 记录）")
    p_build.add_argument("--out", help="输出 ISO 路径")
    p_build.add_argument("--overlay", help="变更集目录（默认 overlay/）")
    p_build.add_argument("--no-embed", action="store_true", help="只产出 data.cpk")
    p_build.set_defaults(func=cmd_rebuild)

    p_text = sub.add_parser("text", help="查看/修改译文")
    text_sub = p_text.add_subparsers(dest="action", required=True)
    p = text_sub.add_parser("list"); p.add_argument("--grep"); p.add_argument("--limit", type=int, default=30); p.set_defaults(func=cmd_text)
    p = text_sub.add_parser("find"); p.add_argument("query", nargs="+"); p.add_argument("--limit", type=int, default=20); p.set_defaults(func=cmd_text)
    p = text_sub.add_parser("set"); p.add_argument("--id", required=True); p.add_argument("--zh", required=True); p.set_defaults(func=cmd_text)
    p = text_sub.add_parser("replace"); p.add_argument("--jp", required=True); p.add_argument("--zh", required=True); p.add_argument("--all", action="store_true"); p.set_defaults(func=cmd_text)
    p = text_sub.add_parser("check"); p.set_defaults(func=cmd_text)
    p = text_sub.add_parser("diff"); p.add_argument("--limit", type=int, default=20); p.set_defaults(func=cmd_text)

    p_image = sub.add_parser("image", help="图片预览与回写")
    image_sub = p_image.add_subparsers(dest="action", required=True)
    p = image_sub.add_parser("apply"); p.add_argument("--config", required=True); p.set_defaults(func=cmd_image)
    p = image_sub.add_parser("decode"); p.add_argument("--package", required=True); p.set_defaults(func=cmd_image)
    p = image_sub.add_parser("list"); p.add_argument("--grep"); p.add_argument("--limit", type=int, default=30); p.set_defaults(func=cmd_image)

    p_overlay = sub.add_parser("overlay", help="变更集清单维护")
    overlay_sub = p_overlay.add_subparsers(dest="action", required=True)
    p = overlay_sub.add_parser("sync"); p.add_argument("--overlay"); p.set_defaults(func=cmd_overlay)
    p = overlay_sub.add_parser("verify"); p.add_argument("--overlay"); p.set_defaults(func=cmd_overlay)

    sub.add_parser("status", help="工作区状态").set_defaults(func=cmd_status)
    p_inv = sub.add_parser("inventory", help="解包清单核对")
    inv_sub = p_inv.add_subparsers(dest="action", required=True)
    p = inv_sub.add_parser("verify"); p.set_defaults(func=lambda a: verify_inventory(strict=True))
    sub.add_parser("verify", help="校验产物").set_defaults(func=cmd_verify)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
