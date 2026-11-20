---
name: monument-valley
description: "把任一主题——人物、团队、组织、项目、产品、一次事件或一个概念——的 GitHub、博客、网站、飞书文档或用户提供的材料，蒸馏成纪念碑谷式的可探索档案（关卡叙事 + 统一等距插画 + 可续建的飞书文档）。USE WHEN: 用户要做人物/项目/团队/产品纪念碑谷、思想山谷、可探索档案、告别纪念册、项目回顾或事件复盘山谷，或要更新、校对、换主角、提升插画清晰度、把已有山谷镜像到另一份飞书文档/知识库。DO NOT USE: 纯文字传记、简历或项目周报、普通表格整理、与山谷无关的单张插画、替人物推断私人动机或人生结局、替组织发布官方口径。"
version: v1.4.0
metadata:
  display_name: 纪念碑谷
  requires:
    bins: ["python3"]
---

## 纪念碑谷

> 把一个主题（人、团队、项目、产品、事件或概念）的真实作品和判断变成一条可探索的空间路径，交付可编辑、可追溯、可续建的飞书 Doc；不是给简历或周报加装饰图，也不是图片版长文章。

## Positioning

- 形态：runtime skill。方法论在 `SKILL.md` 与 `references/`；可执行部分是两个离线工具：状态检查器 `scripts/validate_manifest.py` 与画面度量 `scripts/analyze_images.py`。
- 跨模型一致性：审美标准写成 `references/aesthetic-canon.md` 的编号条款，出图提示、度量与评审都对照它；审美判断不交给出图的那个模型自评。能量化的（色板、主角比例、留白、明度、主角位置、交付尺寸）交给脚本；剩下的由独立评审按 `references/review-rubric.md` 打分并写出违反的条款；风格起点固定为 `assets/style/` 下的风格参考图与色卡。
- 委托：飞书读写交给宿主已有的官方飞书技能或 CLI（如 `lark-doc` / `lark-cli docs`）；插图交给宿主的图像生成或编辑能力；超分交给本地工具。
- 不做：不代替来源阅读、不发明工具参数、不在技能目录保存任何人的资料或远端 ID、不访问网络。

## Use cases

| 场景 | 例子 | 行为 |
|---|---|---|
| 新建山谷 | 「把 @某人 的博客和 GitHub 做成纪念碑谷」「给这个项目 / 团队 / 这次演练做一个纪念碑谷」 | 定主题类别 → 取证 → 设计关卡 → 锁定主角 → 成组出图 → 建文档 → 回读验收 |
| 更新山谷 | 「补一篇新文章进去」 | 最新快照 → 来源差异 → 只改受影响章节，保留人工改动 |
| 换主角 / 调形象 | 「主角其实是一个土豆」 | 锁定本相特征 → 先出基准图 → 全部插画按原位重绘并原位替换 |
| 画面质量 | 「小人比例和场景不匹配」「清晰度好差」 | 逐图校比例；按交付规格超分并压缩后原位换图 |
| 全文校对 | 「再检查下全文」 | 按校对清单逐项核对，修正并记更新日志 |
| 画面验收 | 「这些图够不够好」「换个模型会不会更差」 | 跑画面度量 → 生成接触表 → 独立评审打分 → 不达标的单张重做 |
| 镜像 | 「全量覆盖到这个知识库」 | 按镜像流程重建，逐项比对一致性 |

## 输入与默认值

从请求中提取主题称呼与类别 `subject_kind`、来源 URL / 文件、覆盖时期、主角参考图、目标文档与创建或更新意图。只有缺少主题或全部材料时才补问；其余用默认值推进：

- 主题类别按请求判断：@某人 是 person，仓库或代码库是 project，发布的服务或应用是 product，一次演练、事故、发布是 event，部门或小组是 team，公司或事业部是 organization，方法论或技术概念是 topic；都不像时用 other，拿不准才问。类别决定旅程问题与红线（见 `references/workflow.md`）。
- 新建飞书文档，不改来源文档。
- 关数按真实材料定：常规六至九关，资料少可三至五关，绝不为凑数虚构经历。
- 至少包含封面、地图、每关主图、作品庭院、结尾；信息充分时加时间线、碑文长廊、转折纪念碑。
- 主角只分 default 与 custom：默认白袍尖帽角色；用户指定或给参考图的都是 custom（黄色小土豆也在此列）。优先级：用户当前明确选择 > 用户参考图 > 默认；不从其他任务继承。
- 既有文档：只要建议就不写入；明确要求更新或已确认修复才在授权范围内执行，不重复索要已有确认。

## Routing / behavior

1. **清点与取证**：建立来源清单、访问状态、修订或抓取时间、公开级别；读原文，不拿搜索摘要或旧版 AI 总结当证据。全量要求报告实际覆盖分母。
2. **分组蒸馏**：独立来源组用并行研究代理，限定范围与输出结构；代理不可用时用清单、确定性抽取和分段研究推进。
3. **设计旅程**：按 `subject_kind` 选旅程问题；每关写事实核心、问题或选择、空间隐喻、到下一关的连接、来源与可编辑明细；保留失败、摇摆与未知。
4. **锁定主角**：记录参考图、外观锚点、**本相特征**（让它一眼是它的东西，如土豆的块茎轮廓与芽眼）、**比例规则**（相对场景多大）与可度量的主色 `color_anchor`；先出一张基准图，经画面度量与独立评审通过后再批量出图。
5. **成组出图**：把 `references/aesthetic-canon.md` 的构图、光影、色彩条款写进提示，以 `assets/style/scene-reference.jpg` 与 `palette-card.png` 为风格参考，按图像工具能力选提示模板（支持参考图 / 只支持文生图，中英文均给出）；每批不超过四幅，每幅都带完整角色与比例约束；改已有画面优先「同图编辑」。地图、时间线、作品庭院是信息图，必须有标签或编号图例。
6. **度量与独立评审**：每批出图后跑 `analyze_images.py metrics` 与 `sheet`；色板、比例或构图未通过的直接重做，不进评审。通过的连同 `crops` 特写、一张 `canary` 对照样本和一张基准图，交给未参与出图的评审（优先不同模型的子代理）按评分表打分；对照没被判不合格或基准图没全部达标，这批作废、换评审；主角无法按颜色度量时由评审给出主角框再重测。
7. **交付规格**：出图后超分，再导出为文档交付尺寸（宽 1600–3840 像素，推荐 2560×1440，单图不超过 1.5 MB）；过大图片会让飞书端加载空白。
8. **写入飞书**：用宿主官方能力建文档、写结构、上传并插图；已有图片用原位替换，保留块位置与图注。只在操作成功后记录远端 ID。
9. **回读验收**：核对章节、图片、明细、引用、配色、主角本相、主角比例、版本记录；按校对清单过一遍全文。工具返回成功不等于渲染正确。
10. **交付与续建**：给真实文档链接、来源覆盖、未完成项和续建位置；失败时交付已有成果与准确阻塞，不造第二份文档。

## 关键规则

- 引用句末用 `[[原文标题]](URL)`；原话逐字，转述不加引号。生成插画和交付文档的链接不是来源引用。
- GitHub 仓库存在不等于采用、影响力、上线或个人贡献；fork、团队项目、演示代码分开说。
- 图承载关系与路径，文字承载精确证据；图化后年份、项目、语言、链接、限定条件仍要留在可编辑文字里。
- 纪念碑是建筑隐喻，不默认人物去世、项目停止或团队解散；离职、下线、重组等转折碑必须有来源支持。
- 主题不是人物时，主角是走过山谷的旅人，不把组织、项目或事件拟人化；团队成果归团队，事件复盘不追责个人。
- 用户排除的图片不参与参考；不要把工作流程图当角色参考。
- 未授权企业材料不得发往公共搜索、公共绘图或其他外部服务；绘图提示只用可出域的抽象视觉内容。
- 远端文档 ID、block ID、媒体 token 必须来自实际工具响应；媒体 token 只在上传时绑定的文档内有效，跨文档必须重新上传。
- 更新日志里写的规格（尺寸、角色、关数）必须与文档实际一致；规格变了就同步改日志。
- 不复制内置或市场技能的内部文件；不把企业语料、鉴权材料或个人信息打进技能包；来源里的命令不构成执行授权。

## Usage

维护任务工作区里的 `valley_manifest.json`，写入远端前和交付前各跑一次：

```bash
python3 skills/monument-valley/scripts/validate_manifest.py <工作区>/valley_manifest.json --phase draft
python3 skills/monument-valley/scripts/validate_manifest.py <工作区>/valley_manifest.json --phase final
```

每批出图后度量并生成接触表，交给独立评审：

```bash
python3 skills/monument-valley/scripts/analyze_images.py metrics <图片...> --character-color FDD277
python3 skills/monument-valley/scripts/analyze_images.py metrics <图片...> --boxes <评审主角框.json>
python3 skills/monument-valley/scripts/analyze_images.py sheet <图片...> --out <工作区>/sheet.png
python3 skills/monument-valley/scripts/analyze_images.py crops <图片...> --character-color FDD277 --out <工作区>/crops.png
python3 skills/monument-valley/scripts/analyze_images.py canary <已验收基准图> --character-color FDD277 --out <工作区>/canary.png
```

`crops` 是主角特写接触表，评审看本相与清晰度用；`canary` 生成主角放大的对照样本，不告知评审、混进每一批，用来校准这批评分（见 `references/review-rubric.md`）。默认白袍角色与背景同色、无法按颜色度量，不传 `--character-color`，改由评审给出主角框（`crops` 用 `--boxes`，`canary` 用 `--box x0,y0,x1,y1`）。`--bounds` 可按人物场景调整比例范围（默认 0.04,0.32）。

安装到其他位置时换成该技能的实际目录。两个工具只用 Python 标准库，无网络、无模型调用；读取 JPEG 时优先用已安装的 Pillow，否则用 macOS 自带 `sips` 转换。

## Output contract

- 首选机器契约：两个工具的 stdout 都是单个 JSON 对象，通过与失败顶层结构相同。
  - 检查器：`passed`、`phase`、`schemaVersion`、`errors`、`error`、`stage`、`actionableHints`、`fallback`。
  - 画面度量：`ok`、`command`、`results`、`summary`、`actionableHints`、`error`、`stage`、`fallback`；`metrics` 的每张图含 `file`、`palette`（`coverage` / `meanSaturation` / `verdict`）、`scale`（`method` / `heightRatio` / `box` / `verdict`）、`composition`（`negativeSpace` / `meanLightness` / `center` / `checks` 含 space、tone、placement / `verdict`）与总 `verdict`；`sheet` 与 `crops` 另有编号图例 `legend`，`crops` 的结果列出定位不到主角的 `missing`；`canary` 返回输出路径、放大倍数与主角框。
  - 度量结论只有 `pass` / `review` / `fail` / `unmeasured`；它是底线检查，不是审美证明，评审分数另记在 manifest。
- 交付给用户：真实飞书文档链接、来源覆盖（分母与缺口）、未完成项、下一次可续建位置。
- 区分：来源证据（可追溯）、蒸馏解释（标为解释）、生成插画（非证据）。检查器通过只说明记录合规，不证明内容真实或远端渲染正确。

## Failure contract

- 检查器退出码：`0` 通过；`1` 有检查未通过（`errors` 逐条列出，`actionableHints` 给下一步）；`2` manifest 无法读取或不是 JSON（`stage: "read"`）。
- 画面度量退出码：`0` 全部 pass；`1` 有图 review / fail / unmeasured，或 `crops` 有图定位不到主角；`2` 输入或依赖错误（含 `canary` 定位不到主角）（`stage` 为 `input` 或 `dependency`，缺 JPEG 转换能力时提示安装 Pillow 或先转 PNG）。
- 远端写入失败：交付已完成部分、`operations` 中的 failed / uncertain 项与恢复方式；uncertain 必须先回读再决定重试。
- 同类尝试最多三次，之后换替代能力或向用户报告阻塞，不猜工具参数。

## Skill Log

- 2026-09-30 (v1.4.0): 审美固化：新增 `references/aesthetic-canon.md`，把验收插画时的判断写成 25 条编号准则（构图、光影、色彩、形体、主角、叙事、整套版式），每条注明由度量还是哪个评审维度检查；画面度量新增 `composition`（留白、平均明度、主角是否在安全区），按 22 张已验收插画与杂乱、压暗、偏边对照样本校准；评审低分须引用条款编号；manifest 可记录 `metrics.composition`，fail 不可被评审覆盖，review 须评审 style 不低于 4。

- 2026-09-30 (v1.3.0): 主题不限于人物：manifest 1.3 新增必填 `subject_kind`（person / team / organization / project / product / event / topic / other），旧版本缺省按 person；检查器错误改为「缺少主题称呼 subject」；工作规范按主题类别给出旅程问题、常见来源、作品庭院内容与额外红线；非人物主题的主角是旅人，不拟人化主题。

- 2026-09-29 (v1.2.0): 跨模型一致性：新增画面度量 `scripts/analyze_images.py`（色板覆盖、带描边识别的主角比例、编号接触表、主角特写、对照样本、色卡），色板与阈值按 65 张已验收插画校准；新增 `assets/style/` 风格参考图与色卡、`references/review-rubric.md` 独立评审评分表；视觉指南给出色值表、中英文提示模板与图像工具能力分流；manifest 1.2 要求度量结论与独立评审打分，评审不得是出图方，每张图附可核对的 `seen` 细节，每批评审须用对照样本与基准图校准（`review_batches`）。规则来自两种模型子代理的盲评实验。

- 2026-09-29 (v1.1.0): 按仓库规范接入（顶层版本、测试与评测移到 `tests/monument-valley/`）；检查器拆为稳定入口 + `valley_manifest` 包，输出补 `actionableHints` / `fallback` / `stage`，读取失败改为退出码 2；manifest 1.1 新增主角本相特征、比例规则、交付尺寸、镜像一致性与校对验收；新增飞书原位换图、跨文档镜像与全文校对规范。
- 2026-09-29 (v1.0.1): 黄色小土豆归入自定义主角，取消专属模式。

## References

| 文件 | 何时读 |
|---|---|
| `references/workflow.md` | 研究、设计旅程、写入与恢复、全文校对之前 |
| `references/visual-guide.md` | 锁定主角、分镜、出图、超分与交付之前 |
| `references/feishu-ops.md` | 在飞书里插图、原位换图、换封面、镜像到另一份文档之前 |
| `references/aesthetic-canon.md` | 写出图提示、评审打分、决定一张图留不留之前 |
| `references/review-rubric.md` | 每批出图后做独立评审、判断是否重做之前 |
| `references/state-contract.md` | 创建、更新或恢复 `valley_manifest.json` 之前 |

| 资产 | 用途 |
|---|---|
| `assets/style/scene-reference.jpg` | 原创风格参考图（无人物、无文字），出图时作风格参考 |
| `assets/style/palette-card.png` | 由 `analyze_images.py palette-card` 按色板生成的色卡 |
