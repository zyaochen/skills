"""evidence-loop：澄清 → 循环 → 交付 的机械裁判。仅依赖 Python 标准库（3.8+）。

模块划分：
  util          退出码、异常、时间、哈希、原子写、路径规则、文件锁
  gitops        git 调用封装（-z 解析、禁用重命名检测、兼容旧版 git）
  runner        运行约定命令：合并输出、进程组超时清理、容错解码
  render        图 JSON 校验、架构图 / 过程图 SVG、自包含 HTML 页面
  constitution  项目宪法（长期规则）的加载与漂移检测
  contract      契约目录：密封的 contract.json、attempts.jsonl、raw/ 原始输出
  scenarios     代码场景的纯逻辑：得分、改进判定、蓝图依赖、元素进度、路线账本
  judge         init / start / smoke / attempt / source / status / resume / verify / approve / relocate / doctor
  text          研究 / 文档场景的硬检查：标题、篇幅、禁用内容、注入文本、论断逐字核对
  sources       来源抓取、HTML 转文本、按内容哈希的只读快照
  rubric        细则评审：随机分隔的提示词、K 次采样中位数、好 / 差样本校准
  research      研究 / 文档场景的契约补全、三层验收与裁决
  formal        形式化设计验证：检查清单、配置生成、输出解析、摘要复用、运行时预检
  tlc           检查器准备：钉死版本下载、自包含 jar 合并、Java 探测与 JRE 下载、自检、失败诊断
  plan          跨会话计划：任务、依赖、证据门槛、停止条件、防篡改、下一会话提示词
  report        交付包与进度快照（handoff.html / progress.html）
  evals         技能评测：用例校验、运行评分（契约类与仓库类检查）、基准汇总
  matrix        跨模型评测矩阵：夹具建仓、调用本机 codex / claude 命令行、评分与汇总
  cli           命令行入口
"""

__version__ = "1.6.2"
