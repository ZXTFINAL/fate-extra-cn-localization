#!/usr/bin/env python3
"""Dump text referenced by Fate/Extra's field DAT bytecode into JSONL."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path


MAIN_POINTER_OPS = {0x3926: "dialogue", 0x1530: "backlog"}
def read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def read_string(data: bytes, offset: int) -> tuple[bytes, str] | None:
    if offset < 0 or offset >= len(data):
        return None
    end = data.find(b"\0", offset)
    if end < 0:
        return None
    raw = data[offset:end]
    try:
        text = raw.decode("cp932")
    except UnicodeDecodeError:
        text = raw.decode("cp932", "replace")
    return raw, text


def parse_dat(path: Path, base: Path) -> list[dict]:
    data = path.read_bytes()
    entries: dict[int, dict] = {}
    pos = 0
    while pos + 4 <= len(data):
        op_pos = pos
        op = read_u32(data, pos)
        pos += 4
        pending: list[tuple[int, str, str, bool]] = []

        if op in MAIN_POINTER_OPS:
            if pos + 4 <= len(data):
                pending.append((pos, MAIN_POINTER_OPS[op], "main", False))
                pos += 4
        elif op == 0x0126:
            if pos + 12 <= len(data):
                pos += 8
                # DAT opcode 0x0126 sets animated text motion. Its renderer
                # and glyph table are distinct from ordinary dialogue.
                pending.append((pos, "motion", "motion", False))
                pos += 4
        elif op == 0x0A26:
            if pos + 8 <= len(data):
                pos += 4
                pending.append((pos, "name_or_location", "misc", True))
                pos += 4
        elif op == 0x0A30:
            if pos + 20 <= len(data):
                pos += 16
                pending.append((pos, "choice", "misc", True))
                pos += 4
        elif op == 0x5030:
            if pos + 16 <= len(data):
                pos += 12
                pending.append((pos, "dungeon_dialogue", "misc", False))
                pos += 4
        elif op in (0x5F16, 0x6116, 0x6416):
            if pos + 8 <= len(data):
                pending.extend(((pos, "popup", "misc", False), (pos + 4, "popup", "misc", False)))
                pos += 8
        elif op in (0x5E16, 0x6016, 0x5316, 0x5016):
            if pos + 4 <= len(data):
                pending.append((pos, "popup", "misc", False))
                pos += 4
        elif op in (0x5916, 0x6316):
            if pos + 12 <= len(data):
                pos += 4
                pending.append((pos, "misc_prompt", "misc", False))
                pos += 4

        for ptr_pos, kind, category, check_alignment in pending:
            ptr = read_u32(data, ptr_pos)
            if ptr == 0 or (check_alignment and ptr & 3) or ptr >= len(data):
                continue
            result = read_string(data, ptr)
            if result is None:
                continue
            raw, text = result
            if not text:
                continue
            entry = entries.setdefault(ptr, {
                "text_offset": ptr,
                "jp": text,
                "jp_bytes_hex": raw.hex(),
                "pointer_offsets": [],
                "categories": set(),
                "kinds": set(),
            })
            entry["pointer_offsets"].append(ptr_pos)
            entry["categories"].add(category)
            entry["kinds"].add(kind)
    return [
        {
            **entry,
            "file": base.as_posix(),
            "pointer_offsets": sorted(set(entry["pointer_offsets"])),
            "categories": sorted(entry["categories"]),
            "kinds": sorted(entry["kinds"]),
            "id": hashlib.sha256(bytes.fromhex(entry["jp_bytes_hex"])).hexdigest()[:16],
        }
        for entry in entries.values()
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="extracted packages directory")
    parser.add_argument("-o", "--output", type=Path, default=Path("work/translation/text.jsonl"))
    parser.add_argument("--references", type=Path, default=Path("work/translation/refs.jsonl"))
    parser.add_argument("--day-input", type=Path, default=Path("work/extracted/cpk/day"))
    args = parser.parse_args()
    root = args.input
    dat_files = [(p, p.relative_to(root)) for p in root.rglob("*.dat") if "field" in p.parts]
    if args.day_input.exists():
        dat_files.extend((p, Path("day") / p.relative_to(args.day_input)) for p in args.day_input.rglob("*.dat"))
    dat_files.sort(key=lambda item: item[1].as_posix())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.references.parent.mkdir(parents=True, exist_ok=True)
    translations = {}
    references = 0
    with args.references.open("w", encoding="utf-8", newline="\n") as refs:
        for path, rel in dat_files:
            for entry in parse_dat(path, rel):
                entry_id = entry["id"]
                translated = translations.setdefault(entry_id, {
                    "id": entry_id,
                    "jp": entry["jp"],
                    "jp_bytes_hex": entry["jp_bytes_hex"],
                    "zh_cn": "",
                    "reference_count": 0,
                    "context": [],
                })
                translated["reference_count"] += 1
                if entry["file"] not in translated["context"] and len(translated["context"]) < 3:
                    translated["context"].append(entry["file"])
                ref = {key: entry[key] for key in ("id", "file", "text_offset", "pointer_offsets", "categories", "kinds")}
                refs.write(json.dumps(ref, ensure_ascii=False, separators=(",", ":")) + "\n")
                references += 1
    with args.output.open("w", encoding="utf-8", newline="\n") as out:
        for entry in translations.values():
            out.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"Scanned {len(dat_files)} field DAT files; found {references} referenced strings, {len(translations)} unique translation entries")
    print(f"Translation source: {args.output}")
    print(f"Reference map: {args.references}")


if __name__ == "__main__":
    main()
