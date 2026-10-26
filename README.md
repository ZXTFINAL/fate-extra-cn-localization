# Fate/Extra 简体中文汉化工程

《Fate/Extra》（PSP 日版，`NPJH-50247`）的简体中文汉化工程记录。本仓库保存**全过程文档、方法论、可复现脚本、翻译主表、术语表、变更集与审计证据**。除 `data/overlay/` 下 584 个改动文件与 `data/evidence/` 下的最小审计切片外，不包含游戏本体、ISO 或未修改的原始资源。

> 目标不是"能跑就行"的补丁，而是可审计、可复现、可迭代的汉化流水线：每一条改动都能追溯到源字节、脚本和验证记录。

---

## 当前状态

| 模块 | 状态 | 关键数字 |
|---|---|---|
| 文本提取 | 完成 | CPK 5,824 条目 → 处理 2,297 条 → 解包 2,240 个包 |
| 文本翻译 | 完成 | 19,711 条唯一文本，19,709 条非空译文（余 2 条原文本身是全角空白） |
| 正文补字 | 完成 | 1,640 个生僻字/标点分配 CP932 用户区别名；字库压缩回 4,096 字 / 16 页 |
| 诗文（poem）字库 | 完成 | 14×14 格、324 字/页；396 个中文字形，修正 16px 网格错位；v17 补分配器回归审计 |
| 注释小字（ruby） | 完成并入 v15 | 1,133 条文本修正；小字表 219 → 518 字 / 3 页 |
| UI 图片 | 完成并入 v15 | 371 个 TXB、2,598 个 TEX 变更；191 页教程 + 274 个小图 |
| 现场动作表 | v18 修复 | 807 个场景 DAT / 851 条包条目；24 槽固定动作表（对话/调查/前往…）汉化 |
| 完整 ISO | v1.3 已发布 | 标准 ISO 与 PPSSPP 专用 ISO 已列入 [GitHub Release](https://github.com/ZXTFINAL/fate-extra-cn-localization/releases/tag/v1.3)；不入 Git |
| 变更集 | v1.3 | 以仓库中的可重建变更集为准；含问题单修复及上下文审校来源追踪 |
| 可重建工程 | v1.3 | 使用 `bootstrap` + `rebuild` 重建；发布校验值见 Release 资产 |
| 唯一 ID 首轮主语境审校 | 完成 | 19,711 / 19,711；开场 641 + 后续 19,070。lane 4 补完前三 lane 剩余的 6,102 条，不重复计入总数 |

**结论边界**：v1.3 修正 Issue #2 中把「男子トイレだ。」误译为布告栏的错误，并让构建审校补丁必须带可核对的原文位置；
高清字库与纹理映射按本版最终 CPK 重建，纹理包清单记录对应 CPK SHA-256，避免 ISO 与纹理包版本错配。
唯一 ID 的首轮主语境审校已覆盖 19,711 / 19,711；每个唯一 ID 至少读过一个指定主位置。这个统计不等于 408,796 处引用、所有重复使用语境、分支和图片内文字都逐处核完，仍可能有语义或图像文字遗漏。v1.3 对 ISO/CPK 与 ZIP/纹理映射做了静态回读，**未做 PSP 实机或 PPSSPP 全流程运行测试**；PPSSPP 用户报告的迷宫蓝屏/黑屏尚未复现，不作为本版已修复项。Release 中的 ISO 是本项目基于日版素材编译的简体中文修改版，不是官方镜像；原游戏与素材版权归各自权利人所有。详细边界见 [ROADMAP.md](ROADMAP.md)。

---

## 仓库结构

```
fate-extra-cn/
├── README.md                 入口与状态总览
├── ROADMAP.md                路线图、已完成/进行中/未开始
├── AGENT.md                  给 AI 代理与协作者的作业手册
├── CHANGELOG.md              版本变更记录
├── docs/
│   ├── 00-overview.md        项目边界与总体架构
│   ├── 01-pipeline.md        端到端流水线与阶段产物
│   ├── 02-formats.md         CPK/PAK/CMP/DAT/TXB/字库格式
│   ├── 03-text-pipeline.md   文本提取、翻译、指针重写
│   ├── 04-font-pipeline.md   正文补字与字库压缩
│   ├── 05-poem-and-ruby.md   诗文格与双层表记
│   ├── 06-ui-images.md       UI 图片本地化
│   ├── 07-build-and-verify.md 打包、ISO 嵌入与验证
│   ├── 08-quality-review.md  语境校对与质量流程
│   ├── 09-pitfalls.md        踩坑清单（症状/根因/修法）
│   ├── 10-timeline.md        按日期的工作记录
│   ├── 11-quick-rebuild.md   一键重建与交接手册
│   └── methodology.md        可迁移的方法论
├── iso/                      放自备正版 ISO（不入库）
├── scripts/
│   ├── quick/                一键重建与快速编辑（quick.py）
│   ├── pipeline/             25 个生产脚本（含 2 个 Swift 渲染器、1 个 C 参考编码器）
│   └── audit/                14 个审计/审校辅助脚本
├── data/
│   ├── overlay/              变更集：584 个改过的二进制资源 + 清单
│   ├── inventory/            解包树清单（15,962 个文件的路径/大小/校验和）
│   ├── glossary-GLOSSARY.md  术语表
│   ├── translation/          主翻译表、字库映射、批次清单
│   ├── review/               ruby 与语境修正结果
│   ├── evidence/             诗文/UI/ruby/语境/构建审计证据
│   └── build/                v15–v1.3 构建报告与静态校验
└── releases/                 各版本发布说明
```

> `work/` 是本地工作区（解包树、引用表、构建产物），由脚本生成，不入库。

---

## 快速开始

### 依赖

- Python 3.11+；重建只需标准库，处理纹理时需 `Pillow`、`numpy`
- 自备日版 ISO（`NPJH-50247`）
- macOS 仅在**重新生成字形**时才需要（Swift/AppKit 渲染）；只做重建和改稿不需要
- 测试建议 PPSSPP

### 两条命令重建（推荐）

仓库已经带好译文主表、两套字库映射和 584 个改过的二进制资源，**不需要重跑补字和图片重排**：

```sh
# 1. 把正版日版 ISO 放到 iso/（或 --iso 指定），从零展开工作区
python3 scripts/quick/quick.py bootstrap --iso iso/original.iso

# 2. 重建 CPK（文本 → 动作表 → 打包）并写回 ISO
python3 scripts/quick/quick.py rebuild
```

`rebuild` 内部是四段：套用变更集 → `build_fate_extra.py` 把 `text.jsonl` 写进 1,245 个 DAT →
`patch_fate_extra_interaction.py` 生成动作表覆盖层、再用 `stage_fate_extra_revision.py` 压进 CPK
（807 个场景包的 24 槽固定动作表）→ `embed_fate_extra_cpk.py` 写回 ISO。
动作表必须在文本之后，否则会被重建覆盖回日文。

产物：`work/build/Fate_Extra_CN.iso`，附 `work/build/quick-build-report.json`（含各阶段 SHA-256）。

`bootstrap` 会做四件事：从 ISO 里直接取出 `PSP_GAME/USRDIR/data.cpk`（不挂载、不改原盘）→
解包 2,297 个 DAT/PAK/CMP → 铺好译文与字库映射 → 按 `data/inventory/` 核对解包树。

### 日常改稿

```sh
python3 scripts/quick/quick.py text find "セイバー"          # 定位
python3 scripts/quick/quick.py text set --id <ID> --zh "……" # 改写（自动查字库覆盖）
python3 scripts/quick/quick.py rebuild                       # 重建 CPK 并写回 ISO（约 11 分钟）
python3 scripts/quick/quick.py text diff                     # 相对主表改了哪些
```

改图：`image decode --package <包路径>` 导出预览 → `image apply --config <补丁配置>` 回写 →
`overlay sync` 更新清单 → `rebuild`。详见 [docs/11-quick-rebuild.md](docs/11-quick-rebuild.md)。

### 手动分步（要改流水线本身时）

```sh
# 1. 读取 CPK 目录 / 解包 DAT、PAK、CMP
python3 scripts/pipeline/extract_fate_extra.py list /path/to/data.cpk > work/cpk-list.json
python3 scripts/pipeline/extract_fate_extra.py extract /path/to/data.cpk --output work/extracted

# 2. 生成可翻译文本表与引用表
python3 scripts/pipeline/dump_fate_extra_text.py work/extracted/packages \
  --day-input work/extracted/cpk/day \
  --output work/translation/text.jsonl \
  --references work/translation/refs.jsonl

# 3. 重建 CPK（需要已翻译的 text.jsonl 与 glyph-map.json）
python3 scripts/pipeline/build_fate_extra.py \
  --translations work/translation/text.jsonl \
  --references work/translation/refs.jsonl \
  --glyph-map data/translation/glyph-map.json \
  --source-cpk /path/to/data.cpk \
  --output-cpk work/build/data.cpk

# 4. 把新 CPK 写回 ISO
python3 scripts/pipeline/embed_fate_extra_cpk.py \
  --source-iso /path/to/original.iso \
  --cpk work/build/data.cpk \
  --output-iso work/build/Fate_Extra_CN.iso \
  --allow-volume-growth
```

补字、诗文、ruby、UI 图片、v15 增量整合的完整命令见 [docs/01-pipeline.md](docs/01-pipeline.md)。

### 数据文件说明

- `data/translation/text.jsonl`：19,711 行，每行 `id / jp / jp_bytes_hex / zh_cn / reference_count`。`id` 是源字符串 SHA-256 前 16 位，稳定、与文件位置无关。
- `data/translation/glyph-map.json`：1,640 个无法用原生 CP932 表示的字符 → 私有区别名（正文及额外菜单文本）。
- `data/translation/poem-glyph-map.json`：诗文与章节卡动画字专用别名表，与正文不是同一套。
- `data/overlay/`：584 个改过的二进制资源，72,892,544 字节，带逐文件校验和；不含 DAT。
- `data/inventory/extracted-tree.jsonl.gz`：15,962 行解包树清单，用来核对自备 ISO 解出的树是否与工程基准一致。
- `refs.jsonl`（70 MB）**不入库**，由 `bootstrap` 或第 2 步重新生成；它是 ID 到文件、偏移、指针位置的映射，属于可复现中间产物。

---

## 文档索引

| 想知道什么 | 看这里 |
|---|---|
| 只想重建出 ISO、或改几句话 | [docs/11-quick-rebuild.md](docs/11-quick-rebuild.md) |
| 整体怎么做、各阶段输入输出 | [docs/01-pipeline.md](docs/01-pipeline.md) |
| CPK/PAK/CMP/DAT/TXB 的字节结构 | [docs/02-formats.md](docs/02-formats.md) |
| 文本怎么提取、长译文指针怎么搬家 | [docs/03-text-pipeline.md](docs/03-text-pipeline.md) |
| 字库为什么只能放 4,096 字、生僻字怎么进游戏 | [docs/04-font-pipeline.md](docs/04-font-pipeline.md) |
| 诗文碎字、ruby 小字缺失的根因 | [docs/05-poem-and-ruby.md](docs/05-poem-and-ruby.md) |
| 图片字怎么定位、去重、回写纹理 | [docs/06-ui-images.md](docs/06-ui-images.md) |
| ISO 怎么替换、怎么验证 | [docs/07-build-and-verify.md](docs/07-build-and-verify.md) |
| 语境校对怎么分工、如何避免"假完成" | [docs/08-quality-review.md](docs/08-quality-review.md) |
| 已知坑与规避方式 | [docs/09-pitfalls.md](docs/09-pitfalls.md) |
| 后续计划 | [ROADMAP.md](ROADMAP.md) |

---

## 重要原则

1. **源工程只读**。所有生成物写入独立的 `work/`，从不修改 ISO 或解包源。
2. **静态证据优先**。格式结论来自真实字节与反汇编，不靠"看起来像"；未实机验证的内容明确标注。
3. **文本与版式分离**。语义翻译、换行排版、控制码修复、字体补字是四类独立变更，各有脚本与审计。
4. **可回归**。每个构建产物都有 SHA-256、变更计数与逐字节回环校验。
5. **不越界声明**。审计报告只陈述已证明的范围，不用"全部完成"掩盖未读内容。

---

## 版权与致谢

- 游戏《Fate/Extra》及其全部素材版权归 Marvelous / TYPE-MOON 等原权利人所有。
- 本仓库包含自行编写的脚本、文档、翻译文本、审计数据，以及 `data/overlay/` 中 **584 个改动过的补丁文件**；完整 ISO 不入 Git。用户明确授权发布的自编译汉化 ISO 与补丁/纹理包分别作为 GitHub Release 附件提供。游戏素材版权仍归原权利人，使用者应持有日版游戏。
- 本项目为非商业同人汉化，禁止用于任何商业用途。
- 文件格式与工具链研究参考了 [ccc-tl/translation-tools](https://github.com/ccc-tl/translation-tools)（CPK/PAK/CMP 读取与 Extra 脚本转储思路）。本项目以其格式发现为基础，目标平台保持日版，未套用其面向美版的 MIPS 偏移。
- 代码采用 MIT 许可；文档与翻译文本采用 CC BY-NC-SA 4.0。详见 [LICENSE](LICENSE)。
