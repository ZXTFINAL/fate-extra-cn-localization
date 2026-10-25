#!/usr/bin/env python3
"""Translate fixed-slot menu help and confirmation labels in UI BIN files."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

from build_fate_extra import encode_game_text


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "data/evidence/ui/fixed-ui-text-patches.json"
DEFAULT_GLYPH_MAP = ROOT / "data/translation/glyph-map.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_fixed_strings(data: bytes, path: Path) -> tuple[list[dict], int]:
    records: list[dict] = []
    offset = 0
    while offset < len(data):
        if not any(data[offset:]):
            break
        if offset + 8 > len(data):
            raise ValueError(f"{path}: truncated record header at 0x{offset:x}")
        record_id, capacity = struct.unpack_from("<II", data, offset)
        if capacity == 0 or capacity > len(data) - offset - 8:
            raise ValueError(f"{path}: invalid capacity {capacity} at 0x{offset:x}")
        field = data[offset + 8:offset + 8 + capacity]
        end = field.find(b"\0")
        if end < 0:
            raise ValueError(f"{path}: unterminated record {record_id} at 0x{offset:x}")
        if any(field[end + 1:]):
            raise ValueError(f"{path}: nonzero padding in record {record_id} at 0x{offset:x}")
        try:
            source = field[:end].decode("cp932")
        except UnicodeDecodeError as error:
            raise ValueError(f"{path}: invalid CP932 in record {record_id}: {error}") from error
        records.append({
            "id": record_id,
            "offset": offset,
            "capacity": capacity,
            "source": source,
        })
        offset += 8 + capacity
    return records, offset


def patch_resource(resource: dict, source_root: Path, out_root: Path,
                   glyph_map: dict[str, str]) -> dict:
    relative = Path(resource["path"])
    source_path = source_root / relative
    if not source_path.is_file():
        raise FileNotFoundError(f"source resource not found: {source_path}")
    source_data = source_path.read_bytes()
    source_hash = sha256(source_data)
    if source_hash != resource["source_sha256"]:
        raise ValueError(
            f"source hash mismatch for {source_path}: "
            f"{source_hash} != {resource['source_sha256']}"
        )

    records, tail_offset = parse_fixed_strings(source_data, source_path)
    by_id = {record["id"]: record for record in records}
    if len(by_id) != len(records):
        raise ValueError(f"duplicate string IDs in {source_path}")

    output = bytearray(source_data)
    replacements = []
    for item in resource["strings"]:
        record_id = item["id"]
        record = by_id.get(record_id)
        if record is None:
            raise ValueError(f"{source_path}: configured record {record_id} is missing")
        if record["source"] != item["source"]:
            raise ValueError(
                f"{source_path}: source text mismatch at id {record_id}: "
                f"{record['source']!r} != {item['source']!r}"
            )
        encoded = encode_game_text(item["target"], glyph_map)
        if len(encoded) + 1 > record["capacity"]:
            raise ValueError(
                f"{source_path}: id {record_id} target needs {len(encoded) + 1} bytes, "
                f"capacity is {record['capacity']}"
            )
        start = record["offset"] + 8
        output[start:start + record["capacity"]] = encoded + bytes(record["capacity"] - len(encoded))
        replacements.append({
            "id": record_id,
            "offset": start,
            "capacity": record["capacity"],
            "source": item["source"],
            "target": item["target"],
            "source_bytes": len(item["source"].encode("cp932")),
            "target_bytes": len(encoded),
        })

    if len(output) != len(source_data) or output[tail_offset:] != source_data[tail_offset:]:
        raise ValueError(f"{source_path}: resource layout or trailing bytes changed")
    destination = out_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(output)

    reverse_map = {alias: character for character, alias in glyph_map.items()}
    for item in replacements:
        start = item["offset"]
        field = bytes(output[start:start + item["capacity"]])
        decoded = field.split(b"\0", 1)[0].decode("cp932")
        roundtrip = "".join(reverse_map.get(character, character) for character in decoded)
        if roundtrip != item["target"]:
            raise ValueError(
                f"{destination}: readback mismatch for id {item['id']}: "
                f"{roundtrip!r} != {item['target']!r}"
            )

    return {
        "path": resource["path"],
        "source_size": len(source_data),
        "output_size": len(output),
        "source_sha256": source_hash,
        "output_sha256": sha256(output),
        "records": replacements,
        "fixed_size_preserved": len(source_data) == len(output),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                        help="fixed UI string patch configuration")
    parser.add_argument("--source-root", type=Path,
                        default=Path("work/extracted/packages/pack"),
                        help="root containing the unpacked source packages")
    parser.add_argument("--glyph-map", type=Path, default=DEFAULT_GLYPH_MAP,
                        help="Chinese character to CP932 glyph alias map")
    parser.add_argument("--out", type=Path,
                        default=Path("work/build/localization-v1.1/fixed-ui-overlay/packages/pack"),
                        help="output root mirroring source package paths")
    parser.add_argument("--report", type=Path,
                        default=Path("work/build/localization-v1.1/fixed-ui-overlay/patch-report.json"),
                        help="JSON verification report path")
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    glyph_map = json.loads(args.glyph_map.read_text(encoding="utf-8"))
    results = [patch_resource(resource, args.source_root, args.out, glyph_map)
               for resource in config["resources"]]
    report = {
        "config_sha256": sha256(args.config.read_bytes()),
        "glyph_map_sha256": sha256(args.glyph_map.read_bytes()),
        "resources": results,
        "patched_strings": sum(len(resource["records"]) for resource in results),
        "fixed_sizes_preserved": all(resource["fixed_size_preserved"] for resource in results),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "resources": len(results),
        "patched_strings": report["patched_strings"],
        "fixed_sizes_preserved": report["fixed_sizes_preserved"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
