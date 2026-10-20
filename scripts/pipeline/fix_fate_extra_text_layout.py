#!/usr/bin/env python3
"""Insert safe line breaks into long Fate/Extra Chinese dialogue lines."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import unicodedata
from collections import defaultdict
from pathlib import Path


TOKEN_RE = re.compile(
    r"#RUBS.*?#REND"
    # One runtime-substituted servant class is an indivisible unit. Some
    # translations have an optional #CDEF immediately after its closing #.
    r"|#SVT\[[^\]]*\]\[[^\]]*\]\[[^\]]*\]#(?:#CDEF)?"
    r"|#\[[^\]]*\]\[[^\]]*\]#"
    # Keep colored names/terms together so a line break cannot split a name
    # such as 部長 between its characters.
    r"|#C\d{9}[^#]*#CDEF"
    r"|##CDEF"
    r"|#C\d{9}|#CDEF|#SP\d{2}|#FAMILY|#GIVEN"
    r"|#[A-Z][A-Z0-9_]*"
)
BREAK_AFTER = set("，。！？；：、…—,.!?;:")
SENTENCE_BREAK_AFTER = set("。！？；!?;")
NO_LINE_START = set("，。！？；：、）》】〕〉」』”’…,.!?;:)\]}>")
# 0x0126 DAT text uses the animated text-motion layout. Inserting dialogue
# line breaks changes that motion and scatters the characters across the
# loading/title card, so keep motion strings intact.
LAYOUT_KINDS = {"dialogue", "backlog", "dungeon_dialogue", "popup"}
# Semantic translations belong in the reviewed JSONL, not this layout pass.
# Keep manually laid-out stuttering and mirror-code puzzles unchanged.
SPECIAL_REWRITES: dict[str, str] = {}
PRESERVE_LAYOUT_IDS = {"706956d0c0338c73", "bb66b4b7"}


def visible_width(text: str) -> float:
    width = 0.0
    for char in text:
        east_width = unicodedata.east_asian_width(char)
        width += 0.5 if east_width in {"Na", "H", "N"} else 1.0
    return width


def token_width(token: str) -> float:
    if token.startswith("#RUBS"):
        middle = token.find("#RUBE", len("#RUBS"))
        if middle < 0 or not token.endswith("#REND"):
            return 0.0
        upper = token[len("#RUBS"):middle]
        base = token[middle + len("#RUBE"):-len("#REND")]
        # RUBS..RUBE is the small annotation; RUBE..REND is the body.
        # Account for long annotations at roughly half the body font size.
        codes = r"#C(?:\d{9}|DEF)"
        return max(
            visible_width(re.sub(codes, "", base)),
            visible_width(re.sub(codes, "", upper)) * 0.5,
        )
    if token.startswith("#SVT["):
        # The runtime substitutes one of the three servant classes here.
        return 6.0
    if token.startswith("#C"):
        text = re.sub(r"^#C\d{9}|#CDEF$", "", token)
        return visible_width(text)
    if token.startswith("#["):
        options = re.findall(r"\[([^\]]*)\]", token)
        return max((visible_width(option) for option in options), default=0.0)
    if token in {"#FAMILY", "#GIVEN"}:
        return 4.0
    if token.startswith("#SP"):
        return 1.0
    return 0.0


def split_units(line: str) -> list[tuple[str, float, bool, bool]]:
    """Return (raw, width, break-after, no-line-start) display units."""
    units: list[tuple[str, float, bool, bool]] = []
    pos = 0
    for match in TOKEN_RE.finditer(line):
        for char in line[pos:match.start()]:
            units.append((char, visible_width(char), char in BREAK_AFTER, char in NO_LINE_START))
        token = match.group(0)
        if token.startswith("#C") and token.endswith("#CDEF"):
            color_open = re.match(r"#C\d{9}", token)
            body = token[color_open.end():-len("#CDEF")] if color_open else token
            # Keep short colored names intact, but allow long colored sentences
            # to wrap. The game color controls are zero-width state changes.
            if color_open and visible_width(body) > 8:
                units.append((color_open.group(0), 0.0, False, False))
                units.extend((char, visible_width(char), char in BREAK_AFTER,
                              char in NO_LINE_START) for char in body)
                units.append(("#CDEF", 0.0, False, False))
            else:
                units.append((token, token_width(token), False, False))
        else:
            units.append((token, token_width(token), False, False))
        pos = match.end()
    for char in line[pos:]:
        units.append((char, visible_width(char), char in BREAK_AFTER, char in NO_LINE_START))
    return units


def wrap_line(line: str, max_width: float) -> tuple[str, int]:
    units = split_units(line)
    if not units:
        return line, 0
    output: list[str] = []
    breaks = 0
    active_color: str | None = None
    while units:
        used = 0.0
        fit = 0
        for index, unit in enumerate(units):
            next_width = used + unit[1]
            if next_width > max_width:
                break
            used = next_width
            fit = index + 1
        if fit >= len(units):
            output.extend(unit[0] for unit in units)
            break
        if fit == 0:
            fit = 1

        # Prefer a nearby punctuation boundary; otherwise break at the last
        # complete glyph/token that fits the text column.
        punctuation_ends = [
            index + 1 for index, unit in enumerate(units[:fit])
            if unit[2] and index + 1 >= max(1, fit - 10)
        ]
        sentence_ends = [
            index + 1 for index, unit in enumerate(units[:fit])
            if unit[0] in SENTENCE_BREAK_AFTER
            and index + 1 >= max(1, fit - 10)
        ]
        end = sentence_ends[-1] if sentence_ends else (
            punctuation_ends[-1] if punctuation_ends else fit
        )
        while end > 1 and end < len(units) and units[end][3]:
            end -= 1
        for raw, _, _, _ in units[:end]:
            output.append(raw)
            if re.fullmatch(r"#C\d{9}", raw):
                active_color = raw
            elif raw == "#CDEF":
                active_color = None
        # Each wrapped line has a balanced color span, so the next line
        # renders identically even if the game's line renderer resets state.
        output.append(("#CDEF\n" + active_color) if active_color else "\n")
        breaks += 1
        units = units[end:]
    return "".join(output), breaks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--translations", type=Path, default=Path("work/translation/text.jsonl"))
    parser.add_argument("--references", type=Path, default=Path("work/translation/refs.jsonl"))
    parser.add_argument("--max-width", type=float, default=23.0)
    parser.add_argument("--backup", type=Path, default=Path("work/translation/text.pre-layout-fix.jsonl"))
    args = parser.parse_args()

    kinds_by_id: dict[str, set[str]] = defaultdict(set)
    with args.references.open(encoding="utf-8") as source:
        for line in source:
            if line.strip():
                ref = json.loads(line)
                kinds_by_id[ref["id"]].update(ref.get("kinds", []))

    if not args.backup.exists():
        shutil.copy2(args.translations, args.backup)

    rows: list[dict] = []
    changed_rows = 0
    added_breaks = 0
    before_max = after_max = 0.0
    for line in args.translations.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["id"] in SPECIAL_REWRITES:
            row["zh_cn"] = SPECIAL_REWRITES[row["id"]]
        text = row.get("zh_cn", "")
        if (text and kinds_by_id[row["id"]] & LAYOUT_KINDS
                and not any(row["id"].startswith(key) for key in PRESERVE_LAYOUT_IDS)):
            lines = text.split("\n")
            wrapped: list[str] = []
            row_breaks = 0
            for content in lines:
                current_width = sum(unit[1] for unit in split_units(content))
                before_max = max(before_max, current_width)
                result, count = wrap_line(content, args.max_width)
                wrapped.append(result)
                row_breaks += count
                after_max = max(after_max, max(
                    (sum(unit[1] for unit in split_units(part)) for part in result.split("\n")),
                    default=0.0,
                ))
            if row_breaks:
                row["zh_cn"] = "\n".join(wrapped)
                changed_rows += 1
                added_breaks += row_breaks
        rows.append(row)

    with args.translations.open("w", encoding="utf-8", newline="\n") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(
        f"Wrapped {changed_rows} dialogue rows with {added_breaks} new line breaks "
        f"(maximum display width {args.max_width:g}; {before_max:g} -> {after_max:g})."
    )
    print(f"Original translation table backed up to {args.backup}.")


if __name__ == "__main__":
    main()
