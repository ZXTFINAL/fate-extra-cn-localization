# 构建、写回与验证

本文件覆盖从资源到可玩 ISO 的最后一段：CPK 重建、ISO9660 写回、增量修订与验证门槛。

---

## 1. 构建产物的层次

| 层 | 产物 | 变更规模 |
|---|---|---|
| 文本层 | `text.jsonl` | 19,709 条非空译文 |
| 字形层 | `kanzi.bin` / `font.txb` | 4,096 字 / 16 页 |
| 包层 | `pack/*.pak`、`pack/*.cmp` | 受影响的 871 条 CPK 路径（v15） |
| 容器层 | `data.cpk` | TOC / ETOC / 对齐全部重写 |
| 镜像层 | `*.iso` | 目录记录 + 卷大小 |

任何一层长度变化都会向上传播。因此构建必须**自底向上重新计算**，不能只替换文件内容。

---

## 2. CPK 重建

`build_fate_extra.py` 的步骤：

1. 读 `manifest.json`，建立 CPK 条目与解包目录的对应；
2. 按 `refs.jsonl` 把译文写回 DAT（短串覆盖 / 长串追加 + 指针重定向）；
3. 找出受影响的包，重新 `write_pak`；
4. CMP 包用 `encode_cmp` 重压为 IECP LZSS；
5. 按 `AbsoluteOffset` 顺序写新 CPK：
   - 每条目 2,048 字节对齐；
   - 未变更条目从源 CPK 直接拷贝；
   - 变更条目写新字节；
6. ETOC 搬到新位置；
7. 回填 TOC 每行的 `FileOffset/FileSize/ExtractSize`；
8. 回填头部 `EtocOffset/ContentSize`；
9. 截断到最终长度。

### 2.1 为什么必须 2,048 对齐

PSP 光驱按扇区读取，CPK 条目偏移若不是扇区对齐，部分加载路径会读错。源 CPK 本身就是 2,048 对齐，重建必须保持一致。

### 2.2 ETOC 不能重建

ETOC 是 CRI 的扩展表，包含工具链元数据。本工程没有完整规格，做法是**原样搬运**，只改它的偏移。重建 ETOC 属于未验证区域。

### 2.3 未变更条目直接拷贝

不要从 `work/extracted/` 重新打包未变更条目：解包目录可能被旧版本覆盖，重新压缩还会改变字节。正确做法是从源 CPK 按 `FileOffset/FileSize` 直接读原始字节。

---

## 3. 写回 ISO

`embed_fate_extra_cpk.py`：

1. 复制源 ISO 到输出（允许原地重建同一路径）；
2. 读扇区 16 的 PVD，校验 `CD001` 与卷大小双端字段一致；
3. 在目录树中定位 `PSP_GAME/USRDIR/data.cpk` 的目录记录；
4. 检查新 CPK 是否能放在原 extent 起始位置：
   - 能放下 → 覆盖；
   - 放不下且允许增长 → 占用后续空闲扇区，更新目录记录 extent size 与 PVD 卷大小；
5. 保持文件名小写（游戏按 `data.cpk` 查找）；
6. 写回。

### 3.1 大小写问题

ISO9660 常把文件名规范为大写，但本作按小写查找。若写回后黑屏/找不到资源，用：

```sh
python3 scripts/pipeline/patch_fate_extra_iso_case.py --iso work/build/Fate_Extra_CN.iso
```

把目录记录中的标识恢复为小写。

### 3.2 卷增长

v14 的 CPK 比原版大，ISO 从 1,280,933,888 增长到 1,386,442,752 字节。增长本身没问题，但：

- 必须更新 PVD 两处卷大小；
- 必须确保占用的扇区原本是空闲的；
- 实机记忆棒需有足够空间；
- 某些自制系统对超大 ISO 的缓存行为不同，需实机确认。

---

## 4. 增量修订（v15）

全量重建一次要处理 5,824 个条目，且容易把旧解包状态带回来。v15 改为定点替换：

```sh
python3 scripts/pipeline/stage_fate_extra_revision.py \
  --source-cpk <v14 的 data.cpk> \
  --previous-translations text.v14.jsonl \
  --translations text.jsonl \
  --previous-glyph-map glyph-map.v14.json \
  --glyph-map glyph-map.json \
  --poem-glyph-map poem-glyph-map.json \
  --references refs.jsonl \
  --overlay work/build/localization-v15/assets/packages \
  --out work/build/localization-v15 \
  --prepare-only
```

保护机制：

| 机制 | 作用 |
|---|---|
| 旧字节校验 | 替换前用旧映射编码旧译文，与实际 CPK 字节比对，不一致即中止 |
| 未变更成员取旧 CPK | 不用可能过期的解包目录 |
| 指针全量核对 | 每个 `pointer_offsets` 都必须指向预期旧串 |
| `--prepare-only` | 先出报告与覆盖层，人工确认后再写 CPK |
| `--overrides` | 允许按 `(id, file, offset)` 做单点覆盖，处理同 ID 不同语境 |

v15 报告（`data/build/build-report-v15.json`）：

| 字段 | 值 |
|---|---:|
| `changed_ids` | 1,186 |
| `changed_dat_files` | 743 |
| `applied_references` | 15,674 |
| `overlay_resources` | 375 |
| `cpk_paths` | 871 |
| `prepared_only` | true |
| `translation_sha256` | `2494980a…c64fcf` |

**v15 尚未生成新 ISO**。它完成的是资源层准备与校验，下一步才是去掉 `--prepare-only` 并写回。

---

## 5. 版本产物

| 版本 | 类型 | 大小 | SHA-256 |
|---|---|---:|---|
| 日版原盘 | ISO | 1,280,933,888 | `60399d610cbcda96601374a2e621a22bb58505c403c6fa4221eec5e87235667b` |
| v14 | 完整 ISO | 1,386,442,752 | `81c651b5ddbefc9ace750640ea41ea2f1a077f2cb32a7b33cbe61349fdcb7631` |
| v15 | 资源预备 | — | 见构建报告 |

v14 是**可运行**版本：文本、正文字库、诗文 14×14 修复、UI 图片（部分）已整合。v15 在其上增加了 ruby 文本修正、ruby 518 字/3 页字库、更多 UI 覆盖。

---

## 6. 验证清单

### 6.1 结构验证

```sh
# CPK 能否被自己的解析器完整读出
python3 scripts/pipeline/extract_fate_extra.py list work/build/data.cpk > /tmp/list.json

# 条目数应与源一致（内容变化，条目数不变）
python3 - <<'EOF'
import json
a=json.load(open('/tmp/list.json')); print(len(a))
EOF
```

### 6.2 回环验证

- 未修改的 PAK/TXB：解包→重打包逐字节相同；
- 未修改的 TEX：解码→编码逐字节相同；
- 修改过的 DAT：重新解析，指针均指向合法 NUL 结尾串。

### 6.3 内容验证

- 随机抽 20 个变更 DAT，读回译文，与 `text.jsonl` 比对；
- 检查长串指针是否都指向文件末尾追加区；
- 检查短串槽位是否已清零。

### 6.4 运行时验证

| 场景 | 检查点 |
|---|---|
| 启动 | 虚构声明、标题、难度选择 |
| 开场 | 校门/走廊/教室对话、人名、选项 |
| 菜单 | 保存/读取/删除/装备/道具/状态 |
| 战斗 | 指令、宝具名、警告、结算 |
| 章节卡 | 诗文完整、不碎字、停留时间可读 |
| ruby | 小字显示、上下层不重叠 |
| 教程 | 191 页标题/正文、按钮符号 |

PPSSPP 通过不等于实机通过；实机需关注加载时间、记忆棒读取、长时间运行。

---

## 7. 常见构建故障

| 故障 | 可能原因 | 排查 |
|---|---|---|
| 游戏黑屏 | ISO 目录记录/卷大小未更新；文件名大小写 | 用 `patch_fate_extra_iso_case.py`；检查 PVD |
| 进入某场景卡死 | 该 DAT 指针越界/对齐错 | 用解析器重读该 DAT，检查 `text_offset` |
| 文本半中日半中 | 只重建了部分复用包 | 查 `refs.jsonl` 中该 ID 的所有 `file` |
| 字库越界崩 | 字数 > 4,096 | 跑压缩脚本，检查页数 |
| 图片花屏 | TEX 重编码丢失唯一块/调色板 | 做未修改回环；检查 CCT 计数 |
| 章节卡碎字 | 用了 16px 网格 | 改 14px，检查 `poem.bin` 顺序 |
| ruby 小字空白 | 字库未扩容或别名不匹配 | 查 `annotation-font-build.json` 的 518/3 页 |

---

## 8. 发布产物建议

GitHub Release 只附**可公开的小文件**：

- 源码归档（本仓库 tag）；
- 翻译数据包（`text.jsonl` + `glyph-map.json` + 术语表 + 修正表，压缩后约 3 MB）；
- 构建报告与校验和；
- 发布说明。

**不要上传 ISO**：体积大、含商业素材、且违反本仓库的分发边界。需要试玩的用户应自行按文档构建。

---

## 9. 相关脚本

| 脚本 | 用途 |
|---|---|
| `build_fate_extra.py` | 全量重建 CPK |
| `embed_fate_extra_cpk.py` | 替换 ISO 内的 data.cpk |
| `patch_fate_extra_iso_case.py` | 恢复小写文件名 |
| `stage_fate_extra_revision.py` | 增量修订（v15 路线） |
| `refresh_fate_extra_incremental.py` | 在已有翻译 CPK 上应用文本增量 |
| `refresh_fate_extra_font.py` | 仅刷新字体/难度包 |
