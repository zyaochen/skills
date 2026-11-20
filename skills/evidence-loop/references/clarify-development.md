# 开发场景的澄清

开发场景用两张图做约定：**现状图**（as-is）描述现在有什么，**蓝图**（blueprint）描述做完后应该有什么。蓝图里的每个节点是一个要实现的元素，`depends` 规定构建顺序。交付时还要有一张**竣工图**（as-built），由智能体根据实际交付的代码绘制，与蓝图逐项对照。

## 1. 先画现状图

读代码，只画与本任务相关的部分：已有的服务、存储、外部依赖和它们之间的调用。现状图让人确认"你理解的起点"是对的，同时让裁判知道蓝图里哪些元素是新增的（`elements_new`）。

## 2. 蓝图 JSON 格式

```json
{
  "meta": {"title": "订单导出服务 · 目标蓝图"},
  "nodes": [
    {"id": "api", "label": "导出接口", "sublabel": "POST /exports", "kind": "flow",
     "accept": "python3 -m pytest -q tests/export/test_api.py"},
    {"id": "worker", "label": "导出工作者", "kind": "service", "row": 0, "col": 1}
  ],
  "edges": [{"from": "api", "to": "worker", "label": "入队", "dashed": false}],
  "regions": [{"label": "异步链路", "wraps": ["worker"]}],
  "depends": {"worker": ["api"]}
}
```

| 字段 | 规则 |
|---|---|
| `nodes[].id` | 必填，匹配 `[A-Za-z0-9_-]+`，全图唯一；`attempt --elements` 用它认领 |
| `nodes[].label` / `sublabel` | 可选的显示文字，必须是字符串 |
| `nodes[].kind` | `service`、`store`、`external`、`decision`、`flow` 之一，决定节点上的色点 |
| `nodes[].accept` | 可选的**逐元素验收命令**：认领该元素的检查点上必须通过，`verify` 时再跑一次；失败时元素保持待定 |
| `nodes[].row` / `col` | 可选整数；所有节点都给出时按网格摆放，否则按最长前驱链自动分层 |
| `edges` | `from` / `to` 必须指向已有节点；`label`、`dashed` 可选；允许成环（只影响画图） |
| `regions` | 用虚线框把一组节点框起来，`wraps` 是节点 ID 列表 |
| `depends` | **构建顺序**：`{"a": ["b"]}` 表示实现 a 之前 b 必须已实现。不能自依赖、不能引用不存在的节点、不能成环 |

`accept` 让"元素已实现"有了各自的证据，而不只依赖一条笼统的回归检查。验收命令和蓝图一起被冻结，循环里不能改。

`edges` 表达运行时关系，`depends` 表达实现顺序，二者经常相似但不必相同。`init` 会用 Kahn 算法把元素分成可并行的批次写进契约（`batches`），成环时直接拒绝并列出涉及的节点。

完整例子见技能目录下的 `assets/blueprint.json`。写好后先预览：

```bash
python3 <skill>/scripts/evloop_render.py design/blueprint.json   # 生成 design/blueprint.html
```

渲染页面不含脚本、不引用外部资源，可以直接用浏览器以 `file://` 打开，也可以作为附件发给人。

## 3. 和人确认范围

| 项 | 参数 | 说明 |
|---|---|---|
| 可编辑范围 | `--editable` | 新代码与竣工图要落在这里 |
| 已有测试 | 视情况放进 `--frozen` | 防止循环通过改测试来"变绿" |
| 回归检查 | `--check-cmd` | 可选。给出时每轮跑它，绿了才算实现；不给时每轮都是人工检查点 |
| 竣工图路径 | `--asbuilt` | 必须位于 `--editable` 之内，交付前由智能体写出 |
| 生成路径 | `--generated` | 构建产物、缓存目录 |

蓝图和现状图在 `init` 时自动加入冻结集合：循环中改动它们的尝试一律无效。开发场景不接受 `--test-cmd`，用 `--check-cmd`。

## 4. init 示例

```bash
python3 <skill>/scripts/evloop.py --home "$PWD/.evloop/runs/order-export" init \
  --scenario development \
  --editable src/export docs/asbuilt.json \
  --frozen tests/legacy \
  --blueprint design/blueprint.json --asis design/asis.json \
  --asbuilt docs/asbuilt.json \
  --check-cmd "python3 -m pytest -q"
```

`init` 会把两张图复制进运行目录并渲染成 `blueprint.html`、`asis.html`，契约里记录 `elements`、`depends`、`batches`、`elements_new`。若给了 `--check-cmd`，基线也会跑一次并记录退出码（开发场景不要求基线通过或失败）。

## 5. 呈交审阅

一次性给人看：现状图、蓝图（附渲染页面路径）、构建批次、可编辑与冻结范围、回归检查命令、竣工图会写在哪里。人改图时，改完重新预览、重新呈交；批准后再 `init`。
