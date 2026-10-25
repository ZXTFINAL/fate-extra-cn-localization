#!/usr/bin/env python3
"""Build the style-specific bitmap glyph library used by baked UI art."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ui_glyph_styles import build_atlas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, nargs="?", default=Path("data/evidence/ui/ui-text-patches.json"))
    parser.add_argument("--png", type=Path, default=Path("data/evidence/ui/ui-style-glyph-atlas.png"))
    parser.add_argument("--metadata", type=Path, default=Path("data/evidence/ui/ui-style-glyph-atlas.json"))
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    print(json.dumps(build_atlas(config, args.png, args.metadata), ensure_ascii=False))


if __name__ == "__main__":
    main()
