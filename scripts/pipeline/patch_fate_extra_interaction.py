#!/usr/bin/env python3
"""Translate the fixed field action table from a working CPK into DAT overlays.

Only the exact common 24-slot action table, preceded by its FF sentinel, is
changed. Existing DAT sizes, offsets, pointer values, scripts and other text are
preserved. Source package data always comes from the supplied CPK.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

from build_fate_extra import encode_game_text
from extract_fate_extra import decode_cmp, parse_cpk, read_cpk_entry
from stage_fate_extra_revision import Package


LABELS = [
    ("話す", "对话"), ("調べる", "调查"),
    ("校舎　B1Fへ", "前往地下1层"),
    ("校舎　1F廊下へ", "前往1层走廊"),
    ("校舎　2F廊下へ", "前往2层走廊"),
    ("校舎　3F廊下へ", "前往3层走廊"),
    ("校舎　屋上へ", "前往校舍屋顶"),
    ("花壇へ", "去花坛"), ("教会へ", "去教会"),
    ("保健室へ", "前往保健室"), ("2-A教室へ", "去2-A教室"),
    ("図書室へ", "前往图书室"), ("校庭へ", "去操场"),
    ("弓道場へ", "前往弓道场"),
    ("（未定）へ", "去（未定）"), ("（未定）へ", "去（未定）"),
    ("（未定）へ", "去（未定）"), ("正門前へ", "前往正门前"),
    ("視聴覚室へ", "前往视听室"),
    ("アリーナへ", "前往竞技场"), ("アリーナへ", "前往竞技场"),
    ("倉庫へ", "去仓库"), ("アリーナへ", "前往竞技场"),
    ("？？？？", "？？？？"),
]
SENTINEL = b"\xff" * 16


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tables(mapping: dict[str, str]) -> tuple[bytes, bytes, list[dict]]:
    before, after, records = bytearray(), bytearray(), []
    for index, (jp, zh) in enumerate(LABELS):
        source = jp.encode("cp932")
        capacity = (len(source) + 4) & ~3
        wanted = source if jp == zh else encode_game_text(zh, mapping)
        if len(wanted) >= capacity:
            raise ValueError(f"label does not fit its original slot: {zh}")
        records.append({"index": index, "jp": jp, "zh_cn": zh,
                        "relative_offset": len(before), "capacity": capacity,
                        "before_hex": source.hex(), "after_hex": wanted.hex()})
        before.extend(source.ljust(capacity, b"\0"))
        after.extend(wanted.ljust(capacity, b"\0"))
    if len(before) != len(after) or len(before) != 0x118:
        raise ValueError("common action table changed length")
    return bytes(before), bytes(after), records


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-cpk", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, default=Path("work/extracted/manifest.json"))
    ap.add_argument("--glyph-map", type=Path, default=Path("work/translation/glyph-map.json"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--audit-only", action="store_true")
    args = ap.parse_args()
    mapping = json.loads(args.glyph_map.read_text(encoding="utf8"))
    before, after, label_records = tables(mapping)
    manifest = json.loads(args.manifest.read_text(encoding="utf8"))
    relevant = {p["path"]: p for p in manifest["packages"]
                if any(e["path"].startswith("field/") and e["path"].endswith(".dat")
                       for e in p["entries"])}
    _, rows = parse_cpk(args.source_cpk)
    rows_by_path = defaultdict(list)
    for row in rows:
        rows_by_path[row["DirName"] + "/" + row["FileName"]].append(row)
    records, no_table = [], []
    package_count = cpk_alias_count = 0
    for number, (name, meta) in enumerate(sorted(relevant.items()), 1):
        aliases = rows_by_path[name]
        # Duplicate CPK rows must resolve to the same exact payload.
        raw = read_cpk_entry(args.source_cpk, aliases[0])
        for alias in aliases[1:]:
            if read_cpk_entry(args.source_cpk, alias) != raw:
                raise ValueError(f"CPK aliases disagree: {name}")
        pak = Package(decode_cmp(raw) if raw.startswith(b"IECP") else raw, meta)
        touched = False
        for member in pak.by_path:
            if not (member.startswith("field/") and member.endswith(".dat")):
                continue
            data = pak.get(member)
            source_needle, output_needle = SENTINEL + before, SENTINEL + after
            hits, already = data.count(source_needle), data.count(output_needle)
            # The adjacent pair must never be silently skipped if its full
            # table or sentinel differs; such a variant requires review.
            raw_pair = before[:16]
            if data.count(raw_pair) != hits:
                raise ValueError(f"unreviewed action table variant: {name}/{member}")
            if hits + already == 0:
                no_table.append(f"{name}/{member}")
                continue
            if hits + already != 1:
                raise ValueError(f"unexpected action table count: {name}/{member}")
            if args.audit_only and hits:
                raise ValueError(f"untranslated field action table: {name}/{member}")
            offset = data.find(source_needle if hits else output_needle) + len(SENTINEL)
            updated = data[:offset] + after + data[offset + len(after):]
            if len(updated) != len(data):
                raise ValueError("DAT length changed")
            if updated[:offset] != data[:offset] or updated[offset + 0x118:] != data[offset + 0x118:]:
                raise ValueError("bytes outside the action table changed")
            if hits and not args.audit_only:
                dest = args.out / "packages" / Path(name).with_suffix("") / member
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(updated)
                reread = dest.read_bytes()
                if reread != updated or reread[offset:offset + 0x118] != after:
                    raise ValueError("overlay readback mismatch")
            records.append({"package": name, "member": member,
                            "table_offset": offset, "size": len(data),
                            "before_sha256": digest(data), "after_sha256": digest(updated),
                            "cpk_alias_rows": len(aliases), "already_chinese": bool(already),
                            "outside_table_identical": True})
            touched = True
        if touched:
            package_count += 1
            cpk_alias_count += len(aliases)
        if number % 100 == 0:
            print(f"Read {number}/{len(relevant)} field packages", flush=True)
    report = {"source_cpk": str(args.source_cpk), "glyph_map": str(args.glyph_map),
              "glyph_map_sha256": digest(args.glyph_map.read_bytes()),
              "mode": "audit" if args.audit_only else "overlay",
              "scanned_packages": len(relevant), "affected_packages": package_count,
              "affected_cpk_rows_including_aliases": cpk_alias_count,
              "affected_dat_files": len(records), "labels_per_table": len(LABELS),
              "changed_labels_per_table": sum(j != z for j, z in LABELS),
              "table_size": len(before), "labels": label_records,
              "records": records, "field_dat_without_action_table": no_table,
              "all_output_slots_within_original_capacity": True,
              "all_dat_lengths_and_outside_table_bytes_preserved": True}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps({k: report[k] for k in ("mode", "scanned_packages", "affected_packages",
          "affected_cpk_rows_including_aliases", "affected_dat_files", "labels_per_table")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
