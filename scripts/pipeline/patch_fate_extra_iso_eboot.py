#!/usr/bin/env python3
"""Put a translated decrypted EBOOT ELF into a copy of a Fate/Extra ISO for PPSSPP."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import struct
from pathlib import Path

from embed_fate_extra_cpk import PVD_SECTOR, SECTOR, hash_range, walk


EXPECTED_ENCRYPTED_EBOOT_SHA256 = "5a0a6b5904e50b11d74fdaa9e0e3107836bb0925f699d6245f7405903f991408"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def patch_iso(source_iso: Path, elf_path: Path, output_iso: Path, report_path: Path | None) -> dict:
    elf_size = elf_path.stat().st_size
    if elf_size < 4 or elf_path.open("rb").read(4) != b"\x7fELF":
        raise ValueError("translated EBOOT must be a decrypted ELF")
    elf_hash = sha256_file(elf_path)
    if source_iso.resolve() == output_iso.resolve():
        raise ValueError("refusing to overwrite the CPK-only ISO; choose a separate PPSSPP output path")
    output_iso.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_iso, output_iso)

    with output_iso.open("r+b") as image:
        image.seek(PVD_SECTOR * SECTOR)
        pvd = image.read(SECTOR)
        if len(pvd) != SECTOR or pvd[0] != 1 or pvd[1:6] != b"CD001":
            raise ValueError("source is missing a valid ISO9660 primary volume descriptor")
        volume_sectors = struct.unpack_from("<I", pvd, 80)[0]
        if struct.unpack_from(">I", pvd, 84)[0] != volume_sectors:
            raise ValueError("ISO volume size fields are inconsistent")
        image.seek(PVD_SECTOR * SECTOR + 156)
        root = image.read(34)
        root_extent = struct.unpack_from("<I", root, 2)[0]
        root_size = struct.unpack_from("<I", root, 10)[0]
        entries = list(walk(image, root_extent, root_size))
        eboots = [entry for entry in entries if entry[4] == ("PSP_GAME", "SYSDIR", "EBOOT.BIN")]
        cpks = [entry for entry in entries if entry[4] == ("PSP_GAME", "USRDIR", "data.cpk")]
        if len(eboots) != 1 or len(cpks) != 1:
            raise ValueError(f"expected one EBOOT.BIN and one data.cpk, got {len(eboots)} and {len(cpks)}")

        record_offset, _record, extent, old_size, _path, is_dir = eboots[0]
        if is_dir:
            raise ValueError("EBOOT.BIN directory record is invalid")
        old_eboot_hash = hash_range(image, extent * SECTOR, old_size)
        if old_eboot_hash != EXPECTED_ENCRYPTED_EBOOT_SHA256:
            raise ValueError(
                "ISO EBOOT is not the verified NPJH-50247 retail executable; "
                f"expected {EXPECTED_ENCRYPTED_EBOOT_SHA256}, got {old_eboot_hash}"
            )
        if math.ceil(elf_size / SECTOR) != math.ceil(old_size / SECTOR):
            raise ValueError("replacement ELF must fit the original EBOOT sector allocation exactly")
        if (extent + math.ceil(elf_size / SECTOR)) * SECTOR > volume_sectors * SECTOR:
            raise ValueError("replacement EBOOT would extend beyond the ISO volume")

        cpk_record_offset, _cpk_record, cpk_extent, cpk_size, _cpk_path, cpk_is_dir = cpks[0]
        if cpk_is_dir:
            raise ValueError("data.cpk directory record is invalid")
        cpk_hash_before = hash_range(image, cpk_extent * SECTOR, cpk_size)

        image.seek(extent * SECTOR)
        with elf_path.open("rb") as source:
            shutil.copyfileobj(source, image, length=8 * 1024 * 1024)
        if elf_size < old_size:
            image.seek(extent * SECTOR + elf_size)
            remaining = old_size - elf_size
            zeroes = b"\0" * min(1024 * 1024, remaining)
            while remaining:
                chunk = min(remaining, len(zeroes))
                image.write(zeroes[:chunk])
                remaining -= chunk

        image.seek(record_offset + 10)
        image.write(struct.pack("<I", elf_size) + struct.pack(">I", elf_size))
        image.flush()

        image.seek(record_offset + 10)
        if image.read(8) != struct.pack("<I", elf_size) + struct.pack(">I", elf_size):
            raise ValueError("EBOOT ISO directory record size update failed")
        eboot_hash_after = hash_range(image, extent * SECTOR, elf_size)
        cpk_hash_after = hash_range(image, cpk_extent * SECTOR, cpk_size)
        if eboot_hash_after != elf_hash:
            raise ValueError("written EBOOT bytes do not match the translated ELF")
        if cpk_hash_after != cpk_hash_before:
            raise ValueError("the translated CPK changed while patching EBOOT")

    report = {
        "source_iso": str(source_iso),
        "source_iso_sha256": sha256_file(source_iso),
        "output_iso": str(output_iso),
        "output_iso_sha256": sha256_file(output_iso),
        "original_encrypted_eboot_sha256": old_eboot_hash,
        "translated_elf_sha256": elf_hash,
        "translated_elf_bytes": elf_size,
        "data_cpk_sha256_unchanged": cpk_hash_after,
        "boot_note": "This ISO contains a decrypted EBOOT ELF for PPSSPP/CFW; retail PSP firmware compatibility is not implied.",
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-iso", type=Path, required=True)
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--output-iso", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = patch_iso(args.source_iso, args.elf, args.output_iso, args.report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
