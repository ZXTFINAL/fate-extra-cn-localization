#!/usr/bin/env python3
"""Replace the data.cpk payload in an existing Fate/Extra PSP ISO."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import struct
from pathlib import Path


SECTOR = 2048
PVD_SECTOR = 16


def read_record(stream, offset: int) -> tuple[bytes, int, int, bytes, bool] | None:
    stream.seek(offset)
    first = stream.read(1)
    if not first:
        return None
    length = first[0]
    if length == 0:
        return None
    stream.seek(offset)
    record = stream.read(length)
    if len(record) != length or length < 34:
        raise ValueError(f"invalid ISO9660 directory record at byte {offset}")
    extent = struct.unpack_from("<I", record, 2)[0]
    size = struct.unpack_from("<I", record, 10)[0]
    name_length = record[32]
    name = record[33:33 + name_length]
    return record, extent, size, name, bool(record[25] & 2)


def walk(stream, extent: int, size: int, path: tuple[str, ...] = ()):
    position = 0
    while position < size:
        absolute = extent * SECTOR + position
        stream.seek(absolute)
        first = stream.read(1)
        if not first:
            raise ValueError("truncated ISO directory")
        if first[0] == 0:
            position = ((position // SECTOR) + 1) * SECTOR
            continue
        item = read_record(stream, absolute)
        if item is None:
            break
        record, child_extent, child_size, raw_name, is_dir = item
        if raw_name == b"\0":
            name = "."
        elif raw_name == b"\1":
            name = ".."
        else:
            name = raw_name.decode("ascii", "strict").split(";", 1)[0]
        child_path = path + (name,)
        yield absolute, record, child_extent, child_size, child_path, is_dir
        if is_dir and name not in {".", ".."}:
            yield from walk(stream, child_extent, child_size, child_path)
        position += len(record)


def hash_range(stream, offset: int, size: int) -> str:
    digest = hashlib.sha256()
    stream.seek(offset)
    remaining = size
    while remaining:
        block = stream.read(min(8 * 1024 * 1024, remaining))
        if not block:
            raise ValueError("truncated ISO file payload")
        digest.update(block)
        remaining -= len(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-iso", type=Path, required=True)
    parser.add_argument("--cpk", type=Path, required=True)
    parser.add_argument("--output-iso", type=Path, required=True)
    parser.add_argument(
        "--allow-volume-growth",
        action="store_true",
        help="allow data.cpk to grow into unused sectors and update the ISO volume size",
    )
    args = parser.parse_args()

    new_size = args.cpk.stat().st_size
    args.output_iso.parent.mkdir(parents=True, exist_ok=True)
    # Allow rebuilding the current ISO in place. This avoids holding two
    # full-size copies when only the data.cpk payload needs to be replaced.
    same_iso = args.source_iso.resolve() == args.output_iso.resolve()
    if not same_iso:
        shutil.copyfile(args.source_iso, args.output_iso)

    with args.output_iso.open("r+b") as image:
        image.seek(PVD_SECTOR * SECTOR)
        pvd = image.read(SECTOR)
        if len(pvd) != SECTOR or pvd[0] != 1 or pvd[1:6] != b"CD001":
            raise ValueError("source is missing an ISO9660 primary volume descriptor")
        volume_sectors = struct.unpack_from("<I", pvd, 80)[0]
        if struct.unpack_from(">I", pvd, 84)[0] != volume_sectors:
            raise ValueError("ISO primary volume descriptor has inconsistent volume size fields")
        if args.source_iso.stat().st_size < volume_sectors * SECTOR:
            raise ValueError("source ISO is shorter than its declared volume size")
        image.seek(PVD_SECTOR * SECTOR + 156)
        root = image.read(34)
        root_extent = struct.unpack_from("<I", root, 2)[0]
        root_size = struct.unpack_from("<I", root, 10)[0]

        entries = list(walk(image, root_extent, root_size))
        targets = [
            entry for entry in entries
            if entry[4][-1].lower() == "data.cpk"
            and entry[4][-2:] == ("USRDIR", "data.cpk")
        ]
        if len(targets) != 1:
            raise ValueError(f"expected one PSP_GAME/USRDIR/data.cpk record, found {len(targets)}")
        record_offset, record, extent, old_size, _path, is_dir = targets[0]
        if is_dir:
            raise ValueError("data.cpk ISO record is unexpectedly a directory")
        if new_size > old_size and not args.allow_volume_growth:
            raise ValueError(
                f"new CPK ({new_size:,} bytes) exceeds its ISO allocation ({old_size:,}); "
                "use --allow-volume-growth only when the new extent does not overlap another file"
            )

        start_sector = extent
        allocation_size = max(old_size, new_size)
        end_sector = extent + (allocation_size + SECTOR - 1) // SECTOR
        for _off, _rec, other_extent, other_size, other_path, other_is_dir in entries:
            if other_is_dir or other_path == _path or other_size == 0:
                continue
            other_start = other_extent
            other_end = other_extent + (other_size + SECTOR - 1) // SECTOR
            if start_sector < other_end and other_start < end_sector:
                raise ValueError(f"data.cpk overlaps another ISO file: {'/'.join(other_path)}")

        new_volume_sectors = max(
            volume_sectors,
            (extent * SECTOR + new_size + SECTOR - 1) // SECTOR,
        )
        if new_volume_sectors > volume_sectors and not args.allow_volume_growth:
            raise ValueError("new data.cpk extends beyond the declared ISO volume size")

        image.seek(extent * SECTOR)
        with args.cpk.open("rb") as source:
            shutil.copyfileobj(source, image, length=8 * 1024 * 1024)
        if new_size < old_size:
            image.seek(extent * SECTOR + new_size)
            remaining = old_size - new_size
            zeroes = b"\0" * min(1024 * 1024, remaining)
            while remaining:
                count = min(remaining, len(zeroes))
                image.write(zeroes[:count])
                remaining -= count

        image.seek(record_offset + 10)
        image.write(struct.pack("<I", new_size))
        image.write(struct.pack(">I", new_size))
        if new_volume_sectors > volume_sectors:
            image.seek(PVD_SECTOR * SECTOR + 80)
            image.write(struct.pack("<I", new_volume_sectors))
            image.write(struct.pack(">I", new_volume_sectors))
            image.truncate(max(
                args.source_iso.stat().st_size,
                new_volume_sectors * SECTOR,
            ))
        image.flush()

        image.seek(record_offset + 10)
        if image.read(8) != struct.pack("<I", new_size) + struct.pack(">I", new_size):
            raise ValueError("ISO directory record size update failed")
        image.seek(PVD_SECTOR * SECTOR + 80)
        if image.read(8) != struct.pack("<I", new_volume_sectors) + struct.pack(">I", new_volume_sectors):
            raise ValueError("ISO volume size update failed")
        if args.output_iso.stat().st_size < new_volume_sectors * SECTOR:
            raise ValueError("output ISO is shorter than its declared volume size")
        embedded_hash = hash_range(image, extent * SECTOR, new_size)

    with args.cpk.open("rb") as cpk_stream:
        cpk_hash = hash_range(cpk_stream, 0, new_size)
    if embedded_hash != cpk_hash:
        raise ValueError("embedded data.cpk does not match the requested CPK")
    print(f"Wrote {args.output_iso} ({args.output_iso.stat().st_size:,} bytes)")
    print(f"Embedded data.cpk: {new_size:,} bytes, SHA-256 {embedded_hash}")


if __name__ == "__main__":
    main()
