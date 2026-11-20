# 续建状态契约

状态属于单次任务工作区，不写进技能目录，也不公开上传内部来源清单。保留真实远端标识是为了恢复操作，访问令牌和签名下载地址不属于持久状态。

## valley_manifest.json 字段

- `schema_version`：新任务用 `1.3`；`1.0`–`1.2` 仍可读，只强制各自版本及以前的字段。
- `subject`：山谷主题的称呼（人物用本人自选称呼，其余用正式名称）。
- `subject_kind`（1.3 必填，旧版本可选、缺省按 person）：`person`、`team`、`organization`、`project`、`product`、`event`、`topic`、`other` 之一；决定 `workflow.md` 里用哪组旅程问题与红线。
- `document`：`mode` 为 create/update；`id`、`url`、`revision` 在创建与读取成功后填写，未知为 null，不给示例假 token。`url` 可以是飞书 `/docx/` 或 `/wiki/` 地址。
- `character`：`mode` 仅为 default/custom；`reference_asset`、`appearance_anchor`、`selection_reason`。custom 要真实本地参考；黄色小土豆也使用 custom，无独立模式或专属确认字段。1.1 另需：
  - `scale_rule`：相对场景的比例规则（如「约门洞高，人群中只略高」）。
  - `identity_traits`：custom 必填，2–4 条本相特征（如「不规则块茎轮廓」「浅褐斑点与芽眼」）。
  - 1.2 可选：`color_anchor`（主角主色 6 位色值，如 `FDD277`，供画面度量；默认白袍角色不填）、`scale_bounds`（`[low, high]`，主角高度占画面比例，默认 `[0.04, 0.32]`）。
- `sources`：每项 `id`、`title`、`url` 或 `local_path`、`status`、`visibility`、`content_hash`；status 为 read/partial/unavailable/duplicate/excluded；visibility 为 public/internal/user_private。
- `coverage`：`discovered`、`read`、`partial`、`unavailable`、`duplicate`、`excluded` 与清单一致，`inventory_complete` 布尔值；声明「全量」须清点完成且无 partial/unavailable。
- `claims`：`id`、`text`、`kind`（fact/paraphrase/quote/interpretation）、`source_ids`；quote 还需 `exact_quote` 和 `quote_verified: true`。无来源的解释可保留，但不能作为事实或引语。
- `sections`：`key`、`title`、`claim_ids`、`image_ids`、`editable_details` 字符串列表、`source_ids`、`content_hash`、`remote_block_ids`。事实段必须有来源。
- `images`：`id`、`role`、`section_key`、`character_mode`、`status`（planned/generated/uploaded/embedded/failed）、`local_path`、`file_token`、`remote_block_id`、`required_labels`、`editable_details`、`label_mode`（none/in_image/overlay/numbered_legend）、`labels_checked`、`visual_checked`。1.1 另需 `scale_checked`，以及交付文件的 `pixel_width`、`pixel_height`、`bytes`。1.2 另需：
  - `generator`：出图的模型或工具标识。
  - `metrics`：`analyze_images.py metrics` 的结论原样填写，`palette` 与 `scale` 各为 pass/review/fail/unmeasured，可附 `height_ratio`、`coverage`；可选 `composition`（pass/review/fail），填了就检查：fail 不可被评审覆盖，review 须评审 style 不低于 4。
  - `review`：`reviewer`（不得与 `generator` 相同）、`scores`（`identity`、`scale`、`style`、`clarity`、`narrative` 五项 1–5 整数）、`verdict`（pass/fail）、`seen`（这张图里一处可核对的具体细节）、`batch`（所属评审批次 id），格式见 `review-rubric.md`。
- `review_batches`（1.2）：每批评审一条，含 `id`、`reviewer`、`images_visible`（评审确认看得到图）、`canary_scale`（评审给对照样本的 scale 分，须低于下限）、`anchor_scores`（评审给基准图的五项分数，须全部达标）。未通过校准的批次不能被图片引用。
- `operations`：`id`、`section_key`、`action`、`status`（planned/applied/verified/failed/uncertain）、`input_hash`。uncertain 必须先回读，不直接再执行。
- `mirrors`（可选）：每项 `id`、`url`、`parity`；`parity` 为 `text`、`images`、`captions`、`colors` 四个布尔值，实际比对后才置 true。镜像文档的图片块另行记录，不与源文档混用。
- `validation`：`remote_readback`、`character_consistency`、`labels_verified`、`details_preserved`、`citations_checked`、`changelog_present` 六个布尔值；1.1 再加 `scale_matched`、`proofread`；1.2 再加 `metrics_checked`、`independent_review`。初始全部 false，实际验证后才置 true。
- `gaps`：诚实记录未读来源、未能核验之处。空清单不代表自动无缺口。
- `version`：当前内容版本，按实际变化更新。

## 状态与恢复规则

稳定 key 标识概念章节，远端 block ID 标识某次实际块。内容哈希用于识别变化，不用于授权，也不用来猜事实真假。

写操作之前把 planned 落盘；收到明确成功再写 applied；回读确认才写 verified。网络超时写 uncertain。恢复时先查远端及当前修订，避免重复插图、重复造表、覆盖用户编辑。来源改动只重蒸馏受影响 source_id，再定位关联 claim 和 section。

新建文档未指定主角时使用 default，不自动继承其他文档的自定义角色。用户改主角或修正本相时要更新全部相关图（含封面与镜像文档），先生成并检查基准图；原位替换后把相关图片的 `visual_checked`、`scale_checked` 重置为 false，重新目检。

## 迁移

- `1.2 → 1.3`：把 `schema_version` 改为 `1.3`，补 `subject_kind`；已有的人物山谷填 `person`，其余字段不变。
- `1.1 → 1.2`：把 `schema_version` 改为 `1.2`，按需补 `color_anchor`；对每张图跑度量、做独立评审后填 `generator`、`metrics`、`review`，并补 `review_batches`，再补 `validation.metrics_checked` / `independent_review`。没做就不填，不从旧的 `visual_checked` 推断。
- `1.0 → 1.1`：把 `schema_version` 改为 `1.1`，补 `scale_rule`、custom 的 `identity_traits`、每张图的 `scale_checked` 与交付尺寸、`validation.scale_matched` / `proofread`。未实际核对的一律填 false，不因迁移置 true。
- 旧的 `potato` 模式：先备份，再把 `character.mode` 及图片的 `character_mode` 统一改为 `custom`；保留参考图、造型、选择依据和远端标识，删除旧的 `explicit_choice` 字段。没有参考图就补齐，不伪造资源。迁移只改本地分类，不代表用户要求换角色，不自动重绘或改远端。检查器不接受旧模式，也不静默修改输入。

## 检查器边界

`scripts/validate_manifest.py` 使用 Python 标准库，无网络、无写入、无模型调用。它不读图片：图片由 `scripts/analyze_images.py` 度量，结论写进 manifest 后再由检查器核对。

- draft：字段、唯一 ID、引用完整性、覆盖统计、来源归因、主角选择、信息图标签计划、镜像地址；1.1 另查比例规则与本相特征。
- final：再要求真实形态的飞书文档地址、非空 ID 与修订、图片嵌入、视觉与标签验收、所有操作 verified、最终验收项完成；1.1 另查每图比例目检、交付尺寸（宽 1600–3840、不超过 1.5 MB）与镜像四项一致性；1.2 另查每图度量结论（色板 pass，或 review 且评审 style 不低于 4；比例必须 pass）与独立评审（评审不是出图方，五项分数不低于下限，结论 pass，有 `seen`，指向同一评审人且通过校准的批次）。检查器只核对记录的对照与基准分数，不核实 `seen` 是否属实；抽查 `seen` 是编排方的职责。

输出与退出码见 `SKILL.md` 的 Output / Failure contract。它只能检查是否按契约记录，不能证明声明为 true 的人工检查真的执行，也不能验证远端 token 有效；最终完成判断仍须结合工具日志和实际回读。
