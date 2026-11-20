---
name: thought-distillation
description: "思想蒸馏：把一个人（或团队）的全部写作——博客、分享合集、索引页、方案文档——全文精读后，串成一条有张力的主线，产出图文并茂的飞书文档（主线 + 七幕论证 + 落地战场 + 思想之根 + 演进 + 张力与反方 + 路线图 + 金句 + 原文索引）。USE WHEN: 用户要蒸馏/提炼某人的思想、经验或方法论，'串一个主线'，'完全蒸馏他的思想'，或给出一组某人的文档/博客链接要求总结其 AI 落地经验。DO NOT USE: 单篇文档摘要、纪念碑谷式关卡叙事档案（use monument-valley）、把外部知识沉淀为 skill、竞品项目对比。"
version: v1.0.0
allowed-tools: Bash, Read, Write, Grep
metadata:
  display_name: 思想蒸馏
  requires:
    bins: ["python3", "bash", "lark-cli"]
---

# thought-distillation

> 不是摘要，是重组：把按时间写的零散文章，重组成"一条主线 + 一组带冲突的论证 + 一套可执行的落地清单"。

## When to use

- "把 XX 的文档/博客蒸馏一遍，串一个主线，给个飞书文档"
- "完全蒸馏他的思想 / 获取他在 AI 落地的经验"
- 用户给出一个人的索引页、分享合集、多篇原创文档链接
- 已有一份蒸馏但"图少、没张力"，要求重做

## When NOT to use

- 单篇文档解读或摘要 → 直接读
- 要关卡叙事 + 统一插画的可探索档案 → `monument-valley`（本 skill 产出的是论证型长文：主线、冲突、证据、反方）
- 想把外部材料变成 skill / rule → 不在本 skill 范围
- 项目或产品对比 → 竞品分析类 skill

## 质量门槛（交付前逐条自检）

- [ ] **一句话主线**能统摄 80% 以上的材料，且本身含一对张力（如"放手与攥紧""追着瓶颈走"）
- [ ] **全量覆盖**：合集每篇 + 索引页挂出的原创落地文档都读过；早期/生活类文章不当噪声，提炼为"思想之根"
- [ ] **张力**：每个核心命题写成"旧共识 ❌ vs 他的判断 ⚡ → 证据 → 代价/自我矛盾"；有"他和自己吵架"与"如果他是错的"两节
- [ ] **图 ≥ 12 张**，类型混搭（主线图、机制图、决策树、闭环、时序、饼图、思维导图 + 3–5 张 SVG 信息图）
- [ ] **证据**：引号内必须是原文逐字；翻译/转述/推断明确标注；预估数字和实测数字分开
- [ ] **边界**：写出样本量、合规、时效性等局限；源文档有密级则在文首标注且不外传

## 标准工作流

```
进度：
- [ ] 1 取材：抓取全部源文档 → 本地 markdown
- [ ] 2 拆分：合集按篇拆开，盘点篇目/日期/阅读量/原文链接
- [ ] 3 精读：按主题分 5–6 组并行子代理，产出结构化笔记
- [ ] 4 合成：定主线 → 七幕 → 战场 → 根 → 演进 → 张力 → 反方
- [ ] 5 配图：Mermaid 直接写；数据对比/张力/时间线派子代理画 SVG 并渲染自检
- [ ] 6 发布与验证：XML 自检 → 创建/覆盖飞书文档 → 导出全部画板检查
```

**1 取材**：用 `bash scripts/fetch_docs.sh <outdir> <url-or-token>...` 串行抓取（并发会触发限流 99991400）。索引页里挂的原创方案/落地文档要一并抓——它们是"落地经验"的一手证据，常比公开分享更硬。无权限的文档记下来，交付时说明。

**2 拆分**：合集用 `python3 scripts/split_collection.py <合集.md> <outdir>` 按 `## N.` 标题拆篇；从合集索引表提取标题、日期、浏览量、原文链接（阅读量是读者信号，可用于演进图气泡）。

**3 精读**：按主题分组（本质与范式 / 工具与编排 / 知识与记忆 / 逆向与解读 / 业务落地 / 早期与生活 + 已有蒸馏评估），每组一个前台并行子代理，提示词模板见 [references/subagent-prompts.md](references/subagent-prompts.md)。不要用后台子代理（中断即丢）。

**4 合成**：按 [references/doc-structure.md](references/doc-structure.md) 的骨架写 DocxXML。先写主线与七幕标题，再填证据；每一幕先写冲突再写结论。

**5 配图**：Mermaid 只用 flowchart / sequenceDiagram / pie / mindmap（画板稳定支持）；对比数据、天平/拔河类张力图、气泡时间线用 SVG，派子代理按模板画并自行渲染验证。

**6 发布与验证**：
```bash
python3 scripts/check_xml.py doc.xml          # UTF-8、未转义 &、svg path 存在、画板计数
cd <xml 所在目录>                              # svg path 只接受相对路径
lark-cli docs +create --as user --content - < doc.xml
# 重做时覆盖原文档以保留链接：
lark-cli docs +update --doc <id> --as user --command overwrite --content - < doc.xml
```
然后对返回的每个 whiteboard token 执行 `lark-cli docs +media-download --type whiteboard --token <t> --output ./chk/N.png --as user`，用 Read 逐张看图；再 `docs +fetch --scope outline` 核对大纲。

DocxXML 与画板坑点速查见 [references/lark-docxml-gotchas.md](references/lark-docxml-gotchas.md)。

## 关键约束

- 只读源文档，不改动作者原文
- 已有他人蒸馏时，先评估其主线/遗漏/误读，再在交付中写"差异"一节
- 子代理的临时验证文档（如"SVG 草稿-勿用"）交付时告知用户清理
- 交付回复：先给链接与主线一句话，再说覆盖范围、图数、已知局限
