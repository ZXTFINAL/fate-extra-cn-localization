#!/usr/bin/env python3
"""Read/extract Fate/Extra PSP's CRI CPK/PAK/CMP resources.

The source ISO is opened read-only. Extracted assets are written under work/.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from pathlib import Path, PurePosixPath


TYPE_WIDTH = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 8, 8: 4, 10: 4, 11: 8}


def be(fmt: str, data: bytes, offset: int):
    return struct.unpack_from(">" + fmt, data, offset)[0]


def nul_string(data: bytes, offset: int) -> str:
    end = data.find(b"\0", offset)
    if end < 0:
        end = len(data)
    return data[offset:end].decode("utf-8", "replace")


def parse_utf(data: bytes, offset: int = 0) -> tuple[dict, list[dict]]:
    """Parse one big-endian CRI @UTF table."""
    if data[offset:offset + 4] != b"@UTF":
        raise ValueError(f"@UTF missing at 0x{offset:x}")
    table_size = be("I", data, offset + 4)
    content = offset + 8
    rows_offset, strings_offset, _data_offset, name_offset, ncols, row_width, nrows = struct.unpack_from(
        ">III I HH I".replace(" ", ""), data, content
    )
    string_base = content + strings_offset
    table_name = nul_string(data, string_base + name_offset)
    schema_pos = content + 24
    cols = []
    for _ in range(ncols):
        flags = data[schema_pos]
        name_offset_col = be("I", data, schema_pos + 1)
        schema_pos += 5
        storage, typ = flags & 0xF0, flags & 0x0F
        col = {"name": nul_string(data, string_base + name_offset_col), "storage": storage, "type": typ}
        width = TYPE_WIDTH.get(typ)
        if width is None:
            raise ValueError(f"unknown UTF field type 0x{typ:x}")
        if storage == 0x30:  # constant value follows its schema entry
            raw = data[schema_pos:schema_pos + width]
            if len(raw) != width:
                raise ValueError("truncated UTF constant")
            schema_pos += width
            col["constant_raw"] = raw
        elif storage not in (0x10, 0x50):
            raise ValueError(f"unknown UTF storage mode 0x{storage:x}")
        cols.append(col)

    if schema_pos - content != rows_offset:
        raise ValueError(f"UTF schema size mismatch: parsed {schema_pos-content}, rows at {rows_offset}")

    def decode_value(col: dict, raw: bytes):
        typ = col["type"]
        if typ == 10:
            return nul_string(data, string_base + struct.unpack(">I", raw)[0])
        if typ == 11:
            return struct.unpack(">II", raw)
        formats = {0: ">B", 1: ">b", 2: ">H", 3: ">h", 4: ">I", 5: ">i", 6: ">Q", 8: ">f"}
        return struct.unpack(formats[typ], raw)[0]

    rows = []
    row_pos = content + rows_offset
    for _ in range(nrows):
        row = {}
        for col in cols:
            if col["storage"] == 0x30:
                raw = col["constant_raw"]
            elif col["storage"] == 0x10:
                raw = bytes(TYPE_WIDTH[col["type"]])
            else:
                width = TYPE_WIDTH[col["type"]]
                raw = data[row_pos:row_pos + width]
                if len(raw) != width:
                    raise ValueError("truncated UTF row")
                row_pos += width
            row[col["name"]] = decode_value(col, raw)
        rows.append(row)
    if row_pos - (content + rows_offset) != nrows * row_width:
        raise ValueError(f"UTF row width mismatch in {table_name}")
    return {"name": table_name, "table_size": table_size, "rows": nrows}, rows


def parse_cpk(path: Path) -> tuple[dict, list[dict]]:
    with path.open("rb") as f:
        header = f.read(0x2000)
    head, _ = parse_utf(header, 0x10)
    toc_offset = next(
        (row["TocOffset"] for row in parse_utf(header, 0x10)[1]), None
    )
    if toc_offset is None:
        raise ValueError("CPK header has no TocOffset")
    with path.open("rb") as f:
        f.seek(toc_offset)
        frame = f.read(0x10)
        if frame[:4] != b"TOC ":
            raise ValueError(f"TOC frame missing at 0x{toc_offset:x}")
        toc_utf = f.read(0x100000)
    toc_meta, rows = parse_utf(toc_utf)
    base = min(next(r["ContentOffset"] for r in parse_utf(header, 0x10)[1]), toc_offset)
    for row in rows:
        row["AbsoluteOffset"] = base + row["FileOffset"]
    return {**head, "TocOffset": toc_offset, "ContentBase": base, "toc": toc_meta}, rows


def safe_relpath(directory: str, filename: str) -> Path:
    raw = PurePosixPath((directory.strip("/") + "/" + filename).lstrip("/"))
    if any(part in ("", ".", "..") for part in raw.parts):
        raise ValueError(f"unsafe archive path: {directory}/{filename}")
    return Path(*raw.parts)


def read_cpk_entry(cpk: Path, row: dict) -> bytes:
    with cpk.open("rb") as f:
        f.seek(row["AbsoluteOffset"])
        raw = f.read(row["FileSize"])
    if len(raw) != row["FileSize"]:
        raise ValueError(f"truncated CPK entry {row.get('FileName')}")
    if raw.startswith(b"CRILAYLA"):
        if len(raw) < 0x110:
            raise ValueError("short CRILAYLA frame")
        unpacked_size, packed_size = struct.unpack_from("<II", raw, 8)
        packed = raw[0x10:0x10 + packed_size]
        prefix = raw[0x10 + packed_size:0x110 + packed_size]
        if len(packed) != packed_size or len(prefix) != 0x100:
            raise ValueError("malformed CRILAYLA frame")
        return prefix + crilayla_decode(packed, unpacked_size)
    return raw


class BitReader:
    def __init__(self, data: bytes):
        self.data = data[::-1]
        self.bitpos = 0

    def read(self, bits: int) -> int:
        value = 0
        for _ in range(bits):
            if self.bitpos >= len(self.data) * 8:
                raise EOFError("truncated CRILAYLA bitstream")
            byte, bit = divmod(self.bitpos, 8)
            value = (value << 1) | ((self.data[byte] >> (7 - bit)) & 1)
            self.bitpos += 1
        return value


def crilayla_decode(packed: bytes, expected_size: int) -> bytes:
    bits = BitReader(packed)
    out = bytearray()
    while len(out) < expected_size:
        if bits.read(1):
            back = bits.read(13) + 3
            length = 3
            for width in (2, 3, 5):
                chunk = bits.read(width)
                length += chunk
                if chunk != (1 << width) - 1:
                    break
            else:
                while True:
                    chunk = bits.read(8)
                    length += chunk
                    if chunk != 0xFF:
                        break
            if back > len(out):
                raise ValueError("invalid CRILAYLA back-reference")
            for _ in range(length):
                out.append(out[-back])
                if len(out) == expected_size:
                    break
        else:
            out.append(bits.read(8))
    return bytes(out[::-1])


def decode_cmp(data: bytes) -> bytes:
    if data[:4] != b"IECP":
        raise ValueError("CMP/IECP signature missing")
    expected = struct.unpack_from("<I", data, 4)[0]
    out = bytearray()
    dictionary = bytearray(4096)
    dictpos = 0xFEE
    pos = 8
    while len(out) < expected:
        if pos >= len(data):
            raise ValueError("truncated CMP control stream")
        control = data[pos]
        pos += 1
        for bit in range(8):
            if len(out) >= expected:
                break
            if (control >> bit) & 1:
                if pos >= len(data):
                    raise ValueError("truncated CMP literal")
                value = data[pos]
                pos += 1
                out.append(value)
                dictionary[dictpos] = value
                dictpos = (dictpos + 1) & 0xFFF
            else:
                if pos + 2 > len(data):
                    raise ValueError("truncated CMP reference")
                b1, b2 = data[pos], data[pos + 1]
                pos += 2
                length = (b2 & 0xF) + 3
                source = (((b2 & 0xF0) << 4) | b1)
                for i in range(length):
                    value = dictionary[(source + i) & 0xFFF]
                    out.append(value)
                    dictionary[dictpos] = value
                    dictpos = (dictpos + 1) & 0xFFF
                    if len(out) >= expected:
                        break
    return bytes(out)


def unpack_pak(data: bytes, dest: Path) -> list[dict]:
    if len(data) < 4:
        raise ValueError("short PAK")
    count, marker = struct.unpack_from("<HH", data, 0)
    has_paths = marker == 0x8000
    sizes_start = 4
    sizes = list(struct.unpack_from("<" + "I" * count, data, sizes_start)) if count else []
    header_size = (4 + 4 * count + 15) & ~15
    pos = header_size
    records = []
    for index, size in enumerate(sizes):
        if has_paths:
            name_raw = data[pos:pos + 64]
            if len(name_raw) != 64:
                raise ValueError("truncated PAK filename")
            name = name_raw.split(b"\0", 1)[0].decode("shift_jis", "replace")
            pos += 64
        else:
            name = f"entry_{index:04d}.bin"
        payload = data[pos:pos + size]
        if len(payload) != size:
            raise ValueError(f"truncated PAK entry {index}: expected {size}, got {len(payload)}")
        pos += size
        rel = safe_relpath("", name) if has_paths else Path(name)
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(payload)
        records.append({"index": index, "path": name, "size": size, "output": str(out)})
    return records


def command_list(args):
    meta, rows = parse_cpk(args.cpk)
    print(json.dumps({"header": meta, "entry_count": len(rows), "entries": rows}, ensure_ascii=False, indent=2))


def command_extract(args):
    cpk = args.cpk
    meta, rows = parse_cpk(cpk)
    root = args.output
    root.mkdir(parents=True, exist_ok=True)
    chosen = []
    for row in rows:
        rel = safe_relpath(row.get("DirName", ""), row["FileName"])
        ext = rel.suffix.lower()
        if ext in (".dat", ".pak", ".cmp"):
            chosen.append((row, rel))
    manifest = {"source_cpk": str(cpk), "header": meta, "extracted": [], "packages": []}
    total = len(chosen)
    for index, (row, rel) in enumerate(chosen, 1):
        data = read_cpk_entry(cpk, row)
        raw_out = root / "cpk" / rel
        raw_out.parent.mkdir(parents=True, exist_ok=True)
        raw_out.write_bytes(data)
        item = {"path": rel.as_posix(), "size": len(data), "source_offset": row["AbsoluteOffset"]}
        manifest["extracted"].append(item)
        if rel.suffix.lower() in (".pak", ".cmp"):
            package_data = decode_cmp(data) if rel.suffix.lower() == ".cmp" else data
            pack_dest = root / "packages" / rel.parent / rel.stem
            records = unpack_pak(package_data, pack_dest)
            manifest["packages"].append({"path": rel.as_posix(), "count": len(records), "entries": records})
        if index % 100 == 0 or index == total:
            print(f"[{index}/{total}] {rel}", file=sys.stderr)
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Extracted {len(chosen)} files; unpacked {len(manifest['packages'])} PAK/CMP packages into {root}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(required=True)
    p_list = sub.add_parser("list", help="list CPK contents as JSON")
    p_list.add_argument("cpk", type=Path)
    p_list.set_defaults(func=command_list)
    p_extract = sub.add_parser("extract", help="extract DAT/PAK/CMP entries and unpack packages")
    p_extract.add_argument("cpk", type=Path)
    p_extract.add_argument("-o", "--output", type=Path, default=Path("work/extracted"))
    p_extract.set_defaults(func=command_extract)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
