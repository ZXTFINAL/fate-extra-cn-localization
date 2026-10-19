# 快速重建与交接

这一篇是给"接手者"看的：不管你是人还是 agent，目标是用最少的前置知识把仓库跑起来、
改一句话、出一版 ISO。

---

## 1. 三层结构

| 层 | 位置 | 是否入库 | 内容 |
|---|---|---|---|
| 可复用层 | `data/`、`scripts/`、`docs/` | ✅ | 译文、字库映射、变更集、解包清单、脚本、文档 |
| 工作区 | `work/` | ❌（`.gitignore`） | 解包树 1.67 GB、引用表 70 MB、构建产物 |
| 产物 | `work/build/` | ❌ | `data.cpk`、`Fate_Extra_CN.iso` |

这样切分的原因：`work/` 里 99% 是未修改的原版资源，可以由 ISO 精确重现；真正需要版本管理
的是**译文 + 变更集 + 规则**。所以仓库只有几十 MB，却能重建 1.3 GB 的完整镜像。

---

## 2. 接手：两条命令

```sh
cp /path/to/日版.iso iso/original.iso
python3 scripts/quick/quick.py bootstrap      # 约 14 分钟，一次即可
python3 scripts/quick/quick.py rebuild        # 约 11 分钟
```

`bootstrap` 的四步：

1. 解析 ISO9660，直接从镜像里取出 `PSP_GAME/USRDIR/data.cpk`（不挂载、不写原盘）；
2. 解包 2,297 个 DAT/PAK/CMP 到 `work/extracted/`；
3. 铺好 `work/translation/text.jsonl` 与 `glyph-map.json`，生成 `refs.jsonl`；
4. 用 `data/inventory/` 的清单逐文件核对解包树。

`rebuild` 的三步：

1. 把 `data/overlay/packages/**` 同步到 `work/build/assets/packages/**`；
2. 用主翻译表重写 DAT 文本，并把变更集涉及的包重新打包成新的 `data.cpk`；
3. 把新 CPK 写回 ISO（必要时扩展卷大小），输出 `work/build/Fate_Extra_CN.iso`。

> **重建不需要 macOS，也不需要 Swift**。字形渲染只在新增生僻字时用到。

---

## 3. 改文本

```sh
python3 scripts/quick/quick.py text find "セイバー"           # 模糊定位，给 ID
python3 scripts/quick/quick.py text set --id 1a2b3c4d --zh "……"
python3 scripts/quick/quick.py text diff                       # 相对主表改了什么
python3 scripts/quick/quick.py text check                      # 字数、字库覆盖体检
python3 scripts/quick/quick.py rebuild
```

`text set` 之后会自动做**字库覆盖检查**：任何既不在 CP932、也不在 `glyph-map.json` 里的字，
都会列出来并标红。这类字在游戏里显示为空白——必须先走补字流程，不能直接提交。

`text check` 的"疑似过长"是排版风险提示（中文比日文短，通常不会超；超了多半是漏了换行）。

## 4. 改图片

```sh
# 1. 导出预览（带 roundtrip 自检，确认解码器与这张图完全对齐）
python3 scripts/quick/quick.py image decode --package pack/000001/interface/shop/shop_00.txb

# 2. 改配置里的文字块（JSON，逐条可 review），回写纹理
python3 scripts/quick/quick.py image apply --config data/evidence/ui/ui-text-patches.json

# 3. 更新变更集清单并重建
python3 scripts/quick/quick.py overlay sync
python3 scripts/quick/quick.py rebuild
```

**不要直接把 PNG 覆盖成 TXB**。这些纹理是"调色板 + CCT 索引"格式，尺寸、格式、调色板任何
一项不匹配都会让整个包读不出来。要么走区域重绘（保留原调色板），要么按
[docs/06-ui-images.md](06-ui-images.md) 的编码路径处理。

## 5. 改变更集后的可追溯性

每次 `rebuild` 都会写 `work/build/quick-build-report.json`：

```json
{
 "source_cpk_sha256": "7bf7e3d1f0586202ddaa90ca228737fff0e37be682b4bd9598c760aa7e451657",
 "translations_sha256": "364e64be7bd174bbbf732721a393841a08cc0469b141f07026534ea58b1aec06",
 "glyph_map_sha256": "cf4650190a971ac5f5fa52df2596a59094d1452d8f0a0724b1a3ea4aec1008c0",
 "output_cpk_bytes": 1307189648,
 "output_cpk_sha256": "853b718a46248f560b1de6eae99a12856ad3a25c7f0a59a17fd76ad1f15681a5",
 "output_iso_bytes": 1420634112,
 "output_iso_sha256": "05f00976889b6b0344828589e5ec60b7a8ac9eb93bb404c6c5cf733c3eb856ce"
}
```

> 以上是本仓库第一次端到端实测的结果（同一张原盘 + 同一份译文 + 同一份变更集）。
> 换一张原盘，`source_cpk_sha256` 与产物哈希都会变，但**构建过程本身是确定的**：
> 相同的三个输入必然得到相同的输出。

配合 `data/overlay/manifest.json` 的逐文件哈希，任何一版产物都能回答"用了哪份译文、
哪份字库、哪份变更集"。提交前一并更新报告，别人才能复现你的字节。

## 6. 体积与时间（实测，Apple Silicon）

| 阶段 | 时间 | 产出 |
|---|---|---|
| 从 ISO 取 data.cpk | ~25 s | 1.13 GB |
| 解包 2,297 个包 | ~13.8 min | 15,962 个文件 / 1.67 GB |
| 生成 refs.jsonl | ~14 s | 408,796 处引用 / 19,711 条 |
| 重建 CPK | ~11.2 min | 1,307,189,648 字节 |
| 写回 ISO | ~2 s | 1,420,634,112 字节 |

（实测：Apple Silicon，macOS。`bootstrap` 合计 840 s，`rebuild` 合计 690 s。）

解包是最慢的一步，但只需做一次；后续改稿只走"重建 CPK + 写回 ISO"，约 11 分钟。
写回快是因为只替换 CPK 区段，不重写整张盘。

## 7. 故障排查

| 症状 | 原因 | 处理 |
|---|---|---|
| `ISO 内找不到 PSP_GAME/USRDIR/data.cpk` | 不是日版原盘，或镜像被改过 | 换 `NPJH-50247` 日版原盘 |
| 解包核对报大量"缺失" | 区域版本不同 / 用了别的 dump 工具 | 若游戏能正常跑可忽略；否则换盘 |
| `只有 N 个未使用日文字形可用` | 新增生僻字太多，4,096 字位不够 | 先 `compact_fate_extra_font.py`，或复用已有别名 |
| 游戏里某些字空白 | 字没进 `glyph-map` | `text check` 找出，走补字流程 |
| 中文全变方块/乱码 | 改了 `kanzi.bin` 原有字位顺序 | 原有字位一个不能动，中文只走 `0xE000` 别名 |
| 某界面直接黑屏/不显示 | 该包 TXB 被写坏 | `overlay verify` 找被改文件，从 git 恢复 |

## 8. 给 agent 的接管清单

1. 读 `AGENT.md` 的 10 条硬约束，尤其"原有字位不动""变更一次只做一类"；
2. `python3 scripts/quick/quick.py status` 看工作区缺什么；
3. 缺 `work/` 就跑 `bootstrap`，缺产物就跑 `rebuild`；
4. 动手前先 `git status`，确认变更集没有被本地手改污染；
5. 改完必跑 `text check` / `overlay verify` / `rebuild` / `verify` 四连；
6. 报告进度时只写真实读过的内容，不批量勾选。
