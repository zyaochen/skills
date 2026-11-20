# lint 报错码与改法

`figure.py build` 和 `figure.py lint` 都会跑。`E` 级拦截交付，`W` 级要看图确认。`wb_check` 是画板自己的检查（whiteboard-cli --check），里面的 `text-overflow` 同样拦截；`node-overlap` 只计数，不拦截（条形压在底槽上、强调框压在表格上都是有意的）。

| 码 | 级别 | 意思 | 用 spec 生成时怎么改 | 手写 SVG 时怎么改 |
|---|---|---|---|---|
| PARSE | E | SVG 不是合法 XML，或没有 viewBox | 不会出现；出现请报 bug | 修语法，根元素加 viewBox |
| FORBID | E | 用了画板不支持的元素（filter、渐变、mask、image、style…） | — | 删掉，用纯色块和叠放代替 |
| TRANSFORM | E | skew / matrix 变换 | — | 只用 translate / rotate / scale |
| LT | E | 文本里有 `&lt;` | 把 `<` 写成 `＜` 或“小于” | 同左 |
| PALETTE | E | 用了色板外的颜色 | 不会出现 | 换成 theme.json 里的颜色 |
| FAMILIES | E | 彩色系超过 `theme.json` 的 `max_families`（当前 5，等于色板的全部彩色系，所以默认主题下不会触发） | 把背景元素的 tone 改成 `base` | 同左 |
| DARK | E | 浅色字，或字压在深色块上 | 不会出现 | 浅底深字 |
| TITLE | E | 顶部没有 24–30px 粗体主标题 | 写 `title` | 按 taste.md 第 2 节放标题 |
| TITLE-LABEL | W | 标题像标签不像判断 | 改成一句结论 | 同左 |
| SOURCE | E | 底部没有“来源：”行 | 写 `source` | 加来源行 |
| SIZE | W | 宽不是 1200 或高超出 420–960 | 太高就拆图或减少条目 | 同左 |
| FONT | E | 字号小于 12 | 不会出现 | 调大 |
| CANVAS | E | 文字超出画布 | 缩短文字 | 移回画布内 |
| MARGIN | E | 形状伸进 40px 边距的一半以内 | 报 bug（引擎应已处理） | 内容收进边距 |
| OVERLAP | E | 两段文字重叠 | 缩短标签、减少条目 | 挪开 |
| SPILL | E | 文字一部分在框里一部分在框外 | 缩短文字 | 加宽框或换行 |
| CROSS | E | 线或箭头穿过文字 | 缩短标签；`graph` 里调整阶段内节点的上下顺序；仍有则报 bug | 改走线或挪字 |
| DENSITY | W | 文字超过 90 段 | 拆图 | 拆图 |
| SIZE-WIDTH | E | 宽不是任一 house 宽（1000 / 1200 / 1300）也不在 `size_width_range` 之内 | 在 spec 写 `aspect: "narrow" \| "normal" \| "wide"` 选一个；或回 1200 | 把 viewBox 宽度对齐到 1000 / 1200 / 1300 |
| COLOR-OVERUSE | E | 饱和彩色元素超过 25 个（bg/bg2 浅色不计） | 把次要元素的 tone 改成 `base`；多张卡同 tone 是合法，但要意识到每个彩色元素都会算 | 减少饱和色的 fill/stroke 使用，保留浅底 |
| TONE-AS-CLASSIFIER | E | 同一 family 饱和元素 ≥ 15 个，tone 被当成元素分类器 | 用 `id: "①"` / `icon: "✗"` / `card_style: "outlined"` 区分元素，tone 只表达状态 | 同左 |
| PRIMARY-DUPLICATE | E | compare 里 `primary: true`（或 highlight:true）的卡多于 1 张 | 只保留推荐的那一张 | 一张图只留一个 colorline |

### `data-role` 豁免（不参与 COLOR-OVERUSE 计数）

以下元素是「数据 / 结构性彩色」，不计入 `COLOR-OVERUSE` 的饱和元素数：

- `track` / `bar`:bars 的底槽和数据条（数据本体）
- `series-point`:line 折线上的数据点圆圈（数据本体）
- `value-chip`:compare 行内带 tone 的 value chip（信息层级信号）
- `side-kv`:layers 侧栏 `{label, value}` 键值对的 value chip（信息层级信号）

这些元素由排色 family 决定，每个 ≤ 几个，加起来仍受 `FAMILIES`（≤ `max_families`）限制。

`stage: "spec"` 的报错（不是 lint）：字段缺失、数量超限，以及“内容放不下”——`graph` 的连线标签旁边没有空位、`sequence` 的消息超过两行、`cycle` 的中心文字超过两行。消息里写了改法，改 spec 重跑。

`notes`（不是 lint，是排版时的提示）：

- `… read as "…"`：字段名、图型名或颜色词写成了近似写法，脚本按 `scripts/lfig/normalize.py` 里的固定对照表改了过来，图不受影响。下次按正确写法写。
- `… is not a field here and was ignored`：这个字段不存在，**里面的内容没有画出来**。按提示的相近字段名改掉重跑。
- `N items are emphasised`：强调超过 2 处，只留主标题说的那一两处。
- `no source given`：没写来源，已填“来源：本文整理”。数字有出处就写上。
- `uses N color families`：颜色太多，同 FAMILIES。
- `figure is Npx tall`：超过 1100 高。这一条是 `stage: "spec"` 的报错，不出图；按消息里列的选项改，没有列 `density` / `aspect` 就是它们对这张图不够用，拆图。
