# 文本流水线

文本量最大，也最容易出现"看起来译完了、实际有错位/漏句/控制码损坏"的问题。本文件说明提取、编号、翻译、排版与回写的完整方法。

---

## 1. 提取：沿操作码找指针，而不是扫字符串

`dump_fate_extra_text.py` 逐 4 字节读取 DAT，遇到已知文本操作码时，把紧随其后的 4 字节解释为字符串指针。

已识别的操作码：

| 操作码 | `kind` | 类别 | 说明 |
|---|---|---|---|
| `0x3926` | `dialogue` | main | 普通对话 |
| `0x1530` | `backlog` | main | 回想/日志 |
| `0x0126` | `motion` | motion | 动画章节卡 |
| `0x0A26` | `name_or_location` | misc | 人名/地名 |
| `0x0A30` | `choice` | misc | 选项 |
| `0x5030` | `dungeon_dialogue` | misc | 迷宫对话 |
| `0x5F16/0x6116/0x6416` | `popup` | misc | 双指针弹窗 |
| `0x5E16/0x6016/0x5316/0x5016` | `popup` | misc | 单指针弹窗 |
| `0x5916/0x6316` | `misc_prompt` | misc | 杂项提示 |

解析规则：

1. 指针为 0、越界、或要求对齐但未对齐 → 跳过。
2. 从指针处读到第一个 NUL，按 Shift-JIS 解码。
3. 空串不收录。
4. 同一偏移被多次引用时，合并为一个条目，累加 `pointer_offsets`。

文本同时来自两处：

- `work/extracted/packages/**/*.dat`（包内脚本）；
- `work/extracted/cpk/day/*.dat`（57 个独立章节脚本）。

两处都扫描后按 `(file, text_offset)` 去重，再按源字节哈希生成 ID。

### 稳定 ID

```python
id = sha256(原始 Shift-JIS 字节).hexdigest()[:16]
```

优点：

- 与文件、偏移、批次顺序无关；
- 同一句台词在 10 个文件里复用时仍是一个 ID；
- 改排版、改指针不会让译文失联。

代价：

- 原文改动会导致 ID 变化。因此**不要修改 `jp` 字段**；需要修原文时新建映射，不做原地改。

---

## 2. 文本表结构

`text.jsonl` 每行：

```json
{
  "id": "bb5bd4a0fe4e6cb6",
  "jp": "うむ、実に素晴らしい。",
  "jp_bytes_hex": "...",
  "zh_cn": "嗯，实在无可挑剔。",
  "reference_count": 12
}
```

`reference_count` 是该 ID 在全部 DAT 中的引用次数，用于：

- 字库分配时按使用频率排序；
- 校对时优先处理高频句；
- 判断某句是否值得单独润色。

`refs.jsonl` 每行：

```json
{
  "id": "...",
  "file": "000016/field/016/0000.dat",
  "text_offset": 69080,
  "pointer_offsets": [69076],
  "categories": ["main"],
  "kinds": ["dialogue"]
}
```

一个 ID 可以有多条 ref（多文件/多指针）。回写时必须**全部**改到，漏一个就会出现"同一句话一半中文一半日文"。

---

## 3. 翻译流程

### 3.1 分批

主表按约 100 条切成 211 个批次。批次文件只含 `id` 与 `zh_cn`，避免把日文原文复制来复制去。

```
batches/001.jsonl ... batches/211.jsonl
```

批次是**人工/代理的作业单位**，不是版本单位。合并时以主表为准：

```sh
python3 scripts/pipeline/apply_translation_batches.py \
  --source work/translation/text.jsonl \
  --batches work/translation/batches
```

默认策略：

- 主表已有非空译文 → 不覆盖；
- 需要重译 → 显式 `--overwrite`；
- 合并前自动备份到 `text.pre-*.jsonl`。

### 3.2 翻译准则

1. **先读上下文再落笔**。同一 ID 可能在多个场景复用，按"引用最多的场景"确定语气。
2. **保留控制码原样**：`#C...`、`#CDEF`、`#SP..`、`#RUBS/#RUBE/#REND`、`#SVT[...]`、换行 `\n`。
3. **保留分支结构**。男女主线、选项、称谓差异不能合并成一句。
4. **术语统一**。以 `data/glossary-GLOSSARY.md` 为准；新术语先入表再使用。
5. **长度意识**。对话框单行约 24 个全角字；超长由排版脚本处理，但翻译时就应避免无意义冗长。
6. **不编造机制**。原文没说的规则、数字、专有名词不补。

### 3.3 术语表（节选）

| 日文 | 中文 | 备注 |
|---|---|---|
| サーヴァント | 从者 | 不译"仆人" |
| マスター | 御主 | 与"主人"区分 |
| ムーンセル | 月灵晶 | 专名 |
| アリーナ | 竞技场 | |
| 宝具 | 宝具 | 保留 |
| セイバー / アーチャー等 | Saber / Archer | 职阶保留英文 |

完整表见 [../data/glossary-GLOSSARY.md](../data/glossary-GLOSSARY.md)。

---

## 4. 排版：换行是独立的一遍

翻译正确不等于显示正确。`fix_fate_extra_text_layout.py` 负责在合适位置插入 `\n`。

规则：

- 只处理 `dialogue / backlog / dungeon_dialogue / popup`；
- `motion`（0x0126 动画章节卡）**不插换行**，插了会打散动画布局；
- 默认每行最多 24 个全角字（`--max-width 24`）；
- 优先在句末标点断行，其次在逗号/顿号；
- 标点不出现在行首；
- 控制码不计入宽度；`#RUBS...` 计量 `#RUBE` 后的正文宽度，而不是小字层；
- 嵌套颜色码不参与字符计数。

输出前会备份 `text.pre-layout-fix.jsonl`。这一步只改 `zh_cn`，不改语义。

---

## 5. 回写：短串覆盖与长串搬家

`build_fate_extra.py` 的核心分支：

```python
if len(new_bytes) <= len(old_bytes):
    slot = len(old_bytes) + 1
    data[text_offset:text_offset+slot] = new_bytes + b"\0" * (slot - len(new_bytes))
else:
    new_offset = len(data)
    data.extend(new_bytes + b"\0")
    for p in pointer_offsets:
        struct.pack_into("<I", data, p, new_offset)
```

### 5.1 为什么短串也要清零整槽

部分渲染器不按 NUL 停止，而按"存储字符数"读取。若只覆盖前几个字节，旧串尾部会继续显示，典型现象是中文后面拖着日文残字。因此必须把原槽（含原 NUL）全部清零。

### 5.2 长串为什么必须搬

DAT 中的字符串是紧密排列的，没有空洞。原地扩展会覆盖下一条指令或字符串。唯一安全做法是追加到文件末尾，并改所有指针。

### 5.3 常见错误

| 现象 | 原因 |
|---|---|
| 一句话只有前几个字是中文 | 只改了主指针，漏了复用指针 |
| 中文后面拖日文 | 短串未清整槽 |
| 游戏在某句崩溃 | 指针改到了非字符串区，或对齐错误 |
| 章节卡文字散开/不显示 | 对 `motion` 文本插了换行，或用了正文字库别名 |
| 同一场景部分中文部分日文 | 该 ID 在多个 DAT 中复用，只重建了部分包 |

### 5.4 增量修订的额外保护

`stage_fate_extra_revision.py` 在替换前做一次"旧字节校验"：

1. 用旧 `glyph-map` 编码旧译文；
2. 与目标 CPK 中该偏移的实际字节比较；
3. 不一致 → 中止，不写入。

这能防止"文本表已更新、CPK 还是更早版本"导致的错位覆盖。未变更的 PAK 成员直接从旧 CPK 取，避免旧解包目录把新资源顶回去。

---

## 6. 验证

文本层的最小验证集：

1. **条数**：`text.jsonl` 行数 = 19,711；非空译文 = 19,709（余 2 条原文是全角空白）。
2. **ID 唯一**：无重复 ID。
3. **引用完整**：`refs.jsonl` 中每个 ID 都能在 `text.jsonl` 找到。
4. **字节可编码**：每条译文经 `glyph-map` 后都能 `cp932` 编码。
5. **长度分布**：记录超长句数量，确认排版脚本已处理。
6. **抽检**：按 `reference_count` 从高到低抽 200 条，人工核对语义/人称/否定。
7. **实机**：PPSSPP 走开场 30 分钟，重点看长句、选项、人名、章节卡。

第 5 项可用一段简单统计：

```sh
python3 - <<'EOF'
import json
rows=[json.loads(l) for l in open('data/translation/text.jsonl',encoding='utf-8')]
long=[r for r in rows if len(r.get('zh_cn',''))>48]
print('total',len(rows),'long',len(long))
EOF
```

---

## 7. 已知的 2 条空译文

`30dd9f5cad7f40ca` 与 `3d014762a0338fc8` 的原文只有全角空白（分别 5 个和 7 个），没有可译内容。它们保留空 `zh_cn`，构建时跳过，不影响覆盖率。统计时不要把这两条算作"漏译"。
