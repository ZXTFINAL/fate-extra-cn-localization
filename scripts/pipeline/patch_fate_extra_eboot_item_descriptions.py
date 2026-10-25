#!/usr/bin/env python3
"""Translate the shared runtime item-effect strings in Fate/Extra's decrypted EBOOT."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


EXPECTED_INPUT_SHA256 = "e6eb5f54d78aa724bf180c25ed33451d8b2c125e6661e72effc2b2ec7864f236"
REPLACEMENTS = (
    ("boost_mp(%02d);", "御主MP+%02d"),
    ("マスターのＭＰが%s上昇", "御主MP提升%s点"),
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encode_game_text(text: str, glyph_map: dict[str, str]) -> bytes:
    mapped = "".join(glyph_map.get(char, char) for char in text)
    try:
        return mapped.encode("cp932")
    except UnicodeEncodeError as exc:
        unsupported = sorted(set(mapped[exc.start:exc.end]))
        rendered = ", ".join(f"{char} (U+{ord(char):04X})" for char in unsupported)
        raise ValueError(f"text has no CP932/glyph mapping: {rendered}") from exc


def patch_elf(input_elf: Path, output_elf: Path, glyph_map_path: Path) -> dict:
    source = input_elf.read_bytes()
    source_hash = sha256(source)
    if source_hash != EXPECTED_INPUT_SHA256:
        raise ValueError(
            "input ELF is not the verified Japanese Fate/Extra EBOOT; "
            f"expected SHA-256 {EXPECTED_INPUT_SHA256}, got {source_hash}"
        )
    if not source.startswith(b"\x7fELF"):
        raise ValueError("input is not a decrypted ELF")

    glyph_map = json.loads(glyph_map_path.read_text(encoding="utf-8"))
    patched = bytearray(source)
    changes = []
    for original, translated in REPLACEMENTS:
        old_bytes = original.encode("cp932")
        new_bytes = encode_game_text(translated, glyph_map)
        locations = []
        cursor = 0
        while True:
            offset = source.find(old_bytes, cursor)
            if offset < 0:
                break
            locations.append(offset)
            cursor = offset + len(old_bytes)
        if len(locations) != 1:
            raise ValueError(f"expected one occurrence of {original!r}, found {len(locations)}")
        offset = locations[0]
        terminator = source.find(b"\0", offset)
        if terminator < 0 or source[offset:terminator] != old_bytes:
            raise ValueError(f"unexpected EBOOT string slot for {original!r}")
        slot_size = terminator - offset + 1
        if len(new_bytes) + 1 > slot_size:
            raise ValueError(
                f"translated text does not fit at 0x{offset:x}: "
                f"{len(new_bytes)} bytes in a {slot_size - 1}-byte slot"
            )
        patched[offset:offset + slot_size] = new_bytes + b"\0" * (slot_size - len(new_bytes))
        changes.append({
            "offset": f"0x{offset:x}",
            "source": original,
            "translation": translated,
            "source_bytes": len(old_bytes),
            "translation_bytes": len(new_bytes),
            "slot_bytes_including_nul": slot_size,
        })

    result = bytes(patched)
    for original, _translated in REPLACEMENTS:
        if original.encode("cp932") in result:
            raise ValueError(f"source string remains after patch: {original!r}")
    output_elf.parent.mkdir(parents=True, exist_ok=True)
    output_elf.write_bytes(result)
    return {
        "input": str(input_elf),
        "input_sha256": source_hash,
        "output": str(output_elf),
        "output_sha256": sha256(result),
        "size_bytes": len(result),
        "changes": changes,
        "target_runtime": "decrypted EBOOT for PPSSPP/CFW; retail PSP firmware compatibility is not implied",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-elf", type=Path, required=True)
    parser.add_argument("--glyph-map", type=Path, required=True)
    parser.add_argument("--output-elf", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    report = patch_elf(args.input_elf, args.output_elf, args.glyph_map)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
