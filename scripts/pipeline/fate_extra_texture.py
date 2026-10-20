#!/usr/bin/env python3
"""Lossless Fate/Extra TXB/TEX reader and indexed texture editor.

Supports T4/T8 PSP swizzle, 16/32px CCT chunks and RGBA8888 TEX.
Unchanged index images re-encode byte-for-byte, including palette and padding.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import struct

import numpy as np
from PIL import Image


@dataclass
class Bundle:
    source: bytes
    names: list[str]
    payloads: list[bytes]
    raw_names: list[bytes]
    header: bytes
    tail: bytes
    has_paths: bool

    @classmethod
    def parse(cls, data: bytes) -> "Bundle":
        count, marker = struct.unpack_from("<HH", data)
        sizes = struct.unpack_from(f"<{count}I", data, 4)
        pos = (4 + count * 4 + 15) & ~15
        header = data[:pos]
        names, payloads, raw_names = [], [], []
        for i, size in enumerate(sizes):
            raw = data[pos:pos + 64] if marker == 0x8000 else b""
            pos += len(raw)
            name = raw.split(b"\0", 1)[0].decode("cp932", "replace") if raw else f"entry_{i:04d}.tex"
            payload = data[pos:pos + size]
            if len(payload) != size:
                raise ValueError(f"truncated TXB entry {i}")
            names.append(name); raw_names.append(raw); payloads.append(payload)
            pos += size
        return cls(data, names, payloads, raw_names, header, data[pos:], marker == 0x8000)

    def rebuild(self, payloads: list[bytes] | None = None) -> bytes:
        payloads = self.payloads if payloads is None else payloads
        if len(payloads) != len(self.payloads):
            raise ValueError("entry count changed")
        out = bytearray(self.header)
        struct.pack_into(f"<{len(payloads)}I", out, 4, *(len(p) for p in payloads))
        for raw_name, payload in zip(self.raw_names, payloads):
            out.extend(raw_name); out.extend(payload)
        out.extend(self.tail)
        return bytes(out)


def unswizzle(data: bytes, row_bytes: int) -> bytes:
    if row_bytes % 16 or len(data) % (row_bytes * 8):
        raise ValueError(f"unaligned swizzled buffer: row={row_bytes}, bytes={len(data)}")
    src = np.frombuffer(data, dtype=np.uint8).reshape(-1, row_bytes // 16, 8, 16)
    return src.transpose(0, 2, 1, 3).reshape(-1, row_bytes).tobytes()


def swizzle(data: bytes, row_bytes: int) -> bytes:
    if row_bytes % 16 or len(data) % (row_bytes * 8):
        raise ValueError(f"unaligned linear buffer: row={row_bytes}, bytes={len(data)}")
    src = np.frombuffer(data, dtype=np.uint8).reshape(-1, 8, row_bytes // 16, 16)
    return src.transpose(0, 2, 1, 3).tobytes()


def unpack_indices(data: bytes, bpp: int, width: int) -> np.ndarray:
    a = np.frombuffer(data, dtype=np.uint8)
    if bpp == 4:
        p = np.empty(a.size * 2, dtype=np.uint8)
        p[0::2] = a & 15; p[1::2] = a >> 4
        a = p
    return a.reshape(-1, width).copy()


def pack_indices(pixels: np.ndarray, bpp: int) -> bytes:
    a = np.asarray(pixels, dtype=np.uint8).reshape(-1)
    if bpp == 4:
        if np.any(a > 15):
            raise ValueError("T4 index exceeds 15")
        a = a[0::2] | (a[1::2] << 4)
    return a.tobytes()


class Texture:
    def __init__(self, data: bytes):
        if len(data) < 48:
            raise ValueError("short TEX")
        self.source = data
        self.format, self.swizzled, self.width, self.height, self.stride = struct.unpack_from("<5H", data, 0x10)
        self.data_size = struct.unpack_from("<I", data, 0x1c)[0]
        if self.format not in (3, 4, 5):
            raise ValueError(f"unsupported TEX format {self.format}")
        self.bpp = {3: 32, 4: 4, 5: 8}[self.format]
        self.pixel_data = data[48:48 + self.data_size]
        if len(self.pixel_data) != self.data_size:
            raise ValueError("truncated pixel data")
        self.palette_offset = 48 + self.data_size
        self.cct_offset = None
        self.cct = None
        self.cct_end = None
        self.chunk_size = None
        self.palette = None
        self.palette_mode = None
        if self.format in (4, 5):
            self.palette_mode, colors = struct.unpack_from("<HH", data, self.palette_offset)
            color_size = 4 if self.palette_mode == 3 else 2
            raw = data[self.palette_offset + 16:self.palette_offset + 16 + colors * color_size]
            if len(raw) != colors * color_size:
                raise ValueError("truncated palette")
            self.palette = self._palette(raw, self.palette_mode)
            co = self.palette_offset + 16 + len(raw)
            if co + 20 <= len(data):
                cols, rows, count, chunk, unique, reserved, unknown = struct.unpack_from("<IIHhHHI", data, co)
                if chunk == -1:
                    chunk = 32
                if chunk in (16, 32) and 0 < cols < 4096 and 0 < rows < 4096 and unique < 10000:
                    # CCT count counts nonempty entries; -1 does not consume count.
                    p, seen, table = co + 20, 0, []
                    while seen < count:
                        if p + 2 > len(data):
                            raise ValueError("truncated CCT table")
                        index = struct.unpack_from("<h", data, p)[0]; p += 2
                        if index < -1 or index >= unique:
                            raise ValueError(f"invalid CCT index {index}/{unique}")
                        table.append(index); seen += index != -1
                    self.cct_offset, self.cct_end = co, p
                    self.cct, self.chunk_size = table, chunk
                    self.cct_unique, self.cct_cols, self.cct_rows = unique, cols, rows
        self.canvas = self._decode()

    @staticmethod
    def _palette(data: bytes, mode: int) -> np.ndarray:
        if mode == 3:
            return np.frombuffer(data, dtype=np.uint8).reshape(-1, 4).copy()
        a = np.frombuffer(data, dtype="<u2").astype(np.uint32)
        if mode == 0:  # BGR565: R in low bits.
            return np.stack(((a & 31) * 255 // 31, ((a >> 5) & 63) * 255 // 63,
                             ((a >> 11) & 31) * 255 // 31, np.full(a.size, 255)), axis=1).astype(np.uint8)
        if mode in (1, 2):  # Original tools use GRAB4444 for both modes.
            return np.stack(((a & 15) * 17, ((a >> 4) & 15) * 17,
                             ((a >> 8) & 15) * 17, ((a >> 12) & 15) * 17), axis=1).astype(np.uint8)
        raise ValueError(f"unsupported palette mode {mode}")

    def _decode(self) -> np.ndarray:
        if not self.data_size:
            shape = (self.height, self.width, 4) if self.format == 3 else (self.height, self.width)
            return np.zeros(shape, dtype=np.uint8)
        if self.cct is not None and self.swizzled and self.width > 16:
            ch = self.chunk_size; unit = ch * ch * self.bpp // 8
            if self.data_size != self.cct_unique * unit:
                raise ValueError("CCT unique count does not match data size")
            self.original_tiles = [self.pixel_data[i:i + unit] for i in range(0, self.data_size, unit)]
            tiles = [unpack_indices(unswizzle(t, ch * self.bpp // 8), self.bpp, ch) for t in self.original_tiles]
            cols = math.ceil(self.width / ch); rows = max(math.ceil(self.height / ch), math.ceil(len(self.cct) / cols))
            canvas = np.zeros((rows * ch, cols * ch), dtype=np.uint8)
            for logical, index in enumerate(self.cct):
                if index != -1:
                    y, x = divmod(logical, cols); canvas[y * ch:(y + 1) * ch, x * ch:(x + 1) * ch] = tiles[index]
            return canvas
        # Tiny cursors declare a 14px crop inside a 32px linear bitmap. The
        # original decoder rounds its canvas to 32 and ignores their swizzle.
        width = self.stride if self.width <= 16 and self.stride > self.width else self.width
        self.storage_width = width
        row_bytes = width * self.bpp // 8
        linear = unswizzle(self.pixel_data, row_bytes) if self.swizzled and self.width > 16 else self.pixel_data
        if self.format == 3:
            return np.frombuffer(linear, dtype=np.uint8).reshape(-1, width, 4).copy()
        return unpack_indices(linear, self.bpp, width)

    def image(self, cropped: bool = True) -> Image.Image:
        pixels = self.canvas[:self.height, :self.width] if cropped else self.canvas
        rgba = pixels if self.format == 3 else self.palette[pixels]
        return Image.fromarray(rgba, "RGBA")

    def metadata(self) -> dict:
        return {"format": self.format, "bpp": self.bpp, "swizzled": self.swizzled,
                "width": self.width, "height": self.height, "stride": self.stride,
                "data_size": self.data_size, "palette_mode": self.palette_mode,
                "palette_colors": len(self.palette) if self.palette is not None else None,
                "cct_chunk_size": self.chunk_size, "cct_entries": len(self.cct) if self.cct is not None else None,
                "cct_unique": getattr(self, "cct_unique", None), "canvas_shape": list(self.canvas.shape)}

    def encode(self, pixels: np.ndarray | None = None) -> bytes:
        a = self.canvas if pixels is None else np.asarray(pixels, dtype=np.uint8)
        if a.shape != self.canvas.shape:
            raise ValueError(f"canvas shape changed: {a.shape} vs {self.canvas.shape}")
        if not self.data_size:
            if np.any(a):
                raise ValueError("cannot populate data-less TEX")
            return self.source
        if self.cct is not None and self.swizzled and self.width > 16:
            ch = self.chunk_size; cols = a.shape[1] // ch
            tiles = list(self.original_tiles)
            lookup = {data: i for i, data in reversed(list(enumerate(tiles)))}
            new_table = []
            # Keep every original unique block, and preserve unchanged references.
            for logical in range(a.shape[0] // ch * cols):
                y, x = divmod(logical, cols); p = a[y * ch:(y + 1) * ch, x * ch:(x + 1) * ch]
                old = self.cct[logical] if logical < len(self.cct) else -1
                old_pixels = self.canvas[y * ch:(y + 1) * ch, x * ch:(x + 1) * ch]
                if np.array_equal(p, old_pixels):
                    new_table.append(old); continue
                if not np.any(p):
                    new_table.append(-1); continue
                raw = swizzle(pack_indices(p, self.bpp), ch * self.bpp // 8)
                index = lookup.get(raw)
                if index is None:
                    index = len(tiles); tiles.append(raw); lookup[raw] = index
                new_table.append(index)
            # Do not invent trailing empty CCT entries when reproducing source.
            while len(new_table) > len(self.cct) and new_table[-1] == -1:
                new_table.pop()
            if len(tiles) > 32767:
                raise ValueError("CCT exceeds signed int16 index range")
            pixel_data = b"".join(tiles)
            palette = self.source[self.palette_offset:self.cct_offset]
            cct_header = bytearray(self.source[self.cct_offset:self.cct_offset + 20])
            struct.pack_into("<H", cct_header, 8, sum(v != -1 for v in new_table))
            struct.pack_into("<H", cct_header, 12, len(tiles))
            header = bytearray(self.source[:48]); struct.pack_into("<I", header, 0x1c, len(pixel_data))
            result = (bytes(header) + pixel_data + palette + bytes(cct_header)
                      + struct.pack(f"<{len(new_table)}h", *new_table) + self.source[self.cct_end:])
            # Native TEX members are 16-byte aligned, including their CCT
            # trailers. Growing the logical table by one int16 otherwise
            # shifts every following TEX/CLUT by 2 bytes. Host roundtrips can
            # still pass, while PSP CLUT uploads use an aligned address and
            # display broken colours and tiles from that member onwards.
            if len(self.source) % 16 == 0:
                result += b"\0" * (-len(result) % 16)
            return result
        linear = a.tobytes() if self.format == 3 else pack_indices(a, self.bpp)
        data = swizzle(linear, self.storage_width * self.bpp // 8) if self.swizzled and self.width > 16 else linear
        return self.source[:48] + data + self.source[48 + self.data_size:]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--roundtrip", action="store_true")
    args = parser.parse_args(); report = []
    for path in args.files:
        rel = path.relative_to(args.root) if args.root else Path(path.name)
        bundle = Bundle.parse(path.read_bytes()); rebuilt = []
        for i, (name, payload) in enumerate(zip(bundle.names, bundle.payloads)):
            if not payload:
                report.append({"path": str(path), "index": i, "name": name, "empty": True})
                rebuilt.append(payload)
                continue
            try:
                tex = Texture(payload)
                target = args.out / rel / f"{i:03d}-{Path(name).stem}.png"
                target.parent.mkdir(parents=True, exist_ok=True); tex.image().save(target)
                encoded = tex.encode(); rebuilt.append(encoded)
                if args.roundtrip and encoded != payload:
                    raise ValueError("TEX roundtrip mismatch")
                report.append({"path": str(path), "index": i, "name": name, "preview": str(target), "roundtrip": encoded == payload, **tex.metadata()})
            except Exception as e:
                report.append({"path": str(path), "index": i, "name": name, "error": str(e)})
                rebuilt.append(payload)
        if args.roundtrip and bundle.rebuild(rebuilt) != bundle.source:
            report.append({"path": str(path), "error": "TXB roundtrip mismatch"})
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "decode-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"textures": len(report), "errors": sum("error" in r for r in report), "report": str(args.out / "decode-report.json")}))


if __name__ == "__main__":
    main()
