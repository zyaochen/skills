# lark-figure 开发

不随技能发布的测试和生成脚本。

```bash
python3 -m unittest discover -s dev/lark-figure -v     # 离线测试：样例、压力样例、校验消息、每条 lint 规则、字宽拟合、CLI
python3 dev/lark-figure/gen_spec_doc.py               # 改了图型模块的 DOC 后，重新生成 references/spec.md 和 examples/*.json
```

改排版引擎后，除了单测，还要跑一遍真实渲染：

```bash
for f in skills/lark-figure/examples/*.json; do python3 skills/lark-figure/scripts/figure.py build $f -o /tmp/lfig; done
```

逐张用图片查看器看 `/tmp/lfig/*.png`；需要验证飞书端效果时，按 `skills/lark-figure/references/publish.md` 建一篇临时文档写入并 `preview`。

`plans/` 是 v1.1 的计划、评审汇总、实施指令和交接记录；`eval/` 是跨模型评测的用例和脚本（见其中 README）。

字宽系数（`assets/theme.json` 的 `measure`）是用 whiteboard-cli 对探针字符串的 `text_shape.width` 拟合的；`test_matches_board_probe` 里记着实测值。whiteboard-cli 升级后若报 `text-overflow`，先重跑探针再调系数。
