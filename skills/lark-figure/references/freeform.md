# 手写 SVG 通道（标准图型覆盖不到时）

先确认真的需要：大多数“特殊图”拆成两张标准图、或用 `stack` 拼起来就够了。手写意味着失去自动排版，出错概率高很多。

## 规则

手写 SVG 和生成的 SVG 过同一套 lint，所以必须遵守同样的约束：

1. 根元素 `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 H" width="1200" height="H">`，H 在 420–960。
2. 第一块是画布：`<rect x="0" y="0" width="1200" height="H" rx="16" fill="#FAFBFD" stroke="#DEE0E3"/>`。
3. 主标题 `<text x="40" y="58" font-size="28" font-weight="bold" fill="#1F2329">一句判断</text>`；副标题 y=92、14px、`#646A73`；来源 `y=H-24`、12px、`#646A73`、以“来源：”开头。
4. 颜色只取 `assets/theme.json` 的 families 和 neutral。先用灰，彩色系 1–2 个够用就不加（lint 的硬上限是 `max_families`，当前 5）。
5. 只用 rect / circle / ellipse / line / polyline / polygon / path / text / g。不用 filter、渐变、pattern、clipPath、mask、image、style、foreignObject，不用 skew / matrix。
6. 文字一律 `<text>`，每行一个 `<text>`；宽度按 taste.md 第 4 节估（中文常规 1.06em、粗体 1.2em），框要留余量。
7. 连线用正交 `<polyline>`，箭头用 `<polygon>` 三角形；线不要穿过文字。
8. 内容离画布边至少 40px。

## 流程

```bash
python3 $S/figure.py lint my.svg --render     # lint + 画板自检 + 本地 PNG（my.png）
```

看 PNG，按 `references/lint.md` 改，直到 `ok: true`。之后的写入飞书步骤和生成的图一样（`wrap` / `put` / `preview`）。

## 想让引擎直接支持？

同一类图手写了两次以上，就该在 `scripts/lfig/charts/` 加一个图型：一个模块提供 `DOC`（含完整 example）、`validate(spec)`、`draw(cv, spec, x, y, w)`，在 `charts/__init__.py` 注册，再在 `dev/lark-figure/` 补测试。颜色、字号一律从 `T` 取。
