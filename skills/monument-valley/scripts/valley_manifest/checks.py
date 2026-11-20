"""离线、只读的山谷状态检查；只核对是否按契约记录，不证明语义或远端资源真实。"""

import re
from urllib.parse import urlparse

from . import config

HEX = re.compile(r"[0-9A-Fa-f]{6}")
GROUPS = (("sources", "id"), ("claims", "id"), ("sections", "key"),
          ("images", "id"), ("operations", "id"))


def is_feishu_doc_url(url):
    parsed = urlparse(url if isinstance(url, str) else "")
    host = parsed.hostname or ""
    trusted = any(host == base or host.endswith("." + base) for base in config.FEISHU_HOSTS)
    return (parsed.scheme == "https" and trusted
            and any(parsed.path.startswith(p) for p in config.FEISHU_DOC_PATHS))


def validate(data, phase="draft"):
    if not isinstance(data, dict):
        return ["根节点必须为对象"]
    return Checker(data, phase).run()


class Checker:
    def __init__(self, data, phase):
        self.data = data
        self.final = phase == "final"
        schema = data.get("schema_version")
        level = config.SCHEMA_VERSIONS.index(schema) if schema in config.SCHEMA_VERSIONS else 0
        self.schema = config.SCHEMA_VERSIONS[level]
        self.strict, self.v12, self.v13 = level >= 1, level >= 2, level >= 3
        self.errors = []
        self.mode = None
        self.rows = {}
        self.batches = {}

    def require(self, ok, message):
        if not ok:
            self.errors.append(message)

    def run(self):
        data = self.data
        self.require(data.get("schema_version") in config.SCHEMA_VERSIONS,
                     "schema_version 必须为 " + "、".join(config.SCHEMA_VERSIONS) + " 之一")
        self.require(isinstance(data.get("subject"), str) and bool(data["subject"].strip()), "缺少主题称呼 subject")
        kind = data.get("subject_kind")
        self.require(kind in config.SUBJECT_KINDS or (kind is None and not self.v13),
                     "主题类别 subject_kind 必须为 " + "、".join(config.SUBJECT_KINDS) + " 之一")
        self.require(bool(data.get("version")), "缺少内容版本")
        document, character = data.get("document", {}), data.get("character", {})
        self.require(isinstance(document, dict), "文档 document 必须为对象")
        self.require(isinstance(character, dict), "主角 character 必须为对象")
        if not isinstance(document, dict) or not isinstance(character, dict):
            return self.errors
        self.require(document.get("mode") in config.DOCUMENT_MODES, "文档模式不合法")
        self.check_character(character)
        self.collect_groups()
        self.check_sources()
        self.check_coverage()
        self.check_claims()
        self.check_sections()
        if self.v12:
            self.check_batches()
        for iid, image in self.rows["images"].items():
            self.check_image(iid, image)
        self.check_operations()
        self.check_mirrors(data.get("mirrors", []))
        if self.final:
            self.check_final(document)
        return self.errors

    def check_character(self, character):
        self.mode = character.get("mode")
        self.require(self.mode in config.CHARACTER_MODES, "主角模式不合法")
        self.require(bool(character.get("appearance_anchor")), "缺少主角形象锚点")
        self.require(bool(character.get("selection_reason")), "缺少主角选择依据")
        custom = self.mode == "custom"
        if custom:
            self.require(bool(character.get("reference_asset")), "自定义主角缺少参考图")
        if self.strict:
            self.require(bool(character.get("scale_rule")), "主角缺少比例规则 scale_rule")
            traits = character.get("identity_traits")
            self.require(not custom or (isinstance(traits, list) and bool(traits)),
                         "自定义主角缺少本相特征 identity_traits")
        if self.v12:
            self.check_measurable(character)

    def check_measurable(self, character):
        color = character.get("color_anchor")
        self.require(color is None or (isinstance(color, str) and HEX.fullmatch(color.lstrip("#")) is not None),
                     "主角 color_anchor 须为 6 位十六进制色值")
        bounds = character.get("scale_bounds")
        valid = (isinstance(bounds, list) and len(bounds) == 2
                 and all(isinstance(v, (int, float)) for v in bounds) and 0 < bounds[0] < bounds[1] <= 1)
        self.require(bounds is None or valid, "主角比例 scale_bounds 须为 0–1 之间的 [low, high]")

    def collect_groups(self):
        for name, key in GROUPS:
            rows = self.data.get(name)
            self.require(isinstance(rows, list), f"{name} 必须为数组")
            self.rows[name] = {}
            for row in rows if isinstance(rows, list) else []:
                self.add_row(name, key, row)
        self.require(bool(self.rows["sources"]), "来源清单不能为空")
        self.require(bool(self.rows["sections"]), "章节不能为空")
        self.require(bool(self.rows["images"]), "图片计划不能为空")
        self.require(isinstance(self.data.get("gaps"), list), "gaps 必须为数组")

    def add_row(self, name, key, row):
        if not isinstance(row, dict):
            self.errors.append(f"{name} 的条目必须为对象")
            return
        value = row.get(key)
        if not isinstance(value, str) or not value:
            self.errors.append(f"{name} 缺少有效 {key}")
            return
        self.require(value not in self.rows[name], f"{name} 存在重复标识 {value}")
        self.rows[name][value] = row

    def references(self, row, field, target, label):
        values = row.get(field)
        self.require(isinstance(values, list), f"{label} 的 {field} 必须为数组")
        if not isinstance(values, list):
            return []
        for value in values:
            self.require(isinstance(value, str) and value in target,
                         f"{label} 引用了不存在的 {field}: {value}")
        return [v for v in values if isinstance(v, str) and v in target]

    def check_sources(self):
        for sid, source in self.rows["sources"].items():
            self.require(source.get("status") in config.SOURCE_STATES, f"来源 {sid} 状态不合法")
            self.require(source.get("visibility") in config.VISIBILITIES, f"来源 {sid} 缺少有效保密类别")
            self.require(bool(source.get("title")), f"来源 {sid} 缺少标题")
            self.require(bool(source.get("url") or source.get("local_path")), f"来源 {sid} 缺少位置")

    def check_coverage(self):
        coverage, sources = self.data.get("coverage", {}), self.rows["sources"].values()
        if not isinstance(coverage, dict):
            self.errors.append("覆盖 coverage 必须为对象")
            return
        self.require(coverage.get("discovered") == len(sources), "覆盖：发现数量与来源清单不一致")
        for state in sorted(config.SOURCE_STATES):
            self.require(coverage.get(state) == sum(s.get("status") == state for s in sources),
                         f"覆盖：来源统计 {state} 不一致")
        self.require(isinstance(coverage.get("inventory_complete"), bool), "覆盖：缺少清点完成状态")
        if any(s.get("status") in {"partial", "unavailable"} for s in sources):
            self.require(bool(self.data.get("gaps")), "覆盖：部分读取或不可访问来源必须记录缺口")

    def check_claims(self):
        sources = self.rows["sources"]
        for cid, claim in self.rows["claims"].items():
            ids = self.references(claim, "source_ids", sources, f"命题 {cid}")
            kind = claim.get("kind")
            self.require(kind in config.CLAIM_KINDS, f"命题 {cid} 类别不合法")
            self.require(bool(claim.get("text")), f"命题 {cid} 没有正文")
            self.require(kind == "interpretation" or bool(ids), f"命题 {cid} 缺少证据")
            for sid in ids:
                self.require(sources[sid].get("status") in config.READABLE_SOURCE_STATES,
                             f"命题 {cid} 使用了未读取来源 {sid}")
            if kind == "quote":
                self.require(bool(claim.get("exact_quote")) and claim.get("quote_verified") is True,
                             f"命题 {cid} 的引语未逐字核验")

    def check_sections(self):
        claims, images = self.rows["claims"], self.rows["images"]
        for key, section in self.rows["sections"].items():
            label = f"章节 {key}"
            cids = self.references(section, "claim_ids", claims, label)
            iids = self.references(section, "image_ids", images, label)
            sids = self.references(section, "source_ids", self.rows["sources"], label)
            self.require(bool(section.get("title")), f"{label} 缺少标题")
            self.require(isinstance(section.get("editable_details"), list), f"{label} 缺少可编辑明细")
            self.require(bool(section.get("content_hash")), f"{label} 缺少内容指纹")
            used = {s for cid in cids for s in claims[cid].get("source_ids", []) if isinstance(s, str)}
            self.require(used.issubset(set(sids)), f"{label} 遗漏命题来源")
            for iid in iids:
                self.require(images[iid].get("section_key") == key, f"{label} 与图片 {iid} 归属冲突")

    def check_image(self, iid, image):
        sections = self.rows["sections"]
        key = image.get("section_key")
        linked = isinstance(key, str) and key in sections
        self.require(linked, f"图片 {iid} 引用无效章节")
        self.require(not linked or iid in sections[key].get("image_ids", []), f"图片 {iid} 未出现在章节清单")
        self.require(image.get("role") in config.IMAGE_ROLES, f"图片 {iid} 角色类别不合法")
        self.require(image.get("character_mode") == self.mode, f"图片 {iid} 主角不一致")
        self.require(image.get("status") in config.IMAGE_STATES, f"图片 {iid} 状态不合法")
        if image.get("role") in config.INFO_ROLES:
            self.require(bool(image.get("required_labels")), f"信息图 {iid} 缺少标签")
            self.require(bool(image.get("editable_details")), f"信息图 {iid} 缺少可编辑明细")
            self.require(image.get("label_mode") in config.LABEL_MODES - {"none"}, f"信息图 {iid} 没有标注方案")
        if self.final:
            self.check_image_final(iid, image)

    def check_image_final(self, iid, image):
        self.require(image.get("status") == "embedded", f"图片 {iid} 尚未嵌入")
        self.require(bool(image.get("file_token") and image.get("remote_block_id")), f"图片 {iid} 缺少远端标识")
        self.require(image.get("visual_checked") is True, f"图片 {iid} 未完成视觉检查")
        self.require(not image.get("required_labels") or image.get("labels_checked") is True,
                     f"图片 {iid} 未核对标签")
        if self.strict:
            self.require(image.get("scale_checked") is True, f"图片 {iid} 未核对主角比例")
            self.check_delivery(iid, image)
        if self.v12:
            review = image.get("review") if isinstance(image.get("review"), dict) else {}
            self.check_metrics(iid, image.get("metrics"), review)
            self.check_review(iid, image.get("generator"), review)

    def check_metrics(self, iid, metrics, review):
        metrics = metrics if isinstance(metrics, dict) else {}
        palette, scale = metrics.get("palette"), metrics.get("scale")
        self.require(palette in config.METRIC_VERDICTS and scale in config.METRIC_VERDICTS,
                     f"图片 {iid} 缺少度量结论 metrics.palette / metrics.scale")
        style = (review.get("scores") or {}).get("style") if isinstance(review.get("scores"), dict) else None
        styled = isinstance(style, int) and style >= 4
        self.require(palette == "pass" or (palette == "review" and styled),
                     f"图片 {iid} 色板度量为 {palette}，灰区须评审 style 不低于 4")
        composition = metrics.get("composition", "pass")
        self.require(composition == "pass" or (composition == "review" and styled),
                     f"图片 {iid} 构图度量为 {composition}，灰区须评审 style 不低于 4（见 aesthetic-canon）")
        self.require(scale == "pass", f"图片 {iid} 主角比例度量为 {scale}，须度量通过（可用评审主角框重测）")

    def check_review(self, iid, generator, review):
        reviewer = review.get("reviewer")
        self.require(bool(generator), f"图片 {iid} 缺少出图来源 generator")
        self.require(bool(reviewer) and reviewer != generator, f"图片 {iid} 评审 reviewer 须独立于出图 generator")
        scores = review.get("scores") if isinstance(review.get("scores"), dict) else {}
        for key in config.SCORE_DIMENSIONS:
            value = scores.get(key)
            ok = isinstance(value, int) and not isinstance(value, bool) and config.SCORE_FLOORS[key] <= value <= 5
            self.require(ok, f"图片 {iid} 评审 {key} 分数缺失或低于 {config.SCORE_FLOORS[key]}")
        self.require(review.get("verdict") == "pass", f"图片 {iid} 评审结论不是 pass")
        seen = review.get("seen")
        self.require(isinstance(seen, str) and bool(seen.strip()), f"图片 {iid} 评审缺少可核对的所见细节 seen")
        batch = self.batches.get(review.get("batch"))
        self.require(batch is not None, f"图片 {iid} 评审未指向已校准的评审批次 batch")
        self.require(batch is None or batch.get("reviewer") == reviewer, f"图片 {iid} 评审人与批次 batch 不一致")

    def check_batches(self):
        batches = self.data.get("review_batches", [])
        self.require(isinstance(batches, list), "评审批次 review_batches 必须为数组")
        for batch in batches if isinstance(batches, list) else []:
            bid = batch.get("id") if isinstance(batch, dict) else None
            if not isinstance(bid, str) or not bid or bid in self.batches:
                self.errors.append("评审批次缺少唯一 id")
                continue
            if self.calibrated(bid, batch):
                self.batches[bid] = batch

    def calibrated(self, bid, batch):
        before = len(self.errors)
        self.require(bool(batch.get("reviewer")), f"评审批次 {bid} 缺少 reviewer")
        self.require(batch.get("images_visible") is True, f"评审批次 {bid} 未确认评审看得到图片 images_visible")
        canary = batch.get("canary_scale")
        self.require(isinstance(canary, int) and not isinstance(canary, bool)
                     and 1 <= canary < config.SCORE_FLOORS["scale"],
                     f"评审批次 {bid} 对照样本 canary_scale 须低于 {config.SCORE_FLOORS['scale']}，否则该评审未失效样本")
        anchor = batch.get("anchor_scores") if isinstance(batch.get("anchor_scores"), dict) else {}
        self.require(all(isinstance(anchor.get(k), int) and anchor.get(k) >= config.SCORE_FLOORS[k]
                         for k in config.SCORE_DIMENSIONS),
                     f"评审批次 {bid} 基准图 anchor_scores 未全部达标，该评审过严或未看清")
        return len(self.errors) == before

    def check_delivery(self, iid, image):
        width, height, size = (image.get(k) for k in ("pixel_width", "pixel_height", "bytes"))
        if not all(isinstance(v, int) and v > 0 for v in (width, height, size)):
            self.errors.append(f"图片 {iid} 缺少交付尺寸 pixel_width/pixel_height/bytes")
            return
        self.require(config.DELIVERY_MIN_WIDTH <= width <= config.DELIVERY_MAX_WIDTH,
                     f"图片 {iid} 交付宽度 {width} 超出 {config.DELIVERY_MIN_WIDTH}–{config.DELIVERY_MAX_WIDTH}")
        self.require(size <= config.DELIVERY_MAX_BYTES,
                     f"图片 {iid} 交付体积 {size} 字节超过 {config.DELIVERY_MAX_BYTES}")

    def check_operations(self):
        for oid, op in self.rows["operations"].items():
            self.require(op.get("status") in config.OPERATION_STATES, f"操作 {oid} 状态不合法")
            self.require(bool(op.get("input_hash")), f"操作 {oid} 缺少输入指纹")
            self.require(not self.final or op.get("status") == "verified", f"操作 {oid} 未回读确认")

    def check_mirrors(self, mirrors):
        if not isinstance(mirrors, list):
            self.errors.append("镜像 mirrors 必须为数组")
            return
        seen = set()
        for index, mirror in enumerate(mirrors, start=1):
            label = f"镜像 #{index}"
            if not isinstance(mirror, dict):
                self.errors.append(f"{label} 必须为对象")
                continue
            mid = mirror.get("id")
            self.require(bool(mid) and mid not in seen, f"{label} 缺少唯一文档 ID")
            seen.add(mid)
            self.require(is_feishu_doc_url(mirror.get("url", "")), f"{label} 缺少有效飞书 docx 或 wiki 地址")
            if self.final:
                self.check_parity(label, mirror.get("parity"))

    def check_parity(self, label, parity):
        parity = parity if isinstance(parity, dict) else {}
        for key in config.MIRROR_PARITY_KEYS:
            self.require(parity.get(key) is True, f"{label} 未核对一致性: {key}")

    def check_final(self, document):
        self.require(is_feishu_doc_url(document.get("url", "")), "文档：缺少有效形态的飞书 docx 或 wiki 地址")
        self.require(bool(document.get("id")) and document.get("revision") is not None, "文档：标识或修订缺失")
        self.require(bool(self.rows["operations"]), "操作：缺少写入与回读操作记录")
        checks = self.data.get("validation", {})
        checks = checks if isinstance(checks, dict) else {}
        for key in config.FINAL_CHECKS[self.schema]:
            self.require(checks.get(key) is True, f"最终验收未通过: {key}")


def hints_for(errors):
    hints = []
    for prefix, hint in config.HINTS:
        if hint not in hints and any(prefix in message for message in errors):
            hints.append(hint)
    return hints
