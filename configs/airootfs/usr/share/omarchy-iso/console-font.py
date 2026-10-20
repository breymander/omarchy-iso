#!/usr/bin/python
"""Terminus for the live console, plus the half blocks the Omarchy logo needs,
drawn in the slots of ŉ and ₧, which nothing the installer prints uses.

Usage: console-font.py <terminus .psf[.gz]> <output .psf>
"""

from __future__ import annotations

import gzip
import struct
import sys
from pathlib import Path

PSF1_MAGIC = b"\x36\x04"
PSF2_MAGIC = b"\x72\xb5\x4a\x86"

UPPER_HALF, LOWER_HALF = 0x2580, 0x2584
# Glyphs that draw only this one character, so nothing else loses its glyph.
SACRIFICED = {0x0149: UPPER_HALF, 0x20A7: LOWER_HALF}

# Characters the installer and gum print, drawn with Terminus's closest glyph.
ALIASES = {
    0x256D: 0x250C,  # ╭ ┌  gum's rounded borders
    0x256E: 0x2510,  # ╮ ┐
    0x256F: 0x2518,  # ╯ ┘
    0x2570: 0x2514,  # ╰ └
    0x2501: 0x2500,  # ━ ─
    0x2503: 0x2502,  # ┃ │
    0x2593: 0x2592,  # ▓ ▒  gum's pulse spinner
    0x2713: 0x221A,  # ✓ √
    0x02BB: 0x2018,  # ʻ ‘  Uzbek's oʻ and gʻ
}


def read_font(data: bytes) -> tuple[int, int, list[bytes], list[list[int]]]:
    if data[:2] == PSF1_MAGIC:
        mode, height = data[2], data[3]
        count, width, offset = (512 if mode & 1 else 256), 8, 4
        if not mode & 2:
            raise ValueError("font has no Unicode table")
        glyphs = [data[offset + i * height : offset + (i + 1) * height] for i in range(count)]
        table: list[list[int]] = [[] for _ in range(count)]
        position, index, in_sequence = offset + count * height, 0, False
        while index < count and position + 1 < len(data):
            value = struct.unpack_from("<H", data, position)[0]
            position += 2
            if value == 0xFFFF:
                index, in_sequence = index + 1, False
            elif value == 0xFFFE:
                in_sequence = True
            elif not in_sequence:
                table[index].append(value)
        return width, height, glyphs, table

    if data[:4] == PSF2_MAGIC:
        _, _, header_size, flags, count, glyph_size, height, width = struct.unpack_from("<8I", data)
        if not flags & 1:
            raise ValueError("font has no Unicode table")
        glyphs = [data[header_size + i * glyph_size : header_size + (i + 1) * glyph_size] for i in range(count)]
        table = [[] for _ in range(count)]
        entries = data[header_size + count * glyph_size :].split(b"\xff")[:count]
        for index, entry in enumerate(entries):
            table[index] = [ord(c) for c in entry.split(b"\xfe")[0].decode("utf-8")]
        return width, height, glyphs, table

    raise ValueError("not a PSF font")


def half_block(width: int, height: int, upper: bool) -> bytes:
    row_bytes = (width + 7) // 8
    full = ((1 << width) - 1) << (row_bytes * 8 - width)
    rows = [full if (row < height // 2) == upper else 0 for row in range(height)]
    return b"".join(row.to_bytes(row_bytes, "big") for row in rows)


def patch(width: int, height: int, glyphs: list[bytes], table: list[list[int]]) -> None:
    owner = {codepoint: index for index, codepoints in enumerate(table) for codepoint in codepoints}
    for codepoint, block in SACRIFICED.items():
        index = owner[codepoint]
        if table[index] != [codepoint]:
            raise ValueError(f"U+{codepoint:04X} shares its glyph with {table[index]}")
        glyphs[index] = half_block(width, height, block == UPPER_HALF)
        table[index] = [block]
    for codepoint, glyph_of in ALIASES.items():
        if codepoint not in owner and glyph_of in owner:
            table[owner[glyph_of]].append(codepoint)


def write_psf2(width: int, height: int, glyphs: list[bytes], table: list[list[int]]) -> bytes:
    glyph_size = (width + 7) // 8 * height
    header = struct.pack("<8I", 0x864AB572, 0, 32, 1, len(glyphs), glyph_size, height, width)
    unicode = b"".join("".join(map(chr, codepoints)).encode("utf-8") + b"\xff" for codepoints in table)
    return header + b"".join(glyphs) + unicode


def main() -> None:
    source, output = Path(sys.argv[1]), Path(sys.argv[2])
    data = source.read_bytes()
    if source.suffix == ".gz":
        data = gzip.decompress(data)
    width, height, glyphs, table = read_font(data)
    patch(width, height, glyphs, table)
    output.write_bytes(write_psf2(width, height, glyphs, table))


if __name__ == "__main__":
    main()
