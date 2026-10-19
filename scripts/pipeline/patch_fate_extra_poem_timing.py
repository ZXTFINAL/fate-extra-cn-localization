#!/usr/bin/env python3
"""Give Fate/Extra's paired animated chapter title cards more reading time."""

from __future__ import annotations

import argparse
import struct
from pathlib import Path


POEM_MOTION = 0x1B
POEM_OP = 0x0126
WAIT_OP = 0x0200
CALL_OP = 0x1401
TITLE_WAIT = 0x3C
EXTENDED_TITLE_WAIT = 0x96


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def patch_file(path: Path) -> list[tuple[int, int, int]]:
    data = bytearray(path.read_bytes())
    poem_ops = []
    for offset in range(0, len(data) - 16, 4):
        if u32(data, offset) != POEM_OP:
            continue
        struct_id, motion = struct.unpack_from("<II", data, offset + 4)
        if motion == POEM_MOTION and struct_id in (0, 1):
            poem_ops.append((offset, struct_id))

    patched = []
    for index, (first_offset, first_id) in enumerate(poem_ops[:-1]):
        second_offset, second_id = poem_ops[index + 1]
        if first_id != 0 or second_id != 1 or second_offset - first_offset != 0x40:
            continue
        start = second_offset + 0x80
        end = min(len(data) - 12, second_offset + 0x180)
        matches = []
        for offset in range(start, end, 4):
            if (
                u32(data, offset) == WAIT_OP
                and u32(data, offset + 4) == 0
                and u32(data, offset + 8) == TITLE_WAIT
                and u32(data, offset + 12) == CALL_OP
            ):
                matches.append(offset)
        if len(matches) != 1:
            raise ValueError(
                f"{path}: expected one 60-tick title-card wait after pair "
                f"0x{first_offset:x}/0x{second_offset:x}, found {len(matches)}"
            )
        wait_offset = matches[0] + 8
        struct.pack_into("<I", data, wait_offset, EXTENDED_TITLE_WAIT)
        patched.append((first_offset, second_offset, wait_offset))

    if patched:
        path.write_bytes(data)
    return patched


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "asset_root",
        type=Path,
        help="root directory containing translated day/*.dat assets",
    )
    args = parser.parse_args()
    if not args.asset_root.is_dir():
        raise SystemExit(f"day asset directory not found: {args.asset_root}")

    results = []
    for path in sorted(args.asset_root.glob("*.dat")):
        for first, second, wait in patch_file(path):
            results.append((path.name, first, second, wait))
    if not results:
        raise SystemExit("no paired animated title cards matched the expected bytecode")
    for name, first, second, wait in results:
        print(f"{name}: title pair 0x{first:x}/0x{second:x}, extended wait at 0x{wait:x}")
    print(f"Extended {len(results)} title-card waits from {TITLE_WAIT} to {EXTENDED_TITLE_WAIT} ticks.")


if __name__ == "__main__":
    main()
