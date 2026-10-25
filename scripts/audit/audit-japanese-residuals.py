#!/usr/bin/env python3
"""Audit player-visible Chinese text for remaining Japanese kana and missing character subtitles."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


KANA_RE = re.compile(r"[ぁ-ゖァ-ヺー]")
RUBY_RE = re.compile(r"#RUBS.*?#RUBE(.*?)#REND", re.S)
IDENTICAL_RUBY_RE = re.compile(r"#RUBS(.*?)#RUBE(.*?)#REND", re.S)
SVT_RE = re.compile(r"#SVT((?:\[[^\]]*\]){3})#")
CHOICE_RE = re.compile(r"#((?:\[[^\]]*\]){2})#")
CONTROL_RE = re.compile(r"#(?:C\d{9}|CDEF|SP\d{2}|FAMILY|GIVEN)")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def visible_text(text: str) -> tuple[str, list[str]]:
    options: list[str] = []

    def collect_svt(match: re.Match[str]) -> str:
        options.extend(re.findall(r"\[([^\]]*)\]", match.group(1)))
        return ""

    def collect_choice(match: re.Match[str]) -> str:
        options.extend(re.findall(r"\[([^\]]*)\]", match.group(1)))
        return ""

    text = RUBY_RE.sub(r"\1", text)
    text = SVT_RE.sub(collect_svt, text)
    text = CHOICE_RE.sub(collect_choice, text)
    text = CONTROL_RE.sub("", text)
    return text, options


def scan_text(text: str, source: str, residuals: list[dict]) -> None:
    visible, options = visible_text(text)
    if KANA_RE.search(visible):
        residuals.append({"source": source, "kind": "visible-kana", "text": visible})
    for option in options:
        if KANA_RE.search(option):
            residuals.append({"source": source, "kind": "runtime-branch-kana", "text": option})


def collect_ui_strings(value: object, source: str, strings: list[tuple[str, str]]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"text", "target", "zh_cn", "translation"} and isinstance(child, str):
                strings.append((f"{source}:{key}", child))
            else:
                collect_ui_strings(child, source, strings)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            collect_ui_strings(child, f"{source}[{index}]", strings)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--translations", type=Path, default=Path("data/translation/text.jsonl"), help="canonical main translation table")
    parser.add_argument("--main-fixes", type=Path, default=Path("data/review/remaining-japanese-fixes.jsonl"), help="review fixes to apply during the audit")
    parser.add_argument("--review-ledgers", action="store_true", default=True,
                        help="apply the complete ordered review ledger before scanning")
    parser.add_argument("--servant-fixes", type=Path, default=Path("data/review/servant-dialogue-fixes.jsonl"), help="translated character-package dialogue ledger")
    parser.add_argument("--servant-references", type=Path, default=Path("data/evidence/servant-dialogue-references.jsonl"), help="source strings and DAT pointer evidence")
    parser.add_argument("--ui-config", type=Path, action="append", help="UI translation configuration to scan; may be repeated")
    parser.add_argument("--report", type=Path, default=Path("work/build/japanese-residual-audit.json"), help="JSON report output")
    args = parser.parse_args()

    main_rows = read_jsonl(args.translations)
    main_by_id = {row["id"]: row for row in main_rows}
    if len(main_by_id) != len(main_rows):
        raise ValueError("duplicate IDs in main translation table")
    ledger_names = [
        "merged-initial-fixes.jsonl", "context-opening-fixes.jsonl",
        "context-extra-fixes.jsonl", "context-lane-1-fixes.jsonl",
        "context-lane-2-fixes.jsonl", "lane2-noise-fixes.json",
        "context-lane-3-fixes.jsonl", "context-lane-4-fixes.jsonl",
        "control-restoration-fixes.jsonl", "root-manual-fixes.jsonl",
        "ruby-fixes.jsonl", "consistency-fixes.jsonl",
        "remaining-japanese-fixes.jsonl",
    ] if args.review_ledgers else []
    applied_by_ledger = {}
    for name in ledger_names:
        path = Path("data/review") / name
        if not path.is_file():
            continue
        if path.suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            fixes = payload.get("fixes", []) if isinstance(payload, dict) else payload
        else:
            fixes = read_jsonl(path)
        for fix in fixes:
            if fix["id"] not in main_by_id:
                raise ValueError(f"main fix ID not found: {name}: {fix['id']}")
            main_by_id[fix["id"]]["zh_cn"] = fix["zh_cn"]
        applied_by_ledger[name] = len(fixes)
    if args.main_fixes.exists():
        for fix in read_jsonl(args.main_fixes):
            if fix["id"] not in main_by_id:
                raise ValueError(f"main fix ID not found: {fix['id']}")
            main_by_id[fix["id"]]["zh_cn"] = fix["zh_cn"]
        applied_by_ledger[args.main_fixes.name] = len(read_jsonl(args.main_fixes))

    identical_ruby_pairs = 0
    for row in main_rows:
        def strip_identical(match: re.Match[str]) -> str:
            nonlocal identical_ruby_pairs
            upper, base = match.groups()
            if upper == base:
                identical_ruby_pairs += 1
                return base
            return match.group(0)
        row["zh_cn"] = IDENTICAL_RUBY_RE.sub(strip_identical, row.get("zh_cn", ""))

    residuals: list[dict] = []
    for row in main_rows:
        scan_text(row.get("zh_cn", ""), f"main:{row['id']}", residuals)

    servant_fixes = read_jsonl(args.servant_fixes)
    servant_refs = read_jsonl(args.servant_references)
    fix_by_id = {row["id"]: row for row in servant_fixes}
    ref_by_id = {row["id"]: row for row in servant_refs}
    if len(fix_by_id) != len(servant_fixes) or fix_by_id.keys() != ref_by_id.keys():
        raise ValueError("servant dialogue fix IDs do not match unique source-reference IDs")
    for fix in servant_fixes:
        if not fix.get("zh_cn", "").strip():
            residuals.append({"source": f"servant:{fix['id']}", "kind": "blank-translation", "text": ""})
        if fix["zh_cn"] == ref_by_id[fix["id"]]["jp"]:
            residuals.append({"source": f"servant:{fix['id']}", "kind": "identical-to-japanese-source", "text": fix["zh_cn"]})
        scan_text(fix["zh_cn"], f"servant:{ref_by_id[fix['id']]['file']}@0x{ref_by_id[fix['id']]['text_offset']:x}", residuals)

    ui_paths = args.ui_config or [
        Path("data/evidence/ui/ui-text-patches.json"),
        Path("data/evidence/ui/image-text-patches.json"),
        Path("data/evidence/ui/tutorial-text-patches.json"),
        Path("data/evidence/ui/fixed-ui-text-patches.json"),
    ]
    ui_strings: list[tuple[str, str]] = []
    for path in ui_paths:
        if path.exists():
            collect_ui_strings(json.loads(path.read_text(encoding="utf-8")), path.as_posix(), ui_strings)
    for source, text in ui_strings:
        scan_text(text, source, residuals)

    inputs = [args.translations, args.main_fixes, args.servant_fixes, args.servant_references]
    inputs.extend(Path("data/review") / name for name in ledger_names if (Path("data/review") / name).exists())
    inputs.extend(path for path in ui_paths if path.exists())
    report = {
        "main_translation_rows": len(main_rows),
        "main_review_fixes": applied_by_ledger,
        "applied_by_ledger": applied_by_ledger,
        "identical_ruby_pairs_removed_for_audit": identical_ruby_pairs,
        "servant_dialogue_rows": len(servant_fixes),
        "servant_dialogue_pointer_references": sum(ref.get("reference_count", 0) for ref in servant_refs),
        "ui_translation_strings_scanned": len(ui_strings),
        "residual_count": len(residuals),
        "residuals": residuals,
        "inputs_sha256": {path.as_posix(): sha256(path) for path in inputs},
        "scope_note": "Scans displayed strings and runtime branch alternatives for Japanese kana; Japanese ruby readings in #RUBS are intentionally excluded, while Chinese base text is scanned.",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"residuals", "inputs_sha256"}}, ensure_ascii=False))
    if residuals:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
