"""山谷状态检查的规则表；枚举、阈值和提示只在这里定义。"""

# 按新旧排序；新增项只对声明了该版本或更高版本的状态强制。
# 1.1：主角本相、比例规则、交付尺寸、镜像一致性、校对。
# 1.2：机器度量（色板、主角比例）与独立评审打分。
# 1.3：山谷主题不限于人物，需声明 subject_kind。
SCHEMA_VERSIONS = ("1.0", "1.1", "1.2", "1.3")

PHASES = ("draft", "final")
# 1.3 之前的状态没有 subject_kind，按人物处理。
SUBJECT_KINDS = ("person", "team", "organization", "project", "product", "event", "topic", "other")
DEFAULT_SUBJECT_KIND = "person"
DOCUMENT_MODES = {"create", "update"}
CHARACTER_MODES = {"default", "custom"}
SOURCE_STATES = {"read", "partial", "unavailable", "duplicate", "excluded"}
READABLE_SOURCE_STATES = {"read", "partial"}
VISIBILITIES = {"public", "internal", "user_private"}
CLAIM_KINDS = {"fact", "paraphrase", "quote", "interpretation"}
IMAGE_ROLES = {"cover", "chapter", "map", "timeline", "gallery", "quote", "ending"}
INFO_ROLES = {"map", "timeline", "gallery"}
IMAGE_STATES = {"planned", "generated", "uploaded", "embedded", "failed"}
LABEL_MODES = {"none", "in_image", "overlay", "numbered_legend"}
OPERATION_STATES = {"planned", "applied", "verified", "failed", "uncertain"}

FEISHU_HOSTS = ("feishu.cn", "larkoffice.com", "larksuite.com")
FEISHU_DOC_PATHS = ("/docx/", "/wiki/")

FINAL_CHECKS_V10 = (
    "remote_readback",
    "character_consistency",
    "labels_verified",
    "details_preserved",
    "citations_checked",
    "changelog_present",
)
FINAL_CHECKS_V11 = FINAL_CHECKS_V10 + ("scale_matched", "proofread")
FINAL_CHECKS_V12 = FINAL_CHECKS_V11 + ("metrics_checked", "independent_review")
FINAL_CHECKS = {"1.0": FINAL_CHECKS_V10, "1.1": FINAL_CHECKS_V11, "1.2": FINAL_CHECKS_V12,
                "1.3": FINAL_CHECKS_V12}

MIRROR_PARITY_KEYS = ("text", "images", "captions", "colors")

# 文档内嵌图的交付尺寸：宽度下限保清晰，宽度与体积上限保加载。
DELIVERY_MIN_WIDTH = 1600
DELIVERY_MAX_WIDTH = 3840
DELIVERY_MAX_BYTES = 1_500_000

# 色板：从 65 张已验收插画（本次土豆版、蛋形版与原版）聚类得到的风格锚点。
PALETTE = {
    "象牙": "F8F5EE", "砂杏": "F2DCC2", "暖砂": "E6BF92", "陶土": "C18F72",
    "雾青": "D3E2E5", "天青": "A9CCE0", "灰青": "98AFAE", "深青": "6F868C",
    "石灰": "CBC8C7", "岩灰": "566366", "雾紫": "B9A7C9", "薰紫": "9D96C3",
    "暮紫": "72788B", "长春蓝": "BBC3FA", "樱粉": "F6C9CD", "蜜桃": "F6AD8A",
    "玫陶": "BB7769", "苔绿": "B0B68C", "深棕": "825646", "金黄": "F2C14E",
}
# 校准结果：已验收 65 张全部落在 pass；饱和度加倍或色相轮换的偏风格样本约四分之三落在 review/fail。
PALETTE_DELTA_E = 15
PALETTE_PASS_COVERAGE = 0.75
PALETTE_PASS_SATURATION = 0.33
PALETTE_FAIL_COVERAGE = 0.6
PALETTE_FAIL_SATURATION = 0.4
PALETTE_SAMPLE_STEP = 1

ANALYSIS_WIDTH = 320
VERDICT_ORDER = ("pass", "unmeasured", "review", "fail")

# 构图：按 22 张已验收插画与杂乱、压暗、偏边对照样本校准（见 references/aesthetic-canon.md）。
# 已验收图留白 0.62–0.94、平均明度 68–97、主角中心横向 0.33–0.67、纵向 0.29–0.82。
QUIET_GRADIENT = 4
SPACE_PASS = 0.6
SPACE_FAIL = 0.45
TONE_PASS = 62
TONE_FAIL = 50
SAFE_ZONE = (0.25, 0.25, 0.75, 0.85)
# 主角色块：与主色的 ΔE 阈值；必须带深色描边才算主角，用来区分太阳、灯光等同色景物。
CHARACTER_DELTA_E = 18
CHARACTER_MIN_AREA = 0.0008
CHARACTER_MAX_CANDIDATES = 8
CHARACTER_RIVAL_AREA = 0.5
OUTLINE_MAX_LIGHTNESS = 40
OUTLINE_RADIUS = 3
OUTLINE_MIN_SCORE = 0.6
# 主角高度占画面高度的比例；已验收插画实测 0.06–0.26。
DEFAULT_SCALE_BOUNDS = (0.04, 0.32)

SCORE_DIMENSIONS = ("identity", "scale", "style", "clarity", "narrative")
SCORE_FLOORS = {"identity": 4, "scale": 4, "style": 3, "clarity": 3, "narrative": 3}
METRIC_VERDICTS = {"pass", "review", "fail", "unmeasured"}

# 主角特写：框外扩倍数与边长；对照样本默认放大倍数（放大后主角高度远超比例上限）。
CROP_MARGIN = 1.8
CROP_SIZE = 384
CANARY_ZOOM = 2.5

SHEET_GAP = 12
SHEET_BACKGROUND = (250, 248, 243)
SHEET_LABEL_BG = (40, 40, 40)
SHEET_LABEL_FG = (255, 255, 255)
SHEET_DIGIT_SCALE = 4
DIGITS = {
    "0": (7, 5, 5, 5, 7), "1": (2, 6, 2, 2, 7), "2": (7, 1, 7, 4, 7), "3": (7, 1, 7, 1, 7),
    "4": (5, 5, 7, 1, 1), "5": (7, 4, 7, 1, 7), "6": (7, 4, 7, 5, 7), "7": (7, 1, 1, 1, 1),
    "8": (7, 5, 7, 5, 7), "9": (7, 5, 7, 1, 7),
}

EXIT_PASSED = 0
EXIT_FAILED = 1
EXIT_UNREADABLE = 2

# 错误前缀 -> 下一步建议；按出现顺序去重后输出。
HINTS = (
    ("schema_version", "新任务把 schema_version 设为 1.3（旧状态可保留 1.0–1.2），见 references/state-contract.md。"),
    ("主题", "写明 subject（主题称呼）与 subject_kind：person、team、organization、project、product、event、topic 或 other。"),
    ("主角", "补齐 character 的 mode、appearance_anchor、selection_reason；custom 还要真实参考图与 identity_traits。"),
    ("比例", "为主角写 scale_rule，并在逐图目检后再置 scale_checked。"),
    ("交付", "按 visual-guide 的交付规格重新导出：宽 1600–3840 像素、单图不超过 1.5 MB。"),
    ("来源", "对照来源清单修正状态、保密类别与位置；未读来源不能支撑命题。"),
    ("覆盖", "让 coverage 计数与 sources 实际状态逐项一致。"),
    ("命题", "给事实、转述、引语补 source_ids；引语需逐字核验。"),
    ("章节", "检查章节的 claim_ids / image_ids / source_ids 引用与内容指纹。"),
    ("图片", "核对图片的章节归属、角色、状态、远端标识和目检记录。"),
    ("信息图", "为地图、时间线、作品庭院补标签清单、可编辑明细与标注方案。"),
    ("操作", "状态不明的操作先回读远端，再改为 verified 或 failed。"),
    ("镜像", "镜像文档须逐项比对正文、图片数、图注与配色后再标记 parity。"),
    ("度量", "用 scripts/analyze_images.py metrics 重新度量，把 palette / scale 结论原样写进 images[].metrics。"),
    ("评审", "换一个未参与出图的评审（优先不同模型的子代理），只看接触表与规则，按 review-rubric 打分。"),
    ("批次", "每批评审混入 canary 对照样本与已验收基准图：canary 须被判不合格、基准图须全部达标，否则换评审重来。"),
    ("最终验收", "只有实际完成回读与人工检查后才把 validation 对应项置 true。"),
    ("文档", "填写真实的飞书 docx 或 wiki 地址、文档 ID 与修订号。"),
    ("读取或结构错误", "确认 manifest 路径存在且是 UTF-8 JSON 对象。"),
)
