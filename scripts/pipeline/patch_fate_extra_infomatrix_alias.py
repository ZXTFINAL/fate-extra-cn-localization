#!/usr/bin/env python3
"""Normalize Drake's alias in the static Rider information-matrix text."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build_fate_extra import encode_game_text


DEFAULT_ASSET = Path(
    "data/overlay/packages/pack/PRELOAD/interface/infomatrixex/infomatrix_eld_d_01.bin"
)
DEFAULT_GLYPH_MAP = Path("data/translation/glyph-map.json")
DEFAULT_REPORT = Path("data/evidence/build/v1.2-infomatrix-alias-fix.json")
RECORD_OFFSET = 0x330
RECORD_SIZE = 0x80
OLD_TEXT = "『#RUBSEl Drago#RUBE恶魔#REND』"
NEW_TEXT = "『#RUBSEI Drago#RUBE大航海的恶魔#REND』"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", type=Path, default=DEFAULT_ASSET)
    parser.add_argument("--glyph-map", type=Path, default=DEFAULT_GLYPH_MAP)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    source = args.asset.read_bytes()
    if len(source) != 960:
        raise ValueError(f"unexpected information-matrix asset size: {len(source)}")
    if RECORD_OFFSET + RECORD_SIZE > len(source):
        raise ValueError("information-matrix record lies outside the asset")

    glyph_map = json.loads(args.glyph_map.read_text(encoding="utf-8"))
    old_bytes = encode_game_text(OLD_TEXT, glyph_map)
    new_bytes = encode_game_text(NEW_TEXT, glyph_map)
    record = source[RECORD_OFFSET:RECORD_OFFSET + RECORD_SIZE]
    old_count = record.count(old_bytes)
    new_count = record.count(new_bytes)
    if old_count == 1 and new_count == 0:
        relative = record.index(old_bytes)
        trailing = record[relative + len(old_bytes):]
        if any(trailing):
            raise ValueError("unexpected non-padding data after the source alias")
        if len(new_bytes) >= RECORD_SIZE - relative:
            raise ValueError("translated alias exceeds its fixed information-matrix record")
        updated_record = record[:relative] + new_bytes + b"\0" * (
            RECORD_SIZE - relative - len(new_bytes)
        )
        updated = source[:RECORD_OFFSET] + updated_record + source[RECORD_OFFSET + RECORD_SIZE:]
        status = "patched"
    elif old_count == 0 and new_count == 1:
        updated = source
        status = "already-patched"
    else:
        raise ValueError(
            f"expected exactly one old or new alias in the record; old={old_count}, new={new_count}"
        )

    if len(updated) != len(source):
        raise ValueError("asset size changed")
    if updated[:RECORD_OFFSET] != source[:RECORD_OFFSET] or updated[RECORD_OFFSET + RECORD_SIZE:] != source[RECORD_OFFSET + RECORD_SIZE:]:
        raise ValueError("bytes outside the reviewed record changed")
    if status == "patched":
        args.asset.write_bytes(updated)
        if args.asset.read_bytes() != updated:
            raise ValueError("asset readback mismatch")

    report = {
        "asset": str(args.asset),
        "status": status,
        "record_offset": f"0x{RECORD_OFFSET:x}",
        "record_capacity_bytes": RECORD_SIZE,
        "source_text": OLD_TEXT,
        "translation": NEW_TEXT,
        "source_bytes": len(old_bytes),
        "translation_bytes": len(new_bytes),
        "asset_size_preserved": len(updated) == len(source),
        "bytes_outside_record_preserved": True,
        "sha256_before": sha256(source),
        "sha256_after": sha256(updated),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
