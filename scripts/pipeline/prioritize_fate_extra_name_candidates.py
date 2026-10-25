#!/usr/bin/env python3
"""Move 岸波白野's existing kanji earlier in the matching name-entry groups.

The name-entry binary stores CP932 characters in variable-sized phonetic groups.
This tool only reorders characters inside their existing groups, preserving the
record count, byte length, all candidates, and the original source file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path


GROUPS = {
    "岸": "が",
    "波": "は",
    "白": "は",
    "野": "や",
}
ORDER = {"が": ["岸"], "は": ["波", "白"], "や": ["野"]}


def parse(data: bytes) -> list[dict]:
    records = []
    offset = 0
    expected_index = 0
    while offset + 8 <= len(data):
        if offset + 8 > len(data):
            raise ValueError(f"truncated record header at 0x{offset:x}")
        index, size = struct.unpack_from("<II", data, offset)
        if index != expected_index:
            raise ValueError(f"record index mismatch at 0x{offset:x}: {index} != {expected_index}")
        if size < 4 or size % 2 or offset + 8 + size > len(data):
            raise ValueError(f"invalid record size {size} at 0x{offset:x}")
        body = data[offset + 8:offset + 8 + size]
        terminator = body.find(b"\0\0")
        if terminator < 0 or terminator % 2 or any(body[terminator:]):
            raise ValueError(f"invalid candidate-list terminator/padding at 0x{offset + 8 + max(terminator, 0):x}")
        encoded = [body[i:i + 2] for i in range(0, terminator, 2)]
        try:
            chars = [unit.decode("cp932") for unit in encoded]
        except UnicodeDecodeError as exc:
            raise ValueError(f"invalid CP932 candidate in record {index}") from exc
        if any(len(char) != 1 for char in chars):
            raise ValueError(f"record {index} contains a non-single-character candidate")
        records.append({"index": index, "size": size, "offset": offset, "chars": chars, "encoded": encoded})
        offset += 8 + size
        expected_index += 1
    if offset != len(data) and not (len(data) - offset == 4 and data[offset:] == b"\0\0\0\0"):
        raise ValueError(f"records end at {offset}, invalid trailing bytes in file length {len(data)}")
    return records


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", type=Path, help="Extracted nameentry/kanji.bin")
    ap.add_argument("--out", type=Path, required=True, help="Prioritized binary output")
    ap.add_argument("--report", type=Path, required=True, help="JSON audit report")
    args = ap.parse_args()

    original = args.source.read_bytes()
    records = parse(original)
    record_end = sum(8 + record["size"] for record in records)
    trailer = original[record_end:]
    by_group = {r["chars"][0]: r for r in records if r["chars"]}
    changes = []
    for group, wanted in ORDER.items():
        record = by_group.get(group)
        if record is None:
            raise ValueError(f"phonetic group {group!r} not found")
        chars = record["chars"]
        encoded = record["encoded"]
        for target_index, char in enumerate(wanted, start=1):
            positions = [i for i, value in enumerate(chars) if value == char]
            if len(positions) != 1:
                raise ValueError(f"expected one {char!r} in group {group!r}, found {len(positions)}")
            old_index = positions[0]
            if old_index < target_index:
                continue
            chars[target_index], chars[old_index] = chars[old_index], chars[target_index]
            encoded[target_index], encoded[old_index] = encoded[old_index], encoded[target_index]
            changes.append({"character": char, "group": group, "old_candidate_index": old_index,
                            "new_candidate_index": target_index})

    output = bytearray()
    for record in records:
        body = b"".join(record["encoded"]) + b"\0\0"
        body += b"\0" * (record["size"] - len(body))
        if len(body) != record["size"]:
            raise ValueError(f"record {record['index']} length changed")
        output.extend(struct.pack("<II", record["index"], record["size"]))
        output.extend(body)
    output.extend(trailer)
    final = bytes(output)
    if len(final) != len(original):
        raise ValueError("file length changed")
    final_records = parse(final)
    for group, wanted in ORDER.items():
        actual = final_records[by_group[group]["index"]]["chars"]
        if actual[1:1 + len(wanted)] != wanted:
            raise ValueError(f"candidate order validation failed for group {group!r}")
    # Compare multiset per phonetic group after reordering; no entry may be lost.
    for before, after in zip(records, final_records):
        if sorted(before["chars"]) != sorted(after["chars"]):
            raise ValueError(f"candidate set changed in group {before['index']}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(final)
    report = {
        "source": str(args.source),
        "source_sha256": hashlib.sha256(original).hexdigest(),
        "output": str(args.out),
        "output_sha256": hashlib.sha256(final).hexdigest(),
        "bytes_before": len(original),
        "bytes_after": len(final),
        "record_count": len(records),
        "prefill_string_found": False,
        "characters_found_individually": {char: True for char in GROUPS},
        "changes": changes,
        "runtime_name-entry_test": "not run per user instruction",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"source", "output"}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
