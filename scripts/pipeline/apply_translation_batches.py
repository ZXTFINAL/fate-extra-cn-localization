#!/usr/bin/env python3
"""Merge translated {id, zh_cn} JSONL batches into the master text table."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"invalid JSON at {path}:{line_number}: {error}") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("work/translation/text.jsonl"))
    parser.add_argument("--batches", type=Path, default=Path("work/translation/batches"))
    parser.add_argument("--overwrite", action="store_true", help="allow batches to replace existing translations")
    args = parser.parse_args()

    translations: dict[str, str] = {}
    batch_paths = sorted(args.batches.glob("*.jsonl"))
    for batch_path in batch_paths:
        for item in read_jsonl(batch_path):
            entry_id = item.get("id")
            text = item.get("zh_cn")
            if not isinstance(entry_id, str) or not isinstance(text, str) or not text:
                raise ValueError(f"each batch row needs a nonempty id and zh_cn: {batch_path}")
            previous = translations.get(entry_id)
            if previous is not None and previous != text:
                raise ValueError(f"conflicting translations for {entry_id} in the batch files")
            translations[entry_id] = text

    rows = list(read_jsonl(args.source))
    ids = {row["id"] for row in rows}
    unknown = sorted(set(translations) - ids)
    if unknown:
        raise ValueError(f"batch contains {len(unknown)} IDs absent from the master table: {unknown[:5]}")

    changed = 0
    for row in rows:
        replacement = translations.get(row["id"])
        if replacement is None:
            continue
        existing = row.get("zh_cn", "")
        if existing and existing != replacement and not args.overwrite:
            raise ValueError(f"refusing to replace existing translation for {row['id']} without --overwrite")
        if existing != replacement:
            row["zh_cn"] = replacement
            changed += 1

    args.source.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=args.source.name + ".", dir=args.source.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        temporary_path.replace(args.source)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise

    total = sum(bool(row.get("zh_cn")) for row in rows)
    print(f"Merged {changed} new translations from {len(batch_paths)} batch files")
    print(f"Coverage: {total}/{len(rows)} strings ({total / len(rows):.1%})")


if __name__ == "__main__":
    main()
