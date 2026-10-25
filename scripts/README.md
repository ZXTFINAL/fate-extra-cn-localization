# 脚本索引

三类脚本：

- `quick/`：日常入口，封装成"两条命令重建 + 改稿即重建"，不改变底层逻辑；
- `pipeline/`：生产链路，输入输出稳定，可重复运行；
- `audit/`：审计/审校辅助，部分带一次性研究假设与硬编码路径，运行前先读源码。

所有 Python 脚本用 Python 3.11+。Swift 脚本用于 macOS 字形渲染（AppKit）。

---

## quick

| 命令 | 作用 |
|---|---|
| `quick.py bootstrap` | ISO → 取 `data.cpk` → 解包 → 铺译文 → 生成 `refs.jsonl` → 核对解包清单 |
| `quick.py rebuild` | 应用语义审校与最终对话排版账本、合并 297 条从者对白 → 同步变更集 → 重建 CPK → 写回 ISO，产出构建报告 |
| `quick.py text list/find/set/replace/check/diff` | 译文定位、改写、字库覆盖检查、相对主表 diff |
| `quick.py image decode/apply/list` | 纹理预览、按配置回写 |
| `quick.py overlay sync/verify` | 变更集清单重算与逐文件校验 |
| `quick.py inventory verify` | 解包树与基准清单比对 |
| `quick.py status` / `verify` | 工作区状态 / 产物校验 |

---

## pipeline

| 脚本 | 作用 | 主要输入 | 主要输出 |
|---|---|---|---|
| `extract_fate_extra.py` | 读取/解包 CPK、PAK、CMP | `data.cpk` | `work/extracted/`、`manifest.json` |
| `dump_fate_extra_text.py` | 沿 DAT 操作码转储文本与引用 | `packages/`、`cpk/day/` | `text.jsonl`、`refs.jsonl` |
| `apply_translation_batches.py` | 合并翻译批次到主表 | `text.jsonl`、`batches/` | 合并后的 `text.jsonl` |
| `fix_fate_extra_text_layout.py` | 插入安全换行、保护 motion | `text.jsonl`、`refs.jsonl` | 带换行的 `text.jsonl` |
| `patch_fate_extra_font.py` | 分配 CP932 别名、渲染正文图集 | 译文、`kanzi.bin`、`font.txb` | `glyph-map.json`、新字库 |
| `compact_fate_extra_font.py` | 扩展到 4,096 内，删无引用日文字 | 扩展字库、译文 | 16 页字库、压缩报告 |
| `render_font_glyphs.swift` | 用 Hiragino W6 渲染字格位图 | 字符列表 | 256 字节/字 alpha 位图 |
| `render_ui_title.swift` | 渲染 UI 标题位图 | 文本、尺寸、字体 | RGBA 原始位图 |
| `patch_fate_extra_poem_font.py` | 重建诗文 14×14 字库 | 译文、`poem.bin`、`poem_font.txb` | 诗文 PAK 覆盖 |
| `patch_fate_extra_annotation_fonts.py` | ruby 9×9 字库扩容到 518 字/3 页 | 正文资源、译文、`glyph-map` | `ruby.bin/txb`、v15 映射、报告 |
| `patch_fate_extra_poem_timing.py` | 延长章节卡停留 | DAT | 修改后的 DAT |
| `patch_fate_extra_ui.py` | 难度选择页文本表 + 烘焙标签 | `modeselect` 包 | 覆盖资源 |
| `patch_fate_extra_image_text.py` | 按配置替换 TEX 文字矩形 | 配置 JSON、TXB | 覆盖 TXB、预览 PNG |
| `patch_fate_extra_fixed_ui.py` | 翻译固定槽位的主菜单说明与确认按钮 | `fixed-ui-text-patches.json`、源 BIN、`glyph-map.json` | 固定长度 UI BIN 覆盖、SHA-256 报告 |
| `fate_extra_texture.py` | TXB/TEX 无损读写库 | TXB 字节 | `Bundle`/`Texture` 对象 |
| `build_fate_extra.py` | 应用译文、重写指针、重建 CPK | 译文、引用、字库、源 CPK | `data.cpk` |
| `refresh_fate_extra_font.py` | 只刷新字体与难度包 | 已有翻译 CPK | 新 CPK |
| `refresh_fate_extra_incremental.py` | 在已有翻译 CPK 上应用文本增量 | 新旧译文、引用、CPK | 新 CPK |
| `stage_fate_extra_revision.py` | 对旧 CPK 定点替换，支持 `--prepare-only` | 旧 CPK、新旧文本/映射、覆盖层 | 覆盖层 + `build-report.json`（或新 CPK） |
| `embed_fate_extra_cpk.py` | 把 CPK 写回 ISO9660 | 原 ISO、新 CPK | 新 ISO |
| `patch_fate_extra_iso_case.py` | 恢复小写 `data.cpk` 标识 | ISO | 修改后的 ISO |
| `build_fate_extra_scene_pack.py` | 从日版 PPSSPP 高清纹理目录整理非文字场景纹理 | NPJH50247 `textures.ini` 与映射图 | xxh64 场景包与清单 |
| `install_fate_extra_scene_pack.py` | 将场景包安全合并进现有 NPJH50247 纹理目录 | 场景包 + PPSSPP 纹理目录 | 备份后的 `textures.ini` 与 `SceneHD/` |
| `build_fate_extra_combined_hd_pack.py` | 将 v1.1 场景包与中文 UI 包映射合并为一份 `textures.ini`，UI 映射覆盖相同哈希 | 场景 ZIP + UI ZIP | 单一配置的 PPSSPP 合并纹理 ZIP、映射清单与校验报告 |
| `install_fate_extra_hd_pack.py` | 安装简体中文高清字库/UI 覆盖层，兼容 quick 与 xxh64 | UI 包 + PPSSPP 纹理目录 | `CN_HD/` 与合并后的哈希表 |
| `build_fate_extra_hd_pack.py` | 从纹理抓取、场景资源和 UI 构建 8 倍汉化纹理包 | TXB 纹理包、渲染配置、运行时抓取索引 | 8 倍 UI/正文图与 quick/xxh64 映射 |
| `import_fate_extra_title_startup_hd.py` | 从 Fate-Extra-HD 日版纹理中按原始哈希导入标题页与开机厂商标志 8 倍图块；排除带韩文副标题的 3 个 logo 图块 | 原始 TXB + HD `NPJH50247` pack | UI 包中的 `OpeningHD/`、双哈希映射与导入报告 |
| `render_hd_font_glyphs.swift` | 以矢量字体栅格化高清正文汉字页 | UTF-8 字符清单 | 2048×2048 正文字库页 |
| `ui_glyph_styles.py` | 按组件保留日文字体风格、基线与字形宽度 | 字符、组件样式、字体配置 | 高分辨率 RGBA 字形 |

### 依赖关系

```
extract_fate_extra
   └─ dump_fate_extra_text
        └─ apply_translation_batches
             └─ fix_fate_extra_text_layout
                  └─ prepare_build_translations
                       └─ final dialogue layout ledger
                            └─ patch_fate_extra_font
                                 └─ compact_fate_extra_font
                                      └─ build_fate_extra
                                           └─ embed_fate_extra_cpk
```

`fate_extra_texture` 被 `patch_fate_extra_image_text` 与 UI 配置脚本引用；`patch_fate_extra_annotation_fonts` 引用 `patch_fate_extra_ui` 的 PAK 读写函数。

### 最小示例

```sh
# 正文补字
python3 scripts/pipeline/patch_fate_extra_font.py \
  --translations data/translation/text.jsonl \
  --refs work/translation/refs.jsonl \
  --extract-root work/extracted/packages \
  --out-root work/build/assets/packages/pack/PRELOAD \
  --glyph-map data/translation/glyph-map.json \
  --allocations work/translation/glyph-allocations.jsonl \
  --renderer scripts/pipeline/render_font_glyphs.swift
```

---

## audit

这些脚本来自实际审计过程，保留原样以便复现报告。部分硬编码 `work/...` 或桌面截图路径，**不要直接当生产工具**。

| 脚本 | 用途 | 说明 |
|---|---|---|
| `reproduce.py` | 复现诗文碎字、验证修复后采样 | 只读 `data/evidence/poem/` 小快照；需 Pillow |
| `match_screenshot.py` | 截图相关性拟合 | 硬编码桌面截图路径，结果见 `screenshot-match.json` |
| `ocr.swift` | macOS Vision 批量 OCR | 输入 JSON 路径列表，输出文字 + bbox |
| `make-ui-config.py` | 生成 274 小图替换配置 | 需 `all-ui/decode-report.json` |
| `make-tutorial-config.py` | 生成 191 页教程配置 | 依赖翻译结果 A/B |
| `build-translation-result-A.py` | 汇总独图译文 | 生成 `translation-result-A.jsonl` |
| `build-context-opening-review.py` | 开场三场景按源顺序排列 | 产出 665 引用审阅表 |
| `build-context-shard-plan.py` | 全量分片计划 | 609 包 + `manifest.json` |
| `lane1-review-state.py` | lane 1 进度/修正记录 | 只记真实读过的 ID |
| `lane2-review-helper.py` | lane 2 分片读取辅助 | `read` 子命令 |
| `append-context-review.py` | 把批量审阅结果并入进度 | 供 lane 3 使用 |
| `build-ruby-fixes.py` | 生成 ruby 候选修正 | 含 929 组合分类规则 |
| `finalize-ruby-fixes.py` | 人工补丁 + 最终 1,133 条 | 依赖候选修正 |
| `ruby-reading-manual.py` | 取消普通注音后的残词修复 | 逐句替换表 |
| `audit-japanese-residuals.py` | 扫描主剧情、动态分支、从者角色包对白和 UI 译文中的日文假名 | 合并主剧情审校补丁；验证 297 条从者译文与来源清单 ID 对齐；输出 JSON 报告 |

### 运行审计脚本的前提

- 工作目录为工程根；
- `work/translation/text.jsonl`、`refs.jsonl` 已生成；
- 报告类脚本会写 `work/translation/review-*/`，不会改主表（`build-ruby-fixes.py` 只写候选文件）。

### 复现诗文审计

```sh
cd data/evidence/poem
python3 ../../../scripts/audit/reproduce.py
```

脚本只读同目录的 `before-assets/`、`after-assets/` 与 `audit.json`，不依赖旧构建。

---

## 新增脚本约定

1. 生产脚本放 `pipeline/`，审计脚本放 `audit/`；
2. 文件头写一行 `"""用途。"""`；
3. CLI 参数全部有 `help`；
4. 默认输出到 `work/`，不覆盖源；
5. 有报告就写 JSON，字段稳定；
6. 在本文件登记：作用、输入、输出、依赖；
7. 不在脚本里硬编码译文或文案（放配置/数据）。
