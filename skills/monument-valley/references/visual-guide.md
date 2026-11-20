# 视觉与分镜规范

## 主角选择

默认是纪念碑谷式的小型白袍、尖帽角色，低细节面孔和简洁轮廓；不是黄色小人。使用纪念碑谷的视觉灵感，不冒称官方合作或复用未经授权的游戏原画。

用户给图时先确认这张确实是角色参考而非排除图。保留外形轮廓、身体比例、主色、面部特征、服饰、四肢粗细和典型配件。真人照片只做用户授权的艺术化呈现，不从照片推断身份、职业、性格或经历。

黄色小土豆是自定义主角的一种，与机器人、动物或其他用户角色走同一流程，不设独立模式、开关或专属确认。不能从其他文档自动继承。

主题不是人物时，主角是走过这座山谷的旅人，而不是主题本身：默认白袍角色照常可用；项目或产品已有吉祥物、团队有自己的形象时，经用户确认后作为 custom 主角。不要把组织、项目或事件画成一个人，也不给事件配一个替罪的角色。

`character` 记录 mode、reference_asset、appearance_anchor、identity_traits、scale_rule 与 selection_reason。自定义主角没有可用参考图时先占位并说明需要图片，不拿无关图顶替。

### 本相：它首先是什么

外观锚点（颜色、描边、眼睛）只保证「像同一个角色」，不保证「是这个东西」。先写出 2–4 条**本相特征**：去掉它，角色就会被认成别的东西。

- 土豆：略不规则的椭圆块茎轮廓、表皮浅褐斑点、几处小芽眼；不能是光滑蛋形，不能有喙或翅膀（否则读成鸡蛋或小鸡）。
- 机器人：可见的接缝、铆钉或屏幕脸；不能被画成穿衣服的人。
- 动物：物种的标志部位（耳形、尾巴、花纹）。

每条提示词同时写外观锚点和本相特征，并写出要避免的误读，例如「不要蛋形、不要鸟喙」。验收时问一句：只看这张图，陌生人会说它是什么？

### 比例：它相对场景多大

写一条**比例规则**，以场景里的参照物表达，不用像素：例如「约一扇门洞或三四级台阶高；与人群同框时只比旁人略高」。封面、章节图、信息图都按同一规则，除非画面叙事明确需要特写。

生成模型会反复把主角放大成画面主体。对策：

- 改已有画面时用「同图编辑」，提示里写明「保持大小与位置不变，不要放大（DO NOT ENLARGE）」。
- 已经偏大就做相对缩小：「缩小到当前约 60%，站在原来的台面中央」，比重写绝对尺寸更稳。
- 每批出图后并排看一遍，把明显偏大的单张重做；比例漂移会在后续批次复发，每批都要查。

## 统一美术语言

完整的审美标准见 `aesthetic-canon.md`（编号条款，出图、度量与评审共用）；下面是出图时最常用的几条。

- 约 30 度等距视角，浮岛、几何柱廊、阶梯、不可能桥、拱门、悬台；画面中有清楚的起点与出口。
- 低饱和、柔和长投影、干净哑光材质、大块留白；主角是小比例但可辨识的视觉锚点。
- 风格起点固定：每次任务都把 `assets/style/scene-reference.jpg`（原创、无人物、无文字）和 `assets/style/palette-card.png` 作为风格参考，而不是让模型从形容词自由发挥。

### 色板

形容词在不同图像模型里理解不同，以色值为准。下表由 65 张已验收插画聚类得到，与 `scripts/valley_manifest/config.py` 的 `PALETTE` 一致；画面度量按它计算覆盖率。

| 名称 | 色值 | 名称 | 色值 | 名称 | 色值 | 名称 | 色值 |
|---|---|---|---|---|---|---|---|
| 象牙 | `#F8F5EE` | 砂杏 | `#F2DCC2` | 暖砂 | `#E6BF92` | 陶土 | `#C18F72` |
| 雾青 | `#D3E2E5` | 天青 | `#A9CCE0` | 灰青 | `#98AFAE` | 深青 | `#6F868C` |
| 石灰 | `#CBC8C7` | 岩灰 | `#566366` | 雾紫 | `#B9A7C9` | 薰紫 | `#9D96C3` |
| 暮紫 | `#72788B` | 长春蓝 | `#BBC3FA` | 樱粉 | `#F6C9CD` | 蜜桃 | `#F6AD8A` |
| 玫陶 | `#BB7769` | 苔绿 | `#B0B68C` | 深棕 | `#825646` | 金黄 | `#F2C14E` |

大面积用前两行（象牙、砂、青、灰）；紫、粉、蜜桃、玫陶用于塔楼与天色；金黄只作点睛。提示词里写「只用附带色卡的颜色」，并附上色卡。
- 横向构图适合文档阅读；主角造型与比例不随章节改变，环境随思想变化。
- 正向提示可用冷蓝/青绿，提醒用暖黄，风险用浅红，推演用淡紫。飞书端只用当前支持的配色；自定义 RGB 不生效就换官方近似色，不反复替换同一失效属性。
- 标题层级、图注、段间距和引语样式一致。绘图不是给每个段落机械加背景。

## 分镜字段

每张图记录 scene_id、section_key、role、叙事动作、证据关联、composition、主角约束、required_labels、editable_details、caption、生成状态与质检状态。

role 是 cover / chapter / map / timeline / gallery / quote / ending 之一。封面和章节图可以无字；map、timeline、gallery 必须有能传递结构的编号、短标签或标记，不得「无文字」生成后仍称标注完成。

## 按图像工具能力选做法

先确认当前图像工具能做什么，再选路径；不要假设所有工具都支持参考图或精确尺寸。

| 工具能力 | 主角一致性 | 改比例 / 修细节 | 风格 |
|---|---|---|---|
| 支持参考图与同图编辑 | 每张都附主角基准图 | 同图编辑，写「保持其余不变、不要放大」 | 附风格参考图与色卡 |
| 只支持参考图、不支持编辑 | 附主角基准图 + 完整锚点 | 重新生成该张，把问题写成否定约束 | 附风格参考图与色卡 |
| 只支持文生图 | 每条提示都写完整锚点、本相、比例；不承诺一致 | 重新生成；三次不过交给用户 | 在提示里逐个写色值 |

多数图像模型对英文提示的遵从度高于中文；工具不明确时用英文模板，中文只用于图内短标签（最好改为叠字）。输出尺寸以工具实际返回为准，交付前统一按「清晰度与交付规格」处理。

## 提示模板

### 章节图

纪念碑谷灵感的原创等距浮岛建筑，只用附带色卡的颜色并对齐风格参考图，柔和长阴影与大块留白；整体明亮，单一柔光从左上来，投影偏冷紫、不用纯黑；平面无纹理，细节靠拱、阶梯、窗洞切分；浮岛完整留在画框内、四周有天空；主角站在路径上、在画面中部，不贴边。主角严格使用同一参考图：[外观锚点]；本相：[本相特征]，不要[易误读形态]。比例：[比例规则]，不要放大成画面主体。场景：[一个隐喻场景]。动作：[主角的可见动作]。入口：[前一关连接]，出口：[下一关线索]。不换装、不添加未经依据的真实人物或奖杯，保留图注空间，画面内无文字。

### 信息图

同一主角、视角、调色与比例规则。将已核验信息变成[路线图/时间石阶/作品庭院]：[准确节点数量及关系]。短标签仅为：[完整标签清单]。长说明不进画面。路线方向明确、标签不遮挡、元素位置可与图下明细一一对应。不以装饰物冒充完成节点。

### 同图编辑

编辑这张图：除[要改的部分]外保持一切不变（建筑、配色、构图、主角位置与大小）。[具体修改]。不要放大主角，不要新增文字。

### English templates

Chapter: Original isometric floating-island architecture inspired by Monument Valley aesthetics (not a copy of any game level), about 30-degree view. Use ONLY the colors of the attached palette card; match the attached style reference. Soft long shadows, clean matte materials, generous empty space. Bright high-key lighting from one soft light source at the upper left; shadows tinted cool violet, never pure black. Flat untextured surfaces; detail comes from arches, stairs and window cuts. The whole floating island stays inside the frame with sky around it. Keep the protagonist on the path, well inside the frame, never at the edge. Protagonist strictly matches the attached character reference: [appearance anchors]. It must clearly read as [identity, e.g. a potato: irregular tuber outline, pale brown speckles, small sprout eyes]; NOT [misreadings, e.g. an egg, a chick, a beak]. Scale: [scale rule, e.g. about the height of one doorway]; do NOT make it the main subject. Scene: [metaphor]. Action: [visible action]. Entrance: [link from previous level]; exit: [hint of next level]. No extra characters, no trophies, no text, no letters, no logos.

Infographic: Same protagonist, view, palette card and scale rule. Turn the verified information into [route map / timeline steps / works courtyard] with exactly [N] nodes connected as [relations]. Short labels only: [list]. Clear direction, labels never covered, positions match the legend below the image.

Edit: Edit this image. Keep EVERYTHING else identical: architecture, colors, composition, and the protagonist's size and position. Only change: [change]. DO NOT ENLARGE the protagonist. Do not add any text.

Shrink: Keep everything identical, but shrink the protagonist to about [60]% of its current size, standing in the same spot. Fill the freed area with the existing background.

## 信息标注与可编辑细节

优先生成可读短标签；中文错字或密度过高时，用生成背景加本地确定性 SVG / PNG 文字叠层，指定字体并核对渲染。没有叠字能力时，用图内清晰编号加图下同序图例，并说明这是编号图例。

时间线保留不确定日期；非线性作品不可硬排为连续进步。人物画像碑可用符号，不捏造长相。离职碑只用来源中的事件与短引语，不添悼亡语气。

## 清晰度与交付规格

图像生成常见输出只有约 1280×720，放进文档偏糊；直接上传原生 5000 像素级大图又会让飞书端加载缓慢甚至空白。按这条链路交付：

1. 生成或编辑得到定稿（记录原始尺寸）。
2. 本地超分 4 倍，插画风格优先用动漫/插画模型（如 Real-ESRGAN `realesrgan-x4plus-anime`）。
3. 缩放导出为交付尺寸：推荐 2560×1440 JPEG，质量约 88；宽度保持 1600–3840 像素，单图不超过 1.5 MB。
4. 逐张校验尺寸、体积、MIME 与文件签名，再上传。

封面同样按此规格。超分只能提升锐度，不能修复画错的主角或比例；先改画，再超分。

## 画面度量

`scripts/analyze_images.py metrics` 只量能量化的底线，结论为 pass / review / fail / unmeasured：

- **色板**：按 ΔE 15 统计像素落在色板附近的比例与平均饱和度。覆盖率不低于 0.75 且饱和度不超过 0.33 为 pass；覆盖率低于 0.6 或饱和度高于 0.4 为 fail；其间为 review。65 张已验收插画全部 pass；对照样本（饱和度加倍、色相轮换）约四分之三被拦下，漏掉的多是本来就接近灰色、改色后仍在风格内的图。
- **主角比例**：给出主角主色（`--character-color`，如土豆 `FDD277`）后，找出与主色相近、且边缘带深色描边的色块，取描边得分最高者为主角，计算其高度占画面高度的比例；默认范围 0.04–0.32（已验收插画实测 0.06–0.26）。描边用来排除同色的太阳、灯光。两个候选相近时判 review。
- **量不了的情况**：默认白袍角色与象牙背景同色，主色不独特的角色也一样，这时不传颜色，由独立评审在接触表上给主角框，脚本按框计算比例。

- **构图**：留白（相邻像素明度几乎不变的比例）不低于 0.6 为 pass、低于 0.45 为 fail；平均明度不低于 62 为 pass、低于 50 为 fail；知道主角位置时，主角中心须在安全区（横向 0.25–0.75、纵向 0.25–0.85）内，否则 review。对应 `aesthetic-canon.md` 的 C2、L2、C3。

度量通过不等于好看；它把「明显跑偏」挡在评审之前，并让不同模型的出图有同一条底线。审美部分按 `review-rubric.md` 由独立评审对照 `aesthetic-canon.md` 打分。

## 批量与质量

一次生成或编辑至多四张，各提示都包含同一角色锚点、本相特征与比例规则。优先同一参考的编辑链；把已验收最好的一张作为后续风格参考。工具不支持一致性参考时如实说明，不承诺像素级一致。

下载后校验成功状态、MIME、图片签名与尺寸；403 HTML 不是 JPEG。重试不超过三次；只重做失败的那一张，不重跑全部。

用 `analyze_images.py sheet` 做按顺序标号的接触表（每张最多六个缩略图），用 `crops` 做主角特写接触表（缩略图太小，看不出本相细节与像素化），优先检查基准主角、封面、地图；图中文字在全尺寸下核对。记录哪些图真正看过，不能自动把 visual_checked 或 scale_checked 设为 true；出图方的自检不能代替独立评审。

最终检查：本相可辨（不被误读成别的东西）；轮廓、脸与服装一致；比例符合规则；没有多手或额外主角；节点数等于文本数；连接不表达错误因果；标签可读；颜色与正文提示语义协调。做不到的检查列入遗留。
