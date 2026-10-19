#!/usr/bin/env python3
"""Restore the lowercase data.cpk ISO9660 identifier expected by Fate/Extra."""

from __future__ import annotations

import argparse
from pathlib import Path


SECTOR = 2048


def records(image, extent: int, size: int):
    image.seek(extent * SECTOR)
    data = image.read(size)
    offset = 0
    while offset < len(data):
        length = data[offset]
        if length == 0:
            offset = ((offset // SECTOR) + 1) * SECTOR
            continue
        record = data[offset:offset + length]
        if len(record) < 34:
            raise ValueError("truncated ISO9660 directory record")
        name_length = record[32]
        name = record[33:33 + name_length]
        yield offset, name, int.from_bytes(record[2:6], "little"), int.from_bytes(record[10:14], "little"), bool(record[25] & 2)
        offset += length


def find_dir(image, parent: tuple[int, int], wanted: bytes) -> tuple[int, int]:
    for _, name, extent, size, is_dir in records(image, *parent):
        if name == wanted and is_dir:
            return extent, size
    raise ValueError(f"ISO9660 directory not found: {wanted!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("iso", type=Path)
    args = parser.parse_args()

    with args.iso.open("r+b") as image:
        image.seek(16 * SECTOR)
        pvd = image.read(SECTOR)
        if pvd[:7] != b"\x01CD001\x01":
            raise ValueError("missing ISO9660 primary volume descriptor")
        root_record = pvd[156:190]
        root = (int.from_bytes(root_record[2:6], "little"), int.from_bytes(root_record[10:14], "little"))
        psp_game = find_dir(image, root, b"PSP_GAME")
        usrdir = find_dir(image, psp_game, b"USRDIR")
        for offset, name, extent, size, is_dir in records(image, *usrdir):
            if name == b"data.cpk" and not is_dir:
                print("ISO already contains lowercase data.cpk")
                return
            if name == b"DATA.CPK" and not is_dir:
                image.seek(usrdir[0] * SECTOR + offset + 33)
                image.write(b"data.cpk")
                image.flush()
                print(f"Patched ISO directory identifier at sector {usrdir[0]} to data.cpk ({size:,} bytes)")
                return
    raise ValueError("PSP_GAME/USRDIR/data.cpk was not found in ISO9660 directory")


if __name__ == "__main__":
    main()
