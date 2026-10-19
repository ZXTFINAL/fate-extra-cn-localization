# 放镜像的位置

把自备的日版《Fate/Extra》（NPJH-50247）镜像放进这个目录，文件名任意：

```
iso/original.iso
```

`python3 scripts/quick/quick.py bootstrap` 会自动找 `iso/*.iso`。

本目录下的 `*.iso` 已被 `.gitignore` 排除，不会误提交。
