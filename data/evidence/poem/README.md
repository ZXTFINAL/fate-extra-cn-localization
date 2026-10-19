# Poem font mismatch: independent static audit

This audit did not start the game or an emulator. It sampled actual asset bytes and compared the resulting fragments with the user's existing screenshot.

## Root cause

The original poem atlas packs **14 × 14 pixel cells, 18 columns × 18 rows per 256 × 256 page**, or **324 glyphs per page**. The production builder previously reused the main dialogue font's **16 × 16 cells, 16 columns, 256 glyphs per page**. It reordered and rendered the poem atlas with those dimensions, while the game continued to sample with the original poem grid.

The original atlas independently demonstrates this packing: indices 0–17 occupy the first row (`,` through `L`), indices 18–35 occupy the second row (`M` through `n`), and index 36 (`r`) begins the third row. The original first row's ink occupies Y = 1–12, with Y = 13 blank and the next row beginning at Y = 14. The runtime initialization disassembly independently establishes 14 × 14 cells.

The TEX header describes the **whole texture** as 256 × 256, T4, swizzled. It does not say its glyph cells are 16 pixels. T4 swizzling itself is correct; the glyph grid copied from the main font is wrong.

For example, the current poem table maps the bytes `95 BD` (alias `平`) to index 350. The old builder put that glyph at page 1, X = 224, Y = 80 (256 glyphs/page, 16 px pitch). The game reads page 1, X = 112, Y = 14 (324 glyphs/page, 14 px pitch). This samples pieces of other characters.

## Reproduction from actual assets

`reproduce.py` reads the retained binary snapshots in `before-assets/`, including the actual `0000.dat`, and resolves the pointers at offsets 9840 and 9904, resolves each encoded key through the actual `poem.bin`, and samples its actual `poem_font.txb` with the original 14 px grid. No glyph substitutions were invented for the reproduction.

The two byte strings resolve through the table to:

- 随后，开场的钟声响起。
- 平凡的日常，宛如一捧砂金一般。

The resulting wrong fragments are `opening-runtime.png` and `ordinary-runtime.png`. Samples span 13 texels within each 14-pixel atlas cell and are assembled tightly for fragment comparison. This does not simulate per-character animation layout or timings. Each reproduces the corresponding row of the user's screenshot `/Users/zhaoxiangting/Desktop/截屏2026-10-19 12.23.53.png`.

`match_screenshot.py` compared resized reproduced pixels against the screenshot. The optimal grayscale normalized correlations are **0.96088** for the first row (X = 492, Y = 590, 265 × 26 px) and **0.96510** for the second row (X = 492, Y = 624, 360 × 26 px). The common scale is approximately 1.84; the screenshot's game surface width of 879 over native PSP width 480 yields 1.83125. This confirms the same fragments, rather than a different general font defect.

Full key/index/page/UV coordinates are in `coordinates.json`; screenshot fitting results are in `screenshot-match.json`.

## Independent sampling after fix

The final corrected font is retained in `after-assets/` with its lookup table and glyph map, so the audit stays reproducible after intermediate builds are deleted. It was sampled with the same 14 px grid and same actual DAT bytes. The two rows now contain the complete expected characters in `opening-after.png` and `ordinary-after.png`.

`before-after-static.png` shows the wrong and corrected results under the same sampling rules and is explicitly labelled as static resource sampling, not an emulator screenshot. It verifies this specific font-grid fault; it does not claim runtime verification of loading animation or physical PSP behavior.

The final font contains all 396 translated glyphs: 0 empty glyphs, 0 mapping mismatches, and 0 cells with nonzero pixels in the protected last row or column. `final-atlas-check.json` records these results and SHA-256 hashes of all retained inputs. The raster is 13 × 13 padded into a 14 × 14 cell.

To regenerate the error fragments, corrected samples, comparison image, and integrity report, run `reproduce.py` with a Python environment containing Pillow. It uses only small files in this audit directory; it does not depend on deleted build folders or mutable production helpers.
