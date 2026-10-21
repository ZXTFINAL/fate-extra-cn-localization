# 变更集（overlay）

这里保存**所有被改动过的二进制资源**——字库表、小字表、UI 纹理。它是"汉化补丁负载"，
不含任何未修改的原始游戏文件。配合自备正版 ISO，任何人可以直接重建出完整中文镜像，
不需要重跑一遍字形渲染、图片重排和审计。

```
data/overlay/
├── manifest.json          580 个文件的路径 / 大小 / SHA-256
└── packages/              目录结构与 work/build/assets/packages 一一对应
    └── pack/
        ├── PRELOAD/       kanzi.bin、font.txb、ruby.bin、ruby.txb
        ├── 000001/…/      266 个 interface 包
        └── …/            100 个 battle 包
```

## 清单（v1.0）

| 类别 | 文件数 | 说明 |
|---|---|---|
| `pack/PRELOAD` | 26 | 正文字库、小字库及菜单/技能/角色参数资源 |
| `pack/*/interface` | 421 | 教程、菜单、物品、情报矩阵与其他界面资源 |
| `pack/*/battle` | 133 | 战斗界面、指令与状态文字 |
| **合计** | **580** | **72,883,600 字节** |

## 每个文件的来源

变更集不是手改出来的，全部由脚本 + 可复核配置生成：

| 文件 | 生成方式 |
|---|---|
| `pack/PRELOAD/kanzi.bin`、`font.txb` | `scripts/pipeline/patch_fate_extra_font.py`（补字 + 压缩回 4,096 字） |
| `pack/PRELOAD/ruby.bin`、`ruby.txb` | `scripts/pipeline/patch_fate_extra_annotation_fonts.py`（9×9 格、518 字 / 3 页） |
| `pack/*/interface`、`battle` | `scripts/pipeline/patch_fate_extra_image_text.py` + `data/evidence/ui/*-text-patches.json` |

v1.0 增补的参数、技能、物品和情报矩阵资源由相应定长字段补丁生成；最终逐文件 SHA-256 记录在 `manifest.json`。

因此变更集是**可再生的**：删掉整个目录，按 `docs/01-pipeline.md` 重跑对应脚本即可复原。
把它纳入版本管理的意义是省掉这条路——接手者不必先有 macOS 渲染环境，也能直接构建。

## 校验

```sh
python3 scripts/quick/quick.py overlay verify
```

逐文件比对 `manifest.json` 里的 SHA-256，缺失或篡改都会报出来。

## 修改后如何更新

1. 直接替换 `data/overlay/packages/...` 下的文件（注意格式约束，见 `docs/06-ui-images.md`）；
2. `python3 scripts/quick/quick.py overlay sync` 重算清单；
3. `python3 scripts/quick/quick.py rebuild` 重建。

> 纹理是调色板 + CCT 索引格式，**不能直接把任意 PNG 丢进去**。替换必须保持原 TEX 的
> 尺寸、格式与调色板，或走 `patch_fate_extra_image_text.py` 的区域重绘路径。细节见
> [docs/06-ui-images.md](../../docs/06-ui-images.md)。

## 边界

- 只放**改过的**文件。原始未改动资源一律从用户自备 ISO 解出，不入库。
- 本目录内容版权归原权利人，仅作为非商业汉化补丁的一部分提供，禁止商用。
