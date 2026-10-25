# 图片本地化审计与本次输出（2026-10-19）

## 已定位的遗漏

- 启动虚构声明实际在 `pack/modeselect/interface/modeselect/fiction.txb`，不是logo商标包。480×272，T8+CCT32，一张整页图片。
- 另一个注意页在 `pack/advice/interface/advice/0000.txb`，提示存在死路与不合理选项，建议准备多个存档；是按行切开的图片。
- 首次系统菜单说明是 `tutorial_other_00/01`，标题与底部说明均烘焙在480×272图片中。当前也已精确替换截图里的六个菜单项、选择提示与保存帮助文字，保留按钮及英文。
- 72个 `tutorial_other_00..71` 包含191页；解码RGBA去重为168张。全部标题与底部教学说明已翻译，截图本体依原图保留（00/01的明确操作标签除外）。
- 常用UI还有大量独立图片字，正文text.jsonl不会覆盖它们。本次处理274个独立小图/片段，覆盖保存、读取、删除、选项、装备、道具、状态、情报矩阵、战斗警告、地图层数、日期、从者选择、宝具咏唱等。六个开战动画用字也从決/戰/開/聖/争/勝替换成简体字。

## 产物与整合

- 最终资源根：`work/build/localization-v15/assets/packages/pack/`。
- 共371个TXB文件，包含重复包中的同一资源；2598个实际TEX条目发生变化，资源共71,320,704字节。它们是供CPK整合的覆盖文件；本任务没有改ISO/CPK或主翻译表。
- `fiction.txb`、191页教程、274个小图共466个规范编辑目标；UI的相同TXB按原始整文件SHA256分组，复制到260个完全相同别名包，避免只改一份时其他场景仍显示日文。
- 不输出 `modeselect/modeselect.txb`，该文件的难度选择页在v14已有翻译，避免覆盖已完成的资源。

## 纹理实现与验证

`tools/fate_extra_texture.py` 支持T4/T8、PSP 16-byte×8-row swizzle、32×32 CCT与RGBA8888解析，保留TXB路径/空条目/尾字节、TEX尺寸/调色板、原有唯一块与未变块引用。新增图片块仅追加并继续去重，更新data_size与CCT非空条目数、唯一块数。CCT为20字节头，后接int16索引；-1为空块且不计入count。色盘长度以色数与模式计算，不能信任palByteSize字段。

`tools/patch_fate_extra_image_text.py` 只改声明的矩形或指定文字RGB；新字量化回原调色板。保留按钮、英文装饰和紫色边框，避免覆盖OCR误把图标当文字的区域。中文用本机Hiragino Sans GB W6渲染，不依赖外部LLM/翻译模型。

完整检查记录 `final-validation.json`：

- 200个去重的原界面TXB、1627个非空TEX、330个空条目，解码后不改像素再编码，全部逐字节相同；原3个14px光标已补stride处理并通过。
- 371个输出TXB再解析/重编码逐字节相同，TXB条目名及顺序、图像尺寸、色盘逐项相同，0错误。
- 274个小图和191页教程都检查编码后的索引图与预期像素一致；文字渲染器会拒绝超出声明矩形的文本。191页正文统一14px、两行以内。
- 已视觉查看启动声明、首教程、多个混合字图与边框图，并修正英文装饰被清字矩形裁掉、原字尾残留等问题。对比证明 `before-after-proof.png`；逐图PNG在 `translated/`、`translated-ui/`、`translated-tutorials/`。

## 仍保留/待进一步处理

本次不应表述为“游戏所有日文图片已全译”。`remaining-ui-candidates.json` 保存所有OCR命中但未由本批处理的条目及分类：制作名单/人名保留；poem字库与背景由原v14诗文流程负责；性别图标、相同汉字、数字和英文装饰多为OCR误报；另有单字“仮”的临时图标待确认实际用途。

多数教程截图内仍有原版UI、技能与道具名称。这些是嵌在截图中的原画面，并非当前运行时UI资源。为避免清错背景，已逐图把关键截图标签另列于 `tutorial-translation-review.json` 的 screenshot_terms；高亮宝具名、投影准备、灵魂篡改操作区等仍可继续按确切矩形补。教程标题/规则正文已译全，不能据此声称截图内部也已逐字全译。

此次全量扫描范围是原提取包路径中的 `/interface/` TXB：2113个全部TXB里，界面文件按内容去重为200包。模型贴图/场景看板、视频字幕、PSP系统对话等其它资源类型需各自清点，不在这个1627图证明内。

## 可复现配置

- `image-text-patches.json`：启动声明。
- `ui-text-patches.json`：274小图与260份重复包分发。
- `tutorial-text-patches.json`：191页教程、首教程截图操作标签。
- `translation-task-A/B.jsonl`、`translation-result-A/B.jsonl`：独图OCR bbox、PNG、译文与语义备注；已由两个代理逐图阅读翻译。
- `ui-bundles-inventory.json`、`all-ui/decode-report.json`、`all-ui-ocr.json`、`ui-japanese-images.json`：完整资源清单、解码与OCR证据。

使用bundled Python依次运行 `tools/patch_fate_extra_image_text.py` 并传上述三个配置即可重建对应覆盖文件；后两个可用 `--previews` 指定其独立PNG目录。两个 `make-*-config.py` 是生成配置的研究脚本，不属于游戏工具原逻辑。

## v1.1 回归修正与残留复核（2026-10-21）

- 用户截图 1 的底部说明来自 `PRELOAD/interface/mainmenu/help.bin`，不属于 TEX 图片。v1.1 为 5 条固定主菜单说明补译中文；截图中的“查看已收集的情报矩阵”对应记录 ID 1。
- 通用确认框 `PRELOAD/interface/cmn/dialog.bin` 仍为日文 `はい / いいえ`，现改为“是 / 否”。存档菜单图片和存档问题句此前已是中文；商店确认按钮也已使用“是 / 否”。
- 情报矩阵 `mtx_cgr_00.tex` 原日文字素的有效纵向范围约为 y=3–14，旧中文绘制框从 y=8 开始，导致标题下移并挤到状态条。v1.1 调整为 y=1；纹理回读框由 y=8–23 移到 y=1–16，TXB/调色板/原尺寸校验通过。
- 固定 UI 表格回查了 `other-ui/audit.json` 中 171 个结构化表：170 个已进入 v1.1 overlay 的表解码检查后无日文假名；唯一未覆盖项 `003016/interface/nameentry/kanji.bin` 是姓名输入用字符键盘，保留日文字符供玩家输入。
- 59 个未处理 OCR 候选均有分类：27 个制作名单与人名保留，18 个图标/数字/英文误报，4 个与中文相同的单字，2 个性别图标，4 个诗文字库/背景由独立流程处理，3 个难度选择图已在旧版处理。剩余 1 个待确认小图是 `PRELOAD/interface/cmn/i_exp.txb#11` 的“仮”，当前没有足够上下文判断它的实际游戏含义，因此暂不擅自替换。
- 教程截图内部原版 UI、制作名单、模型贴图、场景看板与视频字幕仍不属于本次运行时 UI 覆盖范围；“游戏所有日文图片均已翻译”仍不是本版结论。

回读与残留分类报告见 `../build/v1.1-fixed-ui-patch-report.json`、`../ui/v1.1-fixed-ui-residual-scan.json` 和 `../build/v1.1-final-iso-validation.json`。


## v1.1 实机照片残留复核（2026-10-23）

- 对照用户提供的难度选择、System 存档及商店照片，回读最终 ISO 中对应 `modeselect.pak`、`savemenu.pak`、`000001.cmp` 的 TXB。难度选择和商店纹理与 overlay 字节完全一致；“NORMAL / EASY”及 “Tukumihara Shop” 是单独保留的英文副标签，不是覆盖失败的日文像素。
- 存档菜单的旧字体样式带深色描边，实机屏幕拍照后容易看成双重字形/日文残影。已将两个存档 TXB 的文字改为无描边明朝样式，重绘并写入 1.1 CPK。
- 同一轮残留扫描发现开场计数标签“剩余”旁独立的“人”字块未用中文样式重绘，现清除后按同一中文字形重新绘制。
- 输出 ISO 的 `data.cpk` SHA-256 与构建 CPK 一致；5 个相关纹理（存档2、开场1、难度1、商店1）均逐字节匹配 overlay。报告在 `../build/v1.1-residual-fix-validation.json`。
- 这次验证是贴图/CPK/ISO 回读，没有在 PSP 实机上重新运行；拍屏中的网纹、像素色边仍可能来自 PSP 液晶拍摄与摩尔纹，需结合这份新 ISO 的实机画面确认。
