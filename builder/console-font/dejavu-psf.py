#!/usr/bin/env python3
"""Build the live console fonts from DejaVu Sans Mono.

Usage: dejavu-psf.py <ttf>[,<fallback ttf>] <ter-v psf[.gz]> <output .psf> <ppem> <baseline row>

Every glyph is DejaVu's, rendered by FreeType with the fonts' own hinting as
a monochrome bitmap. kbd's Terminus at the same cell size (ter-v) supplies
only the list of characters: its 512 slots and their Unicode table, so the
font covers exactly what Terminus does. DejaVu's box drawing and blocks span
its line, one row short of the cell at these sizes; they sit on a baseline of
their own that puts the line at the top of the cell, and repeat its last row
into the row left over, so they join from cell to cell. The three shades are
drawn as the usual 25, 50 and 75 % dithers, which hinting turns into moiré.

A glyph DejaVu Sans Mono lacks comes from the fallback (DejaVu Sans). A glyph
whose ink spills out of the cell but is no wider than it moves inside; one
that is wider loses columns identical to their left neighbour, the inside of
a bar or a bowl, until it fits. A capital with tonos that is still too wide
gets its tonos above the letter's top left, in the empty rows over the cap
height. Each of those is printed, so a rebuild can be checked against
README.md; a glyph that fits none of these ways stops the build.

Usage of the outputs is in README.md; i18n.sh loads them by cell height.
"""

from __future__ import annotations

import gzip
import struct
import sys

import freetype

PSF1_MAGIC = b"\x36\x04"
PSF2_MAGIC = b"\x72\xb5\x4a\x86"

UPPER_HALF, LOWER_HALF = 0x2580, 0x2584
# The logo's half blocks, drawn in the slots of ŉ and ₧, which nothing prints.
SACRIFICED = {0x0149: UPPER_HALF, 0x20A7: LOWER_HALF}

# Terminus draws these alike and gives each pair one slot; DejaVu does not.
# Each moves to the slot of a CP437 symbol no catalog, keymap or script on
# the live ISO uses.
SPLIT = {
    0x03C0: 0x2261,  # π, shared with п        -> slot of ≡
    0x03BD: 0x2310,  # ν, shared with v        -> slot of ⌐
    0x04AF: 0x2229,  # ү, shared with γ        -> slot of ∩
    0x045B: 0x207F,  # ћ, shared with ħ        -> slot of ⁿ
    0x2013: 0x2021,  # –, shared with - and −  -> slot of ‡
}

# Characters the installer and gum print that the font has no glyph for,
# drawn with the closest glyph it has.
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

# At 8x16 hinting shrinks the dot of DejaVu's zero to one pixel, one pixel
# away from O; stretch that dot to three rows.
TALL_DOT = {(8, 16): {0x0030}}


def joins_cells(codepoint: int) -> bool:
    return 0x2500 <= codepoint <= 0x259F or codepoint in (0x2320, 0x2321)


SHADES = {
    0x2591: lambda x, y: x % 2 == 0 and y % 2 == 0,  # ░
    0x2592: lambda x, y: (x + y) % 2 == 0,  # ▒
    0x2593: lambda x, y: not (x % 2 and y % 2),  # ▓
}

# Greek capitals with tonos, and the capital without it.
TONOS = {0x0386: 0x0391, 0x0388: 0x0395, 0x0389: 0x0397, 0x038A: 0x0399,
         0x038C: 0x039F, 0x038E: 0x03A5, 0x038F: 0x03A9}


def read_font(data: bytes) -> tuple[int, int, list[bytearray], list[list[int]]]:
    if data[:2] == PSF1_MAGIC:
        mode, height = data[2], data[3]
        count, width, offset = (512 if mode & 1 else 256), 8, 4
        if not mode & 2:
            raise ValueError("font has no Unicode table")
        glyphs = [bytearray(data[offset + i * height : offset + (i + 1) * height]) for i in range(count)]
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
        glyphs = [bytearray(data[header_size + i * glyph_size : header_size + (i + 1) * glyph_size]) for i in range(count)]
        entries = data[header_size + count * glyph_size :].split(b"\xff")[:count]
        table = [[ord(c) for c in entry.split(b"\xfe")[0].decode("utf-8")] for entry in entries]
        return width, height, glyphs, table

    raise ValueError("not a PSF font")


def write_psf2(width: int, height: int, glyphs: list[bytearray], table: list[list[int]]) -> bytes:
    glyph_size = (width + 7) // 8 * height
    header = struct.pack("<8I", 0x864AB572, 0, 32, 1, len(glyphs), glyph_size, height, width)
    unicode = b"".join("".join(map(chr, codepoints)).encode("utf-8") + b"\xff" for codepoints in table)
    return header + b"".join(bytes(glyph) for glyph in glyphs) + unicode


def half_block(width: int, height: int, upper: bool) -> bytearray:
    row_bytes = (width + 7) // 8
    full = ((1 << width) - 1) << (row_bytes * 8 - width)
    return bytearray(b"".join((full if (row < height // 2) == upper else 0).to_bytes(row_bytes, "big") for row in range(height)))


def ink(face: freetype.Face, codepoint: int, width: int, baseline: int) -> list[tuple[int, int]]:
    """The glyph's pixels as (x, y) in the cell, centred on its advance."""
    face.load_char(codepoint, freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_MONO)
    glyph, bitmap = face.glyph, face.glyph.bitmap
    left = glyph.bitmap_left + (width - (glyph.advance.x >> 6)) // 2
    top = baseline - glyph.bitmap_top
    return [(left + x, top + y) for y in range(bitmap.rows) for x in range(bitmap.width)
            if bitmap.buffer[y * bitmap.pitch + x // 8] >> (7 - x % 8) & 1]


def narrow(pixels: list[tuple[int, int]], columns: int) -> list[tuple[int, int]] | None:
    """Drop `columns` columns that repeat their left neighbour, nearest the middle first."""
    xs = sorted({x for x, _ in pixels})
    column = {x: frozenset(y for px, y in pixels if px == x) for x in range(xs[0], xs[-1] + 1)}
    middle = (xs[0] + xs[-1]) / 2
    repeats = sorted((x for x in column if x - 1 in column and column[x] and column[x] == column[x - 1]),
                     key=lambda x: abs(x - middle))
    if len(repeats) < columns:
        return None
    dropped = set(repeats[:columns])
    return [(x - sum(1 for d in dropped if d < x), y) for x, y in pixels if x not in dropped]


def fit(pixels: list[tuple[int, int]], width: int) -> list[tuple[int, int]] | None:
    """Pixels moved, or narrowed and moved, into a cell `width` wide; None if they cannot be."""
    if not pixels:
        return pixels
    xs = [x for x, _ in pixels]
    span = max(xs) - min(xs) + 1
    if span > width:
        pixels = narrow(pixels, span - width)
        if pixels is None:
            return None
        xs = [x for x, _ in pixels]
    shift = -min(xs) if min(xs) < 0 else min(0, width - 1 - max(xs))
    return [(x + shift, y) for x, y in pixels]


def tonos_above(face: freetype.Face, codepoint: int, width: int, baseline: int) -> list[tuple[int, int]] | None:
    """The capital's own glyph with the tonos raised over its top left corner."""
    accented, plain = ink(face, codepoint, width, baseline), ink(face, TONOS[codepoint], width, baseline)
    body = fit(plain, width)
    if body is None:
        return None
    left = min(x for x, _ in plain)
    mark = [(x, y) for x, y in accented if x < left - 1]
    top = min(y for _, y in body)
    dx, dy = -min(x for x, _ in mark), top - 2 - max(y for _, y in mark)
    if dy > 0 or min(y for _, y in mark) + dy < 0:
        return None
    return body + [(x + dx, y + dy) for x, y in mark]


def main() -> None:
    ttfs, source, output = sys.argv[1].split(","), sys.argv[2], sys.argv[3]
    ppem, baseline = int(sys.argv[4]), int(sys.argv[5])
    data = open(source, "rb").read()
    if source.endswith(".gz"):
        data = gzip.decompress(data)
    width, height, glyphs, table = read_font(data)
    row_bytes = (width + 7) // 8

    for codepoint, donor in SPLIT.items():
        slot = next(i for i, codepoints in enumerate(table) if donor in codepoints)
        if table[slot] != [donor]:
            raise ValueError(f"U+{donor:04X} shares its glyph with {table[slot]}")
        next(codepoints for codepoints in table if codepoint in codepoints).remove(codepoint)
        table[slot] = [codepoint]
    # A shared slot is drawn from its lowest code point: Latin before Greek
    # before Cyrillic, arrows before triangles.
    table = [sorted(codepoints) for codepoints in table]

    faces = []
    for ttf in ttfs:
        face = freetype.Face(ttf)
        face.set_pixel_sizes(0, ppem)
        faces.append(face)
    # DejaVu's full block spans its line: put that line at the top of the cell.
    faces[0].load_char(0x2588, freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_MONO)
    join_baseline, line_rows = faces[0].glyph.bitmap_top, faces[0].glyph.bitmap.rows
    if line_rows > height:
        raise ValueError(f"DejaVu's line is {line_rows} rows, taller than the cell")

    report: dict[str, list[str]] = {"fallback": [], "narrowed": [], "tonos above": [], "clipped": []}
    for slot, codepoints in enumerate(table):
        if not codepoints:
            continue
        for number, face in enumerate(faces):
            codepoint = next((c for c in codepoints if face.get_char_index(c)), None)
            if codepoint is None:
                continue
            joins = joins_cells(codepoint)
            raw = ink(face, codepoint, width, join_baseline if joins else baseline)
            if joins:
                last_row = [x for x, y in raw if y == line_rows - 1]
                raw = raw + [(x, y) for y in range(line_rows, height) for x in last_row]
            pixels = fit(raw, width)
            if pixels is not None:
                break
        else:
            pixels = tonos_above(faces[0], codepoints[0], width, baseline) if codepoints[0] in TONOS else None
            if pixels is None:
                raise ValueError(f"U+{codepoints[0]:04X} fits the {width}x{height} cell in no way")
            number, codepoint, raw = 0, codepoints[0], pixels
            report["tonos above"].append(chr(codepoint))
        if number:
            report["fallback"].append(chr(codepoint))
        if raw and len({x for x, _ in pixels}) < len({x for x, _ in raw}):
            report["narrowed"].append(chr(codepoint))
        if codepoint in TALL_DOT.get((width, height), ()):
            xs = [x for x, _ in pixels]
            alone = [(x, y) for x, y in pixels if min(xs) < x < max(xs) and not
                     {(x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)} - {(x, y)} & set(pixels)]
            if len(alone) != 1:
                raise ValueError(f"U+{codepoint:04X}: expected one dot pixel, found {alone}")
            (x, y), = alone
            pixels = pixels + [(x, y - 1), (x, y + 1)]
        if codepoint in SHADES:
            pixels = [(x, y) for y in range(height) for x in range(width) if SHADES[codepoint](x, y)]
        cell = bytearray(len(glyphs[slot]))
        lost = 0
        for x, y in pixels:
            if 0 <= y < height:  # ink above or below the cell is the overhang of box drawing and blocks
                cell[y * row_bytes + x // 8] |= 0x80 >> (x % 8)
            else:
                lost += 1
        if lost:
            report["clipped"].append(f"{chr(codepoint)}:{lost}")
        glyphs[slot] = cell

    for codepoint, block in SACRIFICED.items():
        slot = next(i for i, codepoints in enumerate(table) if codepoint in codepoints)
        if table[slot] != [codepoint]:
            raise ValueError(f"U+{codepoint:04X} shares its glyph with {table[slot]}")
        glyphs[slot] = half_block(width, height, block == UPPER_HALF)
        table[slot] = [block]

    owner = {codepoint: slot for slot, codepoints in enumerate(table) for codepoint in codepoints}
    for codepoint, glyph_of in ALIASES.items():
        if codepoint not in owner and glyph_of in owner:
            table[owner[glyph_of]].append(codepoint)

    open(output, "wb").write(write_psf2(width, height, glyphs, table))
    for key, items in report.items():
        print(f"{key}: {' '.join(items) or '-'}")


if __name__ == "__main__":
    main()
