# 写入飞书

## 依赖

| 工具 | 用途 | 检查 |
|---|---|---|
| Node + npx | 本地渲染 PNG、画板自检（`@larksuite/whiteboard-cli@^0.2.12`） | `npx -y @larksuite/whiteboard-cli@^0.2.12 -v` |
| lark-cli | 写画板、导出预览、备份 | `lark-cli auth status` 里 user 身份 ready，带 `board:whiteboard:node:*` 权限 |

可用环境变量替换命令：`LFIG_WBCLI`（默认 `npx -y @larksuite/whiteboard-cli@^0.2.12`）、`LFIG_LARK_CLI`（默认 `lark-cli`，跨账号时可设成 `lark-cli --profile xxx`）、`LFIG_STATE`（备份目录，默认 `~/.cache/lark-figure`）。

lark-cli 只读写当前目录和 `/tmp` 下的文件，脚本统一在 `/tmp` 落临时文件，调用方不用管。

## 三种写法

### A. 新建文档或插入新图

```bash
python3 $S/figure.py wrap out/k1.svg > /tmp/k1.xml     # <whiteboard type="svg">…</whiteboard>
```

把这段 XML 放进 lark-doc 的 `docs +create --content` 或 `docs +update`（按 lark-doc 技能的写法定位插入点）。返回值里 `new_blocks` 中 `block_type: whiteboard` 的 `block_token` 就是画板 token，记下来，后面 `put` / `preview` 用。

一篇文档有多张图时，一张图一个 `<whiteboard>`，放在它解释的那段文字之后。

### B. 覆盖已有画板

```bash
python3 $S/figure.py put TOKEN out/k1.svg            # dry-run：只校验请求
python3 $S/figure.py put TOKEN out/k1.svg --yes      # 备份原画板 → 覆盖写入（失败自动重试 3 次）
```

画板 token 从文档里拿：`lark-cli docs +fetch` 的结果里 `<whiteboard token="…">`。token 不变，文档块不用动。lint 不过时 `put` 会拒绝，除非加 `--force`（不要用，除非用户明确要求）。

### C. 回滚

```bash
ls ~/.cache/lark-figure/bak/                          # TOKEN-时间戳.json
python3 $S/figure.py restore TOKEN ~/.cache/lark-figure/bak/TOKEN-xxx.json --yes
```

## 复核

```bash
python3 $S/figure.py preview TOKEN -o out/k1.lark.png
```

导出的是飞书服务端的真实渲染。导出图会被补成正方形，下面一片白是导出器加的，不是画板内容。和本地 `out/k1.png` 对比：文字有没有被截断、换行位置是否一致。

## 常见问题

| 现象 | 处理 |
|---|---|
| `permission denied` / 403 | 当前用户对文档没有编辑权限；让文档所有者加协作者，或换 `--profile` |
| `put` 成功但 `preview` 是旧图 | 服务端有延迟，脚本已自动重试；仍旧则隔几秒再跑一次 `preview` |
| `npx` 很慢或超时 | 第一次需要下载包；网络受限时 `build --no-render`，并告诉用户没做本地预览 |
| 文档里图很小 | 飞书按文档宽度缩放 1200 宽的画板，属正常；不要把画布改宽 |
