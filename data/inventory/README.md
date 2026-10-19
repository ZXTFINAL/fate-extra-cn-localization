# 解包清单（inventory）

原始解包树有 **15,962 个文件 / 1.67 GB**，全部是游戏资源，不入库。这里只保存**目录结构与
逐文件校验和**，用来回答三个问题：

1. 我解出来的树，和工程基准是不是同一份？
2. 某个文件在 `packages/` 里的确切路径是什么？
3. 重建时到底读了哪些文件（便于排查"少了一个包"这类错误）？

```
data/inventory/
├── summary.json              顶层统计
└── extracted-tree.jsonl.gz   15,962 行：path / size / sha256 前 16 位
```

## 统计

| 顶层 | 文件数 | 字节 |
|---|---|---|
| `cpk/` | 1,543 | 714,093,866 |
| `packages/` | 14,419 | 1,078,197,360 |
| **合计** | **15,962** | **1,792,291,226** |

排除两项：`.DS_Store`（系统垃圾）与 `extracted/manifest.json`（内含绝对路径
`/tmp/fateextra-iso/...`，跨机器必然不同）。这两项不影响构建。

`cpk/` 是从 `data.cpk` 原样取出的 `.dat` / `.pak` / `.cmp`；`packages/` 是 PAK/CMP 解开后的
实际资源（纹理、脚本、字库）。两者都可由 `data.cpk` 完整重现，因此没有任何"只能靠拷贝"的内容。

## 怎么用

```sh
# 解包（bootstrap 会自动做）
python3 scripts/quick/quick.py bootstrap --iso iso/original.iso

# 单独核对：逐文件比大小与 SHA-256
python3 scripts/quick/quick.py inventory verify
```

`bootstrap` 默认在解包后自动核对一次；加 `--skip-inventory` 可跳过（约省 10 秒）。
校验和不符只报警告，因为不同区域版本、不同 dump 工具的零填充可能有差异；
如果**文件数**或**路径**对不上，说明拿错了盘。

## 为什么不全传

- 1.67 GB 里 99% 是未修改的原版资源，传上去既超仓库限制，也没有信息增量；
- 汉化只改了 375 个文件（见 `data/overlay/`），其余都可以从正版 ISO 精确重现；
- 清单 + 构建脚本 = 同等可复现性，体积从 GB 级降到几百 KB。
