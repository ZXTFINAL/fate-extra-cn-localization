# Changelog

格式参考 Keep a Changelog。版本号采用 `0.x`：工程迭代中的 `v14` / `v15` 对应发布标签 `v0.14.0` / `v0.15.0`；从本版起标签跟工程构建号走（`v18` → `v0.18.0`；`v0.17.0` 未单独发版）。

---

## [v0.18.0] — 2026-10-20

**同步到 v18 工程状态：动作表修复、诗文回归、变更集扩容**

### Added

- 新脚本 5 个：`assemble_fate_extra_v15.py`、`audit_fate_extra_poems.py`、
  `patch_fate_extra_interaction.py`（现场动作表）、`patch_fate_extra_xmb.py`（PSP 菜单图）、
  `cmp_lzss_encoder.c`（C 参考编码器）。
- `data/translation/poem-glyph-map.json`：诗文/章节卡动画字专用别名表（与正文不是同一套）。
- `data/review/`：`merged-initial-fixes.jsonl`（1,186）、`context-lane-4-fixes.jsonl`、
  `control-restoration-fixes.jsonl`（6）、`root-manual-fixes.jsonl`（105）、
  `structural-candidates.jsonl`、v15/v16 装配报告、`v16-layout-report.txt`。
- `data/evidence/build/`：v16/v17 静态校验、v18 XMB 资源报告、v18 动作表补丁报告。
- `data/evidence/poem/`：v17 分配器增量、非诗文别名审计、修复前后对照图。

### Changed

- `data/translation/text.jsonl` → `text.v16-reviewed.post-layout.jsonl`
  （SHA-256 `9967396a…`，19,709 条非空译文；含 10 份补丁合并 4,364 处改动、
  23 宽排版 1,285 行对话 / 1,359 个换行）。
- `data/translation/glyph-map.json`：1,571 → 1,613 条别名（v16 表；2 条重分配）。
- `data/overlay/`：375 → **381 个文件**，71,900,512 → 72,180,368 字节。
  新增 6 个诗文资源（`charsel` / `modeselect` / `poem` 三个包的 `poem.bin`、`poem_font.txb`），
  4 个文件内容更新（字库与 UI 纹理）。变更集**只含 txb/bin，不含 DAT**。
- `scripts/quick/quick.py rebuild` 由两段变三段：文本重建 → 动作表注入 → 写回 ISO；
  新增 `--motion-glyph-map` 与 `data/translation/poem-glyph-map.json` 的同步。
- `scripts/validate_repo.py` 常量改为 19,711 译文 / 1,613 别名 / 381 变更文件 / 72,180,368 字节。

### Fixed

- **现场动作表仍是日文**：`話す` / `調べる` / `校舎　B1Fへ` 等 24 槽固定动作表不在文本提取范围内，
  且 v17 字库缺原生「話」字，界面只剩「す」。v18 从实际 CPK 读出 808 个场景包，
  改写 807 个非空 DAT（851 条包装条目），只替换固定哨兵后的 280 字节共用表，
  其余字节、指针与脚本不变。
- **诗文分配器回归**：v17 补分配器差量校验与非诗文别名审计，修正 16px 网格错位后的别名漂移。
- **TEX 成员对齐**：`fate_extra_texture.py` 在逻辑表增长后补齐 16 字节对齐，避免后续 TEX/CLUT
  整体偏移 2 字节导致 PSP 上花屏（宿主回环测不出来）。
- **PSP 菜单图**：`ICON0.PNG` / `PIC0.PNG` / `PIC1.PNG` 汉化并写回 ISO 外资源区。

### Notes

- 本版基线：`Fate_Extra_CN-v18.iso` 1,461,848,064 字节，内嵌 `data.cpk` 1,348,403,600 字节。
- 仓库侧已做过一次完整重建复核：4 分 24 秒产出 `data.cpk` 1,342,282,128 字节，
  与工程 v18 CPK 逐成员比对 16,961 相同 / 851 不同（差在历次增量重建留下的死字节），
  按指针解引用抽检 20,522 处可见文本 **0 差异**。详见 `data/evidence/build/v18-repro-verification.md`。
- 仍**未做 PPSSPP/实机全流程回归**；静态校验与字节回读通过不等同于可玩性验证。
- 仓库不发布 ISO；变更集 + 清单 + 脚本保证同一张原盘可重建同一份产物。

---

## [v0.16.0] — 2026-10-19

**可重建工程包：变更集 + 解包清单 + 一键重建**

这一版不加新译文，只解决"别人拿到仓库怎么快速重建"。

### Added

- `data/overlay/`：375 个改动过的二进制资源（4 个字库/小字文件 + 5 个公共界面 + 266 个
  interface + 100 个 battle），71,900,512 字节，含逐文件 SHA-256。
- `data/inventory/`：15,962 个解包文件的路径/大小/校验和（gzip JSONL，160 KB），
  用于核对自备 ISO 解出的树是否与工程基准一致。
- `scripts/quick/quick.py`：`bootstrap` / `rebuild` / `text` / `image` / `overlay` /
  `inventory` / `status` / `verify` 八个入口。
- `docs/11-quick-rebuild.md`：交接手册（三层结构、改稿流程、实测耗时、故障表）。

### Changed

- 重建路径从"重跑解包→补字→图片重排→打包"变为"套用变更集 → 打包 → 写回"，
  解包只需一次，日常改稿只走后两步。
- README 快速开始改为两条命令；手动分步降为"要改流水线本身时"的参考。
- `AGENT.md` 增加 4.0 首次接管流程；约束 2 明确为"不分发原版资源"。

### Notes

- 变更集是**改动文件**，不是原版资源；仍需自备日版 ISO。
- 不含 ISO。仓库不发布镜像，只保证"用同一张原盘能重建出同一份产物"。

---

## [v0.15.0] — 2026-10-19

**工程基线 + v15 资源预备（未生成新 ISO）**

### Added

- 完整的工程文档：总览、流水线、格式、文本、字库、诗文/ruby、UI、构建、质量、坑、时间线、方法论。
- `AGENT.md` 作业手册与 `ROADMAP.md` 路线图。
- 20 个生产脚本与 14 个审计脚本入库。
- 翻译主表 `text.jsonl`（19,711 条）、术语表、`glyph-map.json`（1,571 别名）、批次清单。
- ruby 修正 1,133 条、最终审计 JSON、字库审计与图集证据。
- 诗文复现脚本与 before/after 采样、截图拟合数据。
- UI 配置（启动声明、274 小图、191 页教程）与回环验证报告。
- v15 构建报告（1,186 文本 / 743 DAT / 375 资源 / 871 CPK 路径）。

### Changed

- ruby 字库 219 → 518 字 / 3 页，保留原 219 槽，沿用正差别名。
- UI 覆盖扩展到 371 个 TXB、2,598 个 TEX。
- 语境校对：开场 641 ID 完成，lane 1 读到 1,452 / 6,356。

### Fixed

- 诗文 16×16 → 14×14 网格，消除章节卡碎字（396 字，0 空字/错位）。
- ruby 上下层同文 337 → 0；结构缺损 2 → 0；组数不符 0。
- 长译文整槽清零，消除中文尾部日文残字。
- ISO 文件名大小写恢复，避免黑屏。

### Known issues

- v15 未回写 ISO；ruby 第三页运行时上限未证实。
- 教程截图内部 UI 仍保留日文。
- lane 2/3 未开始。
- 视频字幕、场景看板、PSP 系统对话未盘点。

---

## [v0.14.0] — 2026-10-19

**首个完整可运行 ISO**

### Added

- `Fate_Extra_CN-v14.iso`：1,386,442,752 字节。
- SHA-256：`81c651b5ddbefc9ace750640ea41ea2f1a077f2cb32a7b33cbe61349fdcb7631`。
- 全量文本、正文 4,096 字库、诗文 14×14 修复、首批 UI 图片。

### Fixed

- 诗文章节卡按 14×14 / 324 字每页重建。
- 12 份 `poem.pak` 副本统一替换。
- 章节卡停留时间延长。

---

## [v0.9.0] — 2026-10-18

**版面与章节卡**

### Added

- 对话框 24 全角字换行、标点避头、溢出修复。
- 章节卡 timing 调整脚本。
- 诗文 14px 采样与对比图。

### Fixed

- 教室/2-A 场景对齐。
- 颜色码范围与角色名对齐。
- motion 文本不再被插入换行。

---

## [v0.5.0] — 2026-10-17

**正文可显示**

### Added

- CP932 用户区别名分配（1,571 字）。
- 中文 W6 字形渲染（16×16，13px）。
- 字库压缩：4,611 → 4,096，删除 515 个无引用日文字。
- 难度选择页文本表与烘焙标签。

### Fixed

- 中文方块/缺字。
- 字库超出运行时 4,096 上限。

---

## [v0.1.0] — 2026-10-16

**格式打通**

### Added

- CPK/PAK/CMP 解包与重打包。
- DAT 文本转储（9 类操作码）、稳定 ID。
- 首版翻译批次与术语表。
- ISO9660 写回、文件名大小写修复。

### Fixed

- 短译文尾部残留。
- 长译文指针重定向。

---

## 未发布

### Planned

- v15 ISO 构建与实机回归。
- lane 2/3 全量语境校对。
- 教程截图内部 UI 补译。
- 视频字幕/场景看板盘点。
- v1.0.0 正式发布。
