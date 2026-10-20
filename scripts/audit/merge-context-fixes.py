#!/usr/bin/env python3
"""Merge review fix files into a translation master table.

The context-review workflow never edits the master table in place. Each review
lane appends absolute ``zh_cn`` values to ``context-lane-N-fixes.jsonl``; this
script is the single place that turns those records into a buildable table.

Rules:

* ``--base`` is the newest consolidated table (the lane baseline), not the
  oldest master. Lane fixes are computed against that baseline.
* Sources are applied in the order given, so a later source overrides an
  earlier one for the same id.
* An id that is missing from the base is a hard error: it means the fix file
  was produced against a different inventory.
* Rows whose value equals the base are counted as no-ops, not failures.

Usage:

    python3 scripts/audit/merge-context-fixes.py \
        --base work/translation/review-20261019/text.context-ruby.jsonl \
        --source work/translation/review-20261019/context-extra-fixes.jsonl \
        --source work/translation/review-20261019/context-lane-1-fixes.jsonl \
        --out work/translation/text.jsonl \
        --report work/build/context-merge-report.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="审校基线表（含已有修复）")
    parser.add_argument("--source", action="append", default=[], help="修复文件，可重复；后出现者覆盖先出现者")
    parser.add_argument("--out", required=True, help="合并后的主表")
    parser.add_argument("--report", help="合并报告 JSON")
    args = parser.parse_args()

    base_path = Path(args.base).expanduser()
    base_rows = load_jsonl(base_path)
    order = [row["id"] for row in base_rows]
    table = {row["id"]: row for row in base_rows}

    applied_total = 0
    touched: set[str] = set()
    report = {
        "base": str(base_path),
        "base_sha256": sha256(base_path),
        "base_rows": len(base_rows),
        "sources": [],
    }

    for source in args.source:
        path = Path(source).expanduser()
        rows = load_jsonl(path)
        missing = [row["id"] for row in rows if row["id"] not in table]
        if missing:
            raise SystemExit(f"{path.name}: {len(missing)} 个 id 不在基线中，例如 {missing[:3]}")
        changed = 0
        conflicts = []
        for row in rows:
            current = table[row["id"]].get("zh_cn") or ""
            if current != row["zh_cn"]:
                if row["id"] in touched:
                    conflicts.append(row["id"])
                table[row["id"]]["zh_cn"] = row["zh_cn"]
                changed += 1
            touched.add(row["id"])
        applied_total += changed
        report["sources"].append({
            "path": str(path),
            "sha256": sha256(path),
            "rows": len(rows),
            "changed": changed,
            "overwrote_previous": len(conflicts),
        })
        print(f"{path.name}: {len(rows)} 条，改动 {changed} 条，覆盖前序 {len(conflicts)} 条")

    out_path = Path(args.out).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for entry_id in order:
            handle.write(json.dumps(table[entry_id], ensure_ascii=False) + "\n")

    translated = sum(1 for row in table.values() if (row.get("zh_cn") or "").strip())
    report.update({
        "out": str(out_path),
        "out_sha256": sha256(out_path),
        "out_rows": len(table),
        "translated": translated,
        "total_changes": applied_total,
    })
    print(f"合计改动 {applied_total} 条；输出 {out_path}（{len(table)} 行，{translated} 条非空）")
    if args.report:
        report_path = Path(args.report).expanduser()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"报告：{report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
