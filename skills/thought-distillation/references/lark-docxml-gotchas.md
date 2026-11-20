# 飞书 DocxXML / 画板坑点速查

权威文档：`lark-cli skills read lark-doc/references/lark-doc-xml.md`、`lark-doc-whiteboard.md`。以下是实战踩过的点。

## CLI

| 坑 | 处理 |
|-|-|
| 输出夹杂更新提示，JSON 解析失败 | `export LARKSUITE_CLI_NO_UPDATE_NOTIFIER=1` |
| `@file` 只接受相对路径 | 用 `--content -` 走 stdin；画板 `path="@./svg/x.svg"` 需在对应目录执行 |
| 并发 fetch 报 99991400 限流 | 串行 + sleep + 重试（`scripts/fetch_docs.sh`） |
| 3380004 无权限 | 记录并在交付中说明，不要反复重试 |
| 重做文档想保留链接 | `docs +update --command overwrite` |
| 局部修改 | `--command str_replace --pattern` 或 `block_insert_after --block-id`（先 `+fetch --detail with-ids`） |

## XML

- `&` 必须写 `&amp;`；正文中的 `<`（如 "<70%"）写 `&lt;`
- checkbox：`<checkbox done="false">`（不是 `checked`）
- grid：`<grid><column width-ratio="0.5">…</column><column width-ratio="0.5">…</column></grid>`，比例和为 1（没有 `cols` 属性）
- callout 子块只允许 p / ul / ol / checkbox；不能放 table、whiteboard、grid
- 跨租户文档用 `<a href>` 链接比 `<cite type="doc">` 稳
- 表格：`<table><colgroup><col width="160"/>…</colgroup><thead>…</thead><tbody>…</tbody></table>`，表头可加 `background-color="light-gray"`

## 画板

- Mermaid 稳定类型：flowchart、sequenceDiagram、pie、mindmap（另有 class、gantt）；柱状/象限/时间线类改用 SVG
- Mermaid 换行用 `<br/>`，不要用 `\n`；节点文字含括号/引号时整体包在 `"…"` 里
- mindmap 节点文本里避免撇号、冒号等符号
- pie 小扇区标签会挤在一起，可接受或合并为"其他"
- SVG：必须有 viewBox；只用 rect/circle/ellipse/polygon/line/polyline/path/text/g；禁止 pattern/clipPath/mask/非阴影 filter；径向渐变可能渲染成白色 → 用纯色
- SVG 中空格可能被吞，名称和数值之间用 `<tspan dx>` 控间距；弯引号字距异常 → 用直引号
- Write 工具写含中文的 SVG 可能损坏编码 → 用 shell heredoc / python 写，`xmllint --noout` 校验
- 预览导出（`+media-download --type whiteboard`）会把彩色/白色文字画成深色，属预览问题，文档内显示正常
