# 飞书写入与镜像操作

以下做法在 2026-09 的 `lark-cli`（`docs +fetch` / `+update` / `+media-upload` / `+media-insert` / `+resource-update`、`api`）上实际跑通。命令与参数会演进：用之前先跑 `lark-cli docs <子命令> --help` 确认，与当前帮助冲突时以帮助为准。所有 `<...>` 都来自当次工具响应，不从别处复制。

## 通用约定

- 以当前用户身份操作（`--as user`），权限不足时报告，不绕行。
- 批量脚本里给每次 CLI 调用接 `</dev/null`，避免它吞掉循环的标准输入。
- 上传文件用相对路径，在文件所在目录执行。
- 静默更新提示：`LARKSUITE_CLI_NO_UPDATE_NOTIFIER=1 LARKSUITE_CLI_NO_SKILLS_NOTIFIER=1`。

## 读取

- 带块 ID 的结构：`docs +fetch --doc <doc_id> --detail with-ids`；图片块按文档顺序出现为 `<img id="...">`。
- 图片块的 token 与尺寸：`api GET /open-apis/docx/v1/documents/<doc_id>/blocks --params '{"page_size":500}'`，筛 `block_type == 27`。查询参数走 `--params`，不要拼进路径。

## 新插图

`docs +media-insert` 把图追加到文档末尾（可带 `--caption`、`--align`），适合按顺序新建。要放到中间，先追加再用 `+update --command block_move_after` 移动。

## 原位替换已有图片

换主角、改比例、提清晰度时不删块重插，保留位置与图注：

1. 以**该图片块**为父节点上传：`docs +media-upload --file <本地图> --parent-type docx_image --parent-node <image_block_id> --doc-id <doc_id>`，取返回的 `file_token`。
2. 替换：`api PATCH /open-apis/docx/v1/documents/<doc_id>/blocks/<image_block_id> --data '{"replace_image":{"token":"<file_token>","width":<宽>,"height":<高>}}'`；需要时一并传 `"caption":{"content":"..."}`。
3. 检查返回的 `image.width` 与预期一致，再把操作标 applied；回读确认后标 verified。

## 封面

`docs +resource-update --doc <doc_id> --type cover --file <本地图>`；`+resource-download --type cover` 可取回核对。

## 镜像到另一份文档或知识库

媒体 token 绑定在上传时的文档上，**不能跨文档复用**。直接用含源文档 `<img>` token 的 XML 做 `overwrite`，会得到部分成功甚至空白文档。可行流程：

1. 读源文档完整 XML，在每个 `<img>` 处切分成若干段，记录每张图的本地文件与图注。
2. 用第一段 `overwrite` 目标文档，然后交替执行：对下一张图 `media-insert`（带图注），再 `append` 下一段文字。
3. 回读目标文档，逐项比对：正文（去掉 ID 与标签后逐字一致）、图片数与顺序、图注、背景色块数量、更新日志。切分边界处的段落最容易丢，逐段核对。
4. 目标文档的封面单独用 `+resource-update` 设置。
5. 在 manifest 的 `mirrors` 里记录目标 ID、地址与四项一致性结果。

之后源文档再换图时，镜像文档的图片块 ID 与源文档不同，要从镜像文档重新读取块 ID 并各自上传替换。

## 局部文字修改

- 一句话内的替换用 `str_replace --pattern <原文> --content <新文>`；跨段或整块用 `block_replace`。
- 往表格加行（如更新日志）：读出整张表的 XML，去掉 `id` 属性，在 `</tbody>` 前插入新行，再 `block_replace` 整张表。

## 验收提醒

工具返回成功不等于用户看得到。图片空白时，先下载每个图片 token 与本地文件比对哈希，确认服务端完好；完好则多为体积过大或预览未生成，按 visual-guide 的交付规格缩小后原位替换。
