#!/usr/bin/env python3
"""Assemble the reviewed Fate/Extra text table without changing its source."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REVIEW = ROOT / "work/translation/review-20261019"

PATCHES = [
    REVIEW / "merged-initial-fixes.jsonl",
    REVIEW / "context-opening-fixes.jsonl",
    REVIEW / "context-extra-fixes.jsonl",
    REVIEW / "context-lane-1-fixes.jsonl",
    REVIEW / "context-lane-2-fixes.jsonl",
    REVIEW / "lane2-noise-fixes.json",
    REVIEW / "context-lane-3-fixes.jsonl",
    REVIEW / "context-lane-4-fixes.jsonl",
    REVIEW / "control-restoration-fixes.jsonl",
    REVIEW / "root-manual-fixes.jsonl",
]
RUBY_PATH = REVIEW / "ordinary-name-ruby-whitelist.jsonl"
ALLOWED_RUBY_CATEGORIES = {
    "person", "place", "mythical_place", "deity", "noble_phantasm",
    "sword_deity", "mythical_beast_name", "servant_true_name",
    "fixed_epithet", "system_name",
}
RUBY_RE = re.compile(r"#RUBS.*?#RUBE(.*?)#REND", re.S)
CONTROL_RE = re.compile(r"#(?:C\d{9}|CDEF|FAMILY|GIVEN|SVT\[[^]]*\](?:\[[^]]*\])?(?:\[[^]]*\])?#|SP\d{2})")


def read_rows(path: Path) -> list[dict]:
    if path.suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            value = value.get("fixes", [])
        if not isinstance(value, list):
            raise ValueError(f"unsupported patch JSON: {path}")
        return value
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def plain_anchor(anchor: str) -> str:
    return CONTROL_RE.sub("", anchor)


def apply_reading(text: str, upper: str, anchor: str) -> tuple[str, str]:
    base = plain_anchor(anchor)
    if not base or not upper:
        return text, "empty-anchor"
    # Don't place an ordinary reading inside an existing semantic ruby.
    # The expression captures the Chinese ruby body (RUBE..REND) as group 1.
    # Don't place an ordinary reading inside an existing semantic ruby.
    already = [m for m in RUBY_RE.finditer(text) if base in m.group(1)]
    if already:
        return text, "already-ruby"
    # A reading is attached only to an unannotated, literal name occurrence.
    # Leave repeated or ambiguous mentions for a deliberate per-line choice.
    ruby_ranges = [m.span() for m in RUBY_RE.finditer(text)]
    hits = [m.start() for m in re.finditer(re.escape(base), text)]
    hits = [p for p in hits if not any(a <= p < b for a, b in ruby_ranges)]
    if len(hits) != 1:
        return text, "missing-or-ambiguous"
    start = hits[0]
    end = start + len(base)
    # The original color control sits outside the ruby pair in the game data.
    return text[:start] + f"#RUBS{upper}#RUBE{base}#REND" + text[end:], "added"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, default=ROOT / "work/translation/text.jsonl")
    ap.add_argument("--out", type=Path, default=REVIEW / "text.v15-reviewed.pre-layout.jsonl")
    ap.add_argument("--report", type=Path, default=REVIEW / "v15-assembly-report.json")
    args = ap.parse_args()

    rows = [json.loads(line) for line in args.source.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_id = {row["id"]: row for row in rows}
    if len(by_id) != len(rows):
        raise ValueError("duplicate translation IDs in source")

    changes: list[dict] = []
    missing_patch_ids: dict[str, list[str]] = {}
    patch_conflicts: list[dict] = []
    last_patch_by_id: dict[str, tuple[str, str]] = {}
    for path in PATCHES:
        if not path.exists():
            continue
        patch_rows = read_rows(path)
        for fix in patch_rows:
            if not isinstance(fix, dict) or "id" not in fix or "zh_cn" not in fix:
                continue
            row = by_id.get(fix["id"])
            if row is None:
                missing_patch_ids.setdefault(path.name, []).append(fix["id"])
                continue
            previous = row.get("zh_cn", "")
            new = fix["zh_cn"]
            if previous != new:
                if fix["id"] in last_patch_by_id and last_patch_by_id[fix["id"]][0] != new:
                    patch_conflicts.append({
                        "id": fix["id"],
                        "earlier_patch": last_patch_by_id[fix["id"]][1],
                        "later_patch": path.name,
                        "earlier_text": last_patch_by_id[fix["id"]][0],
                        "later_text": new,
                    })
                changes.append({"id": fix["id"], "patch": path.name, "from": previous, "to": new})
                row["zh_cn"] = new
            last_patch_by_id[fix["id"]] = (new, path.name)

    ruby_counts = Counter()
    skipped_ruby: list[dict] = []
    for group in read_rows(RUBY_PATH):
        if group.get("category") not in ALLOWED_RUBY_CATEGORIES:
            continue
        for occ in group.get("occurrences", []):
            row = by_id.get(occ.get("id"))
            if row is None:
                skipped_ruby.append({"id": occ.get("id"), "reason": "missing-id"})
                continue
            updated, result = apply_reading(row.get("zh_cn", ""), group["jp_upper"], occ["zh_anchor"])
            if result == "added":
                row["zh_cn"] = updated
                ruby_counts["added"] += 1
            else:
                ruby_counts[result] += 1
                skipped_ruby.append({"id": occ["id"], "jp_upper": group["jp_upper"], "anchor": occ["zh_anchor"], "reason": result})

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")
    report = {
        "source": str(args.source),
        "output": str(args.out),
        "translation_rows": len(rows),
        "patches": {p.name: len(read_rows(p)) for p in PATCHES if p.exists()},
        "patch_changes": len(changes),
        "patch_conflicts": patch_conflicts,
        "missing_patch_ids": missing_patch_ids,
        "ordinary_ruby": dict(ruby_counts),
        "ordinary_ruby_skips": skipped_ruby,
        "final_overrides": ["root-manual-fixes.jsonl is applied after all review ledgers"],
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "ordinary_ruby_skips"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
