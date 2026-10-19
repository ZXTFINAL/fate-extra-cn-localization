# Fate/Extra 简体中文汉化工程

《Fate/Extra》（PSP 日版，`NPJH-50247`）的简体中文汉化工程记录。本仓库保存**全过程文档、方法论、可复现脚本、翻译主表、术语表与审计证据**。除 `data/evidence/poem/` 下用于复现缺陷的少量最小二进制切片外，不包含游戏本体、ISO 或完整商业素材。

> 目标不是"能跑就行"的补丁，而是可审计、可复现、可迭代的汉化流水线：每一条改动都能追溯到源字节、脚本和验证记录。

---

## 当前状态

| 模块 | 状态 | 关键数字 |
|---|---|---|
| 文本提取 | 完成 | CPK 5,824 条目 → 处理 2,297 条 → 解包 2,240 个包 |
| 文本翻译 | 完成 | 19,711 条唯一文本，19,709 条非空译文（其余 2 条原文仅为全角空白） |
| 正文补字 | 完成 | 1,571 个生僻字/标点分配 CP932 用户区别名；字库压缩回 4,096 字 / 16 页 |
| 诗文（poem）字库 | 完成 | 14×14 格、324 字/页；396 个中文字形，修正 16px 网格错位 |
| 注释小字（ruby） | 完成并入 v15 | 1,133 条文本修正；小字表 219 → 518 字 / 3 页 |
| UI 图片 | 完成并入 v15 | 371 个 TXB、2,598 个 TEX 变更；191 页教程 + 274 个小图 |
| 完整 ISO | v14 已构建 | `Fate_Extra_CN-v14.iso`，1,386,442,752 字节 |
| v15 资源 | 已预备 | 1,186 条文本、743 个 DAT、375 个覆盖资源，**尚未回写 ISO** |
| 可重建工程 | 完成 | 375 个变更文件 / 15,962 条解包清单 / `bootstrap` + `rebuild` 两条命令 |
| 全量语境校对 | 进行中 | 开场 641 / 19,711 ID；lane 1 已读 1,452 / 6,356 |

**结论边界**：v14 ISO 是可运行版本；v15 是已完成资源层准备、等待整合与实机回归的下一版。本仓库不声称"全部日文图片/文本已逐字校对完成"，未完成项见 [ROADMAP.md](ROADMAP.md)。

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
│   ├── pipeline/             20 个生产脚本（含 2 个 Swift 渲染器）
│   └── audit/                14 个审计/审校辅助脚本
├── data/
│   ├── overlay/              变更集：375 个改过的二进制资源 + 清单
│   ├── inventory/            解包树清单（15,962 个文件的路径/大小/校验和）
│   ├── glossary-GLOSSARY.md  术语表
│   ├── translation/          主翻译表、字库映射、批次清单
│   ├── review/               ruby 与语境修正结果
│   ├── evidence/             诗文/UI/ruby/语境审计证据
│   └── build/                v15 构建报告
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

仓库已经带好译文主表、字库映射和 375 个改过的二进制资源，**不需要重跑补字和图片重排**：

```sh
# 1. 把正版日版 ISO 放到 iso/（或 --iso 指定），从零展开工作区
python3 scripts/quick/quick.py bootstrap --iso iso/original.iso

# 2. 应用变更集 + 重建 CPK + 写回 ISO
python3 scripts/quick/quick.py rebuild
```

产物：`work/build/Fate_Extra_CN.iso`，附 `work/build/quick-build-report.json`（含各阶段 SHA-256）。

`bootstrap` 会做四件事：从 ISO 里直接取出 `PSP_GAME/USRDIR/data.cpk`（不挂载、不改原盘）→
解包 2,297 个 DAT/PAK/CMP → 铺好译文与字库映射 → 按 `data/inventory/` 核对解包树。

### 日常改稿

```sh
python3 scripts/quick/quick.py text find "セイバー"          # 定位
python3 scripts/quick/quick.py text set --id <ID> --zh "……" # 改写（自动查字库覆盖）
python3 scripts/quick/quick.py rebuild                       # 只重建受影响的部分
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
- `data/translation/glyph-map.json`：1,571 个无法用原生 CP932 表示的字符 → 私有区别名。
- `data/overlay/`：375 个改过的二进制资源（字库表、小字表、UI 纹理），71.9 MB，带逐文件校验和。
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
- 本仓库仅包含自行编写的脚本、文档、翻译文本与审计数据；除审计用最小切片外，**不提供 ISO、CPK、字体、图片等游戏资源**。使用者需自备正版游戏。
- 本项目为非商业同人汉化，禁止用于任何商业用途。
- 文件格式与工具链研究参考了 [ccc-tl/translation-tools](https://github.com/ccc-tl/translation-tools)（CPK/PAK/CMP 读取与 Extra 脚本转储思路）。本项目以其格式发现为基础，目标平台保持日版，未套用其面向美版的 MIPS 偏移。
- 代码采用 MIT 许可；文档与翻译文本采用 CC BY-NC-SA 4.0。详见 [LICENSE](LICENSE)。
