# 数据说明

本目录保存**可公开的翻译与审计数据**，不含游戏资源。

---

## translation/

| 文件 | 说明 |
|---|---|
| `text.jsonl` | 主翻译表，19,711 行。字段：`id / jp / jp_bytes_hex / zh_cn / reference_count` |
| `glyph-map.json` | 1,571 个"汉字 → CP932 用户区别名"映射 |
| `glyph-allocations.jsonl` | 别名分配流水（目标字、索引、时间） |
| `batches-manifest.json` | 211 个翻译批次的文件、条数、首尾 ID |
| `batch-001.sample.jsonl` | 批次格式样例 |

### `id` 规则

```
id = sha256(原始 Shift-JIS 字节).hexdigest()[:16]
```

- 与文件位置无关；
- 同一句在多文件复用只占一行；
- **不要修改 `jp` 字段**，否则 ID 变化、批次失联。

### 未入库的中间产物

| 文件 | 原因 | 如何生成 |
|---|---|---|
| `refs.jsonl`（约 70 MB） | 体积大、可由源重建 | `dump_fate_extra_text.py` |
| `batches/001..211.jsonl` | 与主表重复；保留清单与样例 | 见 `batches-manifest.json` |
| `text.pre-*.jsonl` | 历史快照 | 各阶段脚本自动备份 |

---

## review/

| 文件 | 说明 |
|---|---|
| `ruby-fixes.jsonl` | 1,133 条 ruby 文本修正（`id / zh_cn / reason`） |
| `ruby-final-audit.json` | 结构统计、缺字表、哈希 |
| `ruby-audit.md` | ruby 文本审计结论与证据 |
| `ruby-font-audit.md` / `.json` | 小字库格式、格尺寸、扩容方案 |
| `ruby-font-atlas.png` | 原小字图集观察图 |
| `context-opening-review.md` | 开场三场景语境校对报告 |
| `context-opening-fixes.jsonl` | 59 条开场修正 |
| `context-lane-1-fixes.jsonl` | lane 1 的 138 条修正 |

### 修正文件格式

```json
{"id":"...","zh_cn":"...","reason":"依据原文「彼女」与前句指代，改为她"}
```

`reason` 必须可复核，不写"润色"。

---

## evidence/

### poem/

| 文件 | 说明 |
|---|---|
| `README.md` | 诗文网格审计（英文） |
| `audit.json` | 目标句、字形索引、页/UV、成员哈希 |
| `coordinates.json` / `after-coordinates.json` | 修复前后逐字坐标 |
| `final-atlas-check.json` | 396 字、0 空字、0 错位 |
| `screenshot-match.json` | 与截图的相关性 0.96088 / 0.96510 |
| `before-after-static.png` | 错误采样 vs 修复采样 |
| `before-assets/` / `after-assets/` | 最小复现快照（DAT/poem.bin/poem_font.txb） |

复现：`python3 scripts/audit/reproduce.py`（在 `data/evidence/poem` 下运行）。

### ui/

| 文件 | 说明 |
|---|---|
| `image-localization-audit.md` | UI 本地化审计全文 |
| `image-text-patches.json` | 启动虚构声明配置 |
| `ui-text-patches.json` | 274 小图 + 260 别名包配置 |
| `tutorial-text-patches.json` | 191 页教程配置 |
| `final-validation.json` | 回环与像素校验 |
| `remaining-ui-candidates.json` | OCR 命中但未处理的条目与分类 |
| `before-after-proof.png` | 修改前后对比 |

### ruby/

| 文件 | 说明 |
|---|---|
| `annotation-preview.png` | 新字在 9×9 槽中的预览 |
| `new-ruby-glyphs.png` | 299 个新增字预览 |

### context/

| 文件 | 说明 |
|---|---|
| `shard-plan-manifest.json` | 609 个审阅包、19,711 ID 的分片清单 |

---

## build/

| 文件 | 说明 |
|---|---|
| `build-report-v15.json` | v15 增量修订报告（1,186 文本 / 743 DAT / 375 资源） |
| `font-compaction-report.json` | 4,611 → 4,096，删除 515 个无引用日文字 |

---

## 数据完整性

| 对象 | 值 |
|---|---|
| `text.jsonl` 行数 | 19,711 |
| 非空译文 | 19,709 |
| 唯一 ID | 19,711 |
| `glyph-map.json` 条目 | 1,571 |
| ruby 修正 | 1,133 |
| v15 翻译表 SHA-256 | `2494980a54c895c9bf75a6d424bc86ade73b81f303f208d1459f1d8a6ac64fcf` |

`scripts/validate_repo.py` 可复核上述计数与 JSON 合法性。
