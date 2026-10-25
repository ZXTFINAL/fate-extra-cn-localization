#!/usr/bin/env python3
"""Translate a missed fixed help string in Fate/EXTRA's PRELOAD package.

The source table uses a fixed 32-byte SJIS text slot. The patch validates its
header and original bytes, encodes the Chinese through the project's glyph
map, and preserves the file size and all bytes outside that slot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

from build_fate_extra import encode_game_text


SOURCE_TEXT = "メインメニューから確認できます"
TARGET_TEXT = "可在主菜单中查看。"
SLOT_OFFSET = 8
SLOT_SIZE = 32


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", type=Path, help="Extracted PRELOAD/interface/infomatpop/msg.bin")
    ap.add_argument("--glyph-map", type=Path, required=True, help="Project glyph-map.json")
    ap.add_argument("--out", type=Path, required=True, help="Patched msg.bin output")
    ap.add_argument("--report", type=Path, required=True, help="JSON audit report")
    args = ap.parse_args()

    original = args.source.read_bytes()
    if len(original) != 48:
        raise ValueError(f"unexpected msg.bin size: {len(original)} != 48")
    record, capacity = struct.unpack_from("<II", original)
    if record != 0 or capacity != SLOT_SIZE:
        raise ValueError(f"unexpected message header: record={record}, slot={capacity}")
    raw_slot = original[SLOT_OFFSET:SLOT_OFFSET + SLOT_SIZE]
    terminator = raw_slot.find(b"\0")
    if terminator < 0 or raw_slot[terminator:] != b"\0" * (SLOT_SIZE - terminator):
        raise ValueError("message slot has invalid termination or nonzero padding")
    actual = raw_slot[:terminator].decode("cp932")
    if actual != SOURCE_TEXT:
        raise ValueError(f"source text mismatch: {actual!r}")

    glyph_map = json.loads(args.glyph_map.read_text(encoding="utf-8"))
    encoded = encode_game_text(TARGET_TEXT, glyph_map)
    if len(encoded) + 1 > SLOT_SIZE:
        raise ValueError(f"translated string exceeds slot: {len(encoded)} + terminator > {SLOT_SIZE}")
    output = bytearray(original)
    output[SLOT_OFFSET:SLOT_OFFSET + SLOT_SIZE] = encoded + b"\0" + b"\0" * (SLOT_SIZE - len(encoded) - 1)
    final = bytes(output)
    if len(final) != len(original):
        raise ValueError("msg.bin length changed")
    if final[:SLOT_OFFSET] != original[:SLOT_OFFSET] or final[SLOT_OFFSET + SLOT_SIZE:] != original[SLOT_OFFSET + SLOT_SIZE:]:
        raise ValueError("bytes outside the text slot changed")
    decoded = final[SLOT_OFFSET:SLOT_OFFSET + SLOT_SIZE].split(b"\0", 1)[0].decode("cp932")
    reverse_map = {alias: char for char, alias in glyph_map.items()}
    readback = "".join(reverse_map.get(char, char) for char in decoded)
    if readback != TARGET_TEXT:
        raise ValueError(f"Chinese alias readback mismatch: {readback!r}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(final)
    report = {
        "resource": "pack/PRELOAD.pak/interface/infomatpop/msg.bin",
        "source_sha256": sha256(original),
        "output_sha256": sha256(final),
        "bytes_before": len(original),
        "bytes_after": len(final),
        "text_slot_offset": SLOT_OFFSET,
        "text_slot_capacity": SLOT_SIZE,
        "jp": SOURCE_TEXT,
        "zh_cn": TARGET_TEXT,
        "encoded_hex": encoded.hex(),
        "readback": readback,
        "bytes_outside_text_slot_unchanged": True,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"jp", "zh_cn"}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
