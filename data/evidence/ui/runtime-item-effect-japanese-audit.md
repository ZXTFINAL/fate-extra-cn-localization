# 礼装名称、介绍与效果说明核对

## 静态礼装文案

已逐条复核 `PRELOAD/cmn/item_param_04.bin` 中 32 条可用装备记录，包括礼装名称、效果说明和风味介绍。静态文案已通过 CPK overlay 写入中文；对应资源为 `data/overlay/packages/pack/PRELOAD/cmn/item_param_04.bin`。例如「强化运动服」的名字与介绍分别是“月海原学园指定的运动服。”和“只要穿上就能强化精神。”逐条文案、全部一般道具字段和编码回读见 [`item-description-coverage-v1.2.md`](item-description-coverage-v1.2.md)。

文字源对照表位于工作区 `work/research/japanese-remaining-v18/items/item-text-translations.tsv`。2026-10-25 重建 CPK SHA-256 为 `feda45962ab7075875dd02a2ff6f1b85cb5a34ca59bb9fe2e29653ceb1942263`；从 CPK 解出的 `PRELOAD.pak` 中，`item_param_01.bin` 与 `item_param_04.bin` 均与覆盖资源逐字节一致。可显示的礼装和道具静态字段日文残留为 0。

## 动态效果句

商店截图里「强化运动服」下方的日文并非礼装介绍字段，而是游戏 EBOOT 根据效果运行时拼接出的通用 MP 效果句。原字符串在已验证的解密 EBOOT 偏移 `0x14e3e4` 和 `0x14e41c`：

| 日文/内部字符串 | 中文 |
| --- | --- |
| `boost_mp(%02d);` | `御主MP+%02d` |
| `マスターのＭＰが%s上昇` | `御主MP提升%s点` |

两条文本已在 `Fate_Extra_CN-v1.2-PPSSPP.iso` 使用的解密 ELF 中原位替换，分别占 11/15 字节和 14/22 字节，均在原槽位内；不改变 EBOOT 文件长度或后续偏移。变更脚本为 `scripts/pipeline/patch_fate_extra_eboot_item_descriptions.py`。

## 构建和运行记录

- `Fate_Extra_CN-v1.2.iso`：2026-10-25 重建并恢复中文 XMB 图片，保留原版加密 EBOOT；SHA-256 `d6a3e9a1e3a025bdab7db42de713090ec09825cc6b5ce15cf537142c934cc03c`。原启动文件适用于 PSP/PPSSPP，但动态 MP 句仍是日文。
- `Fate_Extra_CN-v1.2-PPSSPP.iso`：以同一 CPK 和中文 XMB 图片为基础，替换成已翻译的解密 ELF；SHA-256 `c7914d6190fc0ebd893db4cd63164c2eb34335114300300953535f555e70cba6`。仅推荐 PPSSPP/支持解密 ELF 的环境，不承诺 PSP 零售固件可启动。
- 本次动态效果句完成了 ELF 槽位读回核验：两条中文编码各出现一次，原日文字符串已消失；ISO 的 XMB 图像也逐字节匹配中文资源。PPSSPP 自动化在加载新 ISO 时超时，故本次没有直接在商店画面目视确认动态句。

“所有礼装介绍已翻译”指 CPK 中的 32 条静态装备/礼装字段；动态 MP 格式句的中文仅在 PPSSPP ELF 版生效。两种 ISO 的 EBOOT 兼容目标不同，不能混称为对 PSP 实机都完整验证过的同一版本。两种构建的封面图片一致为中文。
