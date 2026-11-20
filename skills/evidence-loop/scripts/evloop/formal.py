"""形式化设计验证：把"这个设计在所有事件交错下是否仍守约定"变成可机械判定、可复跑的问题。

它不是一个新场景，而是叠加在修复 / 开发 / 优化场景上的一道门槛：

- 输入（都在仓库里）：冻结的检查清单 checks.json（筛选结论、案例、性质、覆盖矩阵、未建模范围、
  注入的故障）、design.md（从真实代码与测试复述的需求、状态、动作及其原子性、假设）、模型 .tla。
  每个案例的检查器配置由 checks.json 确定性生成，不由人手写。
- 检查器：显式状态模型检查器（TLC）。jar 按 sha256 钉死，不符即阻断，从不静默回退；
  只解析 -tool 格式的输出，成功标志只在错误级别为 0 时计入，且必须统计到大于 0 的不同状态。
- 结论只有两种：verified，或一条具体的反例路径。对外措辞固定为 CONCLUSION，不升级为"系统正确"。
- 约定案例（contract）必须 verified；探针案例（probe）故意写更强的候选约定，出反例就是待人裁决的发现。
- 输入摘要覆盖 checks.json、design.md、模型、生成的配置、检查器哈希与命令；摘要相同的结果直接复用，
  摘要变了就重跑——改了设计不可能沿用上一次的结论。
- 模型在 --editable 之内是"设计迭代"模式（反例驱动修订）；之外则随 checks.json 一起冻结，
  是"按已验证设计实现"模式，实现者不能改模型去迁就代码。
"""
import json
import os
import re
import shlex
import shutil

from . import render, tlc
from .runner import run_command
from .util import INVALID, REJECTED, atomic_write_text, fail, in_scope, norm, sha256_file, sha256_json

FLAGS = ("formal_spec", "model_cmd", "checker_path", "checker_sha256")
TRIGGERS = {
    "shared_state": "多个独立执行者修改共享状态，且先后顺序影响结果",
    "retry_timeout": "重试、超时、重复或迟到的消息影响产出",
    "crash_recovery": "崩溃恢复影响所有权、去重或持久化顺序",
    "ownership": "跨异步变更的授权、租约或资源所有权",
}
CONCLUSION = "在指定的模型、参数和假设下，检查器完成了检查且未发现被检查性质的违例"
TRIAGE = ("设计缺陷", "建模缺陷", "需求歧义")
PLACEHOLDERS = ("checker", "model", "cfg", "metadir")
REQUIRED_TOKENS = ("-tool", "-noGenerateSpecTE")
FORBIDDEN_TOKENS = {"-continue": "发现违例后继续跑会把反例淹没在输出里",
                    "-simulate": "随机模拟不是穷举",
                    "-dfid": "迭代加深只探索到给定深度"}
VIOLATION_CODES = {2107, 2108, 2110, 2112, 2114, 2116}
QUIET_CODES = {2121, 2264}  # "到此为止的行为"、反例标记：属于反例本身，不算检查器错误
SUCCESS_CODE = 2193
STATE_CODE = 2217
VIOLATION_EXITS = {10, 11, 12, 13}
KEEP = ("accepted", "green", "checkpoint", "failing")
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
MSG_RE = re.compile(r"@!@!@STARTMSG (\d+):(\d+) @!@!@\r?\n(.*?)@!@!@ENDMSG \1 @!@!@", re.S)
STATES_RE = re.compile(r"([\d,]+) distinct states? found")
TRACE_CAP = 120


# ---------------------------------------------------------------- 约定

def enabled(c):
    return bool(c.get("formal"))


def check_model_cmd(cmd):
    for name in PLACEHOLDERS:
        if "{" + name + "}" not in cmd:
            fail(f"--model-cmd 必须包含占位符 {{{name}}}")
    try:
        cmd.format(**{n: "x" for n in PLACEHOLDERS})
        tokens = shlex.split(cmd)
    except (KeyError, IndexError, ValueError) as e:
        fail(f"--model-cmd 只能使用 {{checker}} {{model}} {{cfg}} {{metadir}} 四个占位符"
             f"（字面花括号写成 {{{{ }}}}）：{e}")
    for flag, why in FORBIDDEN_TOKENS.items():
        if flag in tokens:
            fail(f"--model-cmd 不能带 {flag}：{why}")
    for flag in REQUIRED_TOKENS:
        if flag not in tokens:
            fail(f"--model-cmd 必须带 {flag}（-tool 让输出可机械解析，-noGenerateSpecTE 不往工作区写轨迹文件）")


def validate_args(a):
    given = [n for n in FLAGS if getattr(a, n, None) is not None]
    if not given:
        return
    if a.scenario in ("research", "document"):
        fail("形式化验证叠加在修复、开发与优化场景上；研究与文档场景没有可建模的状态机")
    if len(given) != len(FLAGS):
        fail("形式化验证需要同时给出 --formal-spec、--model-cmd、--checker-path、--checker-sha256")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", a.checker_sha256):
        fail("--checker-sha256 必须是 64 位十六进制的 sha256")
    check_model_cmd(a.model_cmd)


def _strs(value, what, names=False, allow_empty=True):
    if value is None:
        value = []
    if not isinstance(value, list) or not all(isinstance(x, str) and x.strip() for x in value):
        raise ValueError(f"{what} 必须是非空字符串列表")
    if not allow_empty and not value:
        raise ValueError(f"{what} 不能为空")
    if names:
        bad = [x for x in value if not NAME_RE.fullmatch(x)]
        if bad:
            raise ValueError(f"{what} 里有不合法的标识符：{bad}")
    return list(value)


def _constant(name, value):
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str) and value.strip() and "\n" not in value:
        return value.strip()
    raise ValueError(f"常量 {name} 的取值必须是单行文本、数字或布尔值")


def check_spec(spec):
    """校验并规范化 checks.json；不合法抛 ValueError。"""
    if not isinstance(spec, dict):
        raise ValueError("必须是 JSON 对象")
    out = {}
    design = spec.get("design")
    if not isinstance(design, str) or not design.strip():
        raise ValueError("design 必须给出设计文档路径")
    out["design"] = norm(design)
    scr = spec.get("screening")
    if not isinstance(scr, dict):
        raise ValueError("screening 必须记录筛选结论：{triggers, rationale}")
    triggers = _strs(scr.get("triggers"), "screening.triggers", allow_empty=False)
    unknown = [t for t in triggers if t not in TRIGGERS]
    if unknown:
        raise ValueError(f"screening.triggers 只能取 {sorted(TRIGGERS)}，不认识：{unknown}")
    if not isinstance(scr.get("rationale"), str) or not scr["rationale"].strip():
        raise ValueError("screening.rationale 必须写明为什么这次变更需要建模")
    out["screening"] = {"triggers": triggers, "rationale": scr["rationale"].strip()}
    out["unmodeled"] = _strs(spec.get("unmodeled"), "unmodeled（未建模的范围）", allow_empty=False)
    out["assumptions"] = _strs(spec.get("assumptions"), "assumptions")
    out["faults"] = _strs(spec.get("faults"), "faults（注入故障的动作名）", names=True)
    cases, seen = [], set()
    raw_cases = spec.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("cases 必须是非空列表")
    for i, c in enumerate(raw_cases):
        where = f"cases[{i}]"
        if not isinstance(c, dict):
            raise ValueError(f"{where} 必须是对象")
        cid = c.get("id")
        if not isinstance(cid, str) or not ID_RE.fullmatch(cid):
            raise ValueError(f"{where}.id 只能由字母、数字、'.'、'_'、'-' 组成")
        if cid in seen:
            raise ValueError(f"案例 id 重复：{cid}")
        seen.add(cid)
        kind = c.get("kind")
        if kind not in ("contract", "probe"):
            raise ValueError(f"{where}.kind 必须是 contract（约定）或 probe（探针）")
        model = c.get("model")
        if not isinstance(model, str) or not model.endswith(".tla"):
            raise ValueError(f"{where}.model 必须是 .tla 文件路径")
        case = {"id": cid, "kind": kind, "model": norm(model)}
        if c.get("spec") is not None:
            if c.get("init") is not None or c.get("next") is not None:
                raise ValueError(f"{where} 的 spec 与 init/next 只能二选一")
            case["spec"] = _strs([c["spec"]], f"{where}.spec", names=True)[0]
        else:
            for key in ("init", "next"):
                case[key] = _strs([c.get(key) or ""] if c.get(key) else None, f"{where}.{key}", names=True,
                                  allow_empty=False)[0]
        consts = c.get("constants") or {}
        if not isinstance(consts, dict) or not all(NAME_RE.fullmatch(k) for k in consts):
            raise ValueError(f"{where}.constants 必须是 {{标识符: 取值}}")
        case["constants"] = {k: _constant(k, v) for k, v in sorted(consts.items())}
        case["invariants"] = _strs(c.get("invariants"), f"{where}.invariants", names=True)
        case["properties"] = _strs(c.get("properties"), f"{where}.properties", names=True)
        if not case["invariants"] and not case["properties"]:
            raise ValueError(f"{where} 至少要检查一条不变式或性质")
        if not isinstance(c.get("check_deadlock", False), bool):
            raise ValueError(f"{where}.check_deadlock 必须是布尔值")
        case["check_deadlock"] = c.get("check_deadlock", False)
        if c.get("question") is not None:
            if not isinstance(c["question"], str):
                raise ValueError(f"{where}.question 必须是文本")
            case["question"] = c["question"]
        cases.append(case)
    if not any(c["kind"] == "contract" for c in cases):
        raise ValueError("至少要有一个约定案例（kind: contract）；只有探针无法证明现有约定")
    out["cases"] = cases
    checked = {p for c in cases if c["kind"] == "contract" for p in c["invariants"] + c["properties"]}
    coverage, ids = [], set()
    raw_cov = spec.get("coverage")
    if not isinstance(raw_cov, list) or not raw_cov:
        raise ValueError("coverage 必须是非空列表：每条需求映射到要检查的性质")
    for i, row in enumerate(raw_cov):
        where = f"coverage[{i}]"
        if not isinstance(row, dict):
            raise ValueError(f"{where} 必须是对象")
        rid = row.get("id")
        if not isinstance(rid, str) or not ID_RE.fullmatch(rid) or rid in ids:
            raise ValueError(f"{where}.id 必须是唯一的需求编号（如 R1）")
        ids.add(rid)
        text = row.get("requirement")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"{where}.requirement 必须写出需求本身")
        props = _strs(row.get("properties"), f"{where}.properties", names=True, allow_empty=False)
        missing = [p for p in props if p not in checked]
        if missing:
            raise ValueError(f"需求 {rid} 声称由 {missing} 覆盖，但没有任何约定案例检查它们")
        coverage.append({"id": rid, "requirement": text.strip(), "properties": props,
                         "code": _strs(row.get("code"), f"{where}.code"),
                         "tests": _strs(row.get("tests"), f"{where}.tests")})
    mapped = {p for row in coverage for p in row["properties"]}
    orphan = sorted(checked - mapped)
    if orphan:
        raise ValueError(f"约定案例检查的性质 {orphan} 没有映射到任何需求；在 coverage 里补上它对应的需求")
    out["coverage"] = coverage
    return out


def cfg_text(case):
    """由案例确定性生成检查器配置；同一案例永远得到同一份文本。"""
    lines = []
    if case.get("spec"):
        lines.append(f"SPECIFICATION {case['spec']}")
    else:
        lines += [f"INIT {case['init']}", f"NEXT {case['next']}"]
    lines += [f"CONSTANT {k} = {v}" for k, v in sorted(case["constants"].items())]
    lines += [f"INVARIANT {x}" for x in case["invariants"]]
    lines += [f"PROPERTY {x}" for x in case["properties"]]
    lines.append("CHECK_DEADLOCK " + ("TRUE" if case["check_deadlock"] else "FALSE"))
    return "\n".join(lines) + "\n"


def inputs(spec_rel, spec):
    return sorted({spec_rel, spec["design"]} | {c["model"] for c in spec["cases"]})


def _repo_file(repo, rel, flag):
    rel = norm(rel)
    if os.path.isabs(rel) or rel.startswith("../") or rel == "..":
        fail(f"{flag} 必须是仓库内的相对路径：{rel}")
    if not os.path.isfile(os.path.join(repo, rel)):
        fail(f"{flag} 文件不存在：{rel}")
    return rel


def checker_file(c, root):
    p = c["formal"]["checker_path"]
    return p if os.path.isabs(p) else os.path.join(root, p)


def checker_problem(c, root):
    path = checker_file(c, root)
    if not os.path.isfile(path):
        return f"检查器不存在：{path}"
    actual = sha256_file(path)
    if actual != c["formal"]["checker_sha256"]:
        return (f"检查器哈希不符：期望 {c['formal']['checker_sha256'][:12]}…，实际 {actual[:12]}…；"
                "不做静默回退，换回约定的检查器或重新澄清")
    return None


_INFO = {}


def checker_info(c, root):
    """检查器 jar 的画像（所需 Java、旁路文件、能提供的模块），按哈希缓存；不是 jar 时为 None。"""
    key = c["formal"]["checker_sha256"]
    if key not in _INFO:
        _INFO[key] = tlc.inspect(checker_file(c, root))
    return _INFO[key]


def module_problems(c, spec, root):
    """模型 EXTENDS / INSTANCE 了检查器里没有的模块（典型：只钉了 tla2tools.jar 却用社区模块）。"""
    info = checker_info(c, root)
    if not info or "TLA-Library" in c["formal"]["model_cmd"]:
        return []
    models = sorted({os.path.join(root, x["model"]) for x in spec["cases"]})
    out = []
    for path, names in tlc.missing_modules(models, info).items():
        lack = [n for n in info["companions"] if not info["companions"][n]["present"]]
        why = (f"检查器清单引用的 {'、'.join(lack)} 不在它旁边" if lack else "检查器里没有这些模块")
        out.append(f"{os.path.relpath(path, root)} 用到的模块 {names} 检查器提供不了：{why}；"
                   f"用 evloop_tlc.py fetch 生成自带社区模块的 {tlc.BUNDLE} 并重新钉死")
    return out


def runtime(c, root):
    """约定命令里的 Java 能否运行这个检查器。返回 (问题或 None, 画像)。命令不以 java 开头时不检查。"""
    info = checker_info(c, root) or {}
    need = info.get("required_java")
    java = tlc.java_of(c["formal"]["model_cmd"])
    view = {"required_java": need, "bundle": info.get("bundle"), "java": java}
    if not java:
        return None, view
    major, line = tlc.java_version(java)
    view.update(java_major=major, java_detail=line)
    if major is None:
        return (f"约定命令里的 {java} 无法运行（{line or '没有输出'}）；装 Java {need or 11}+，"
                "或用 evloop_tlc.py fetch --jre 下载 JRE 后改用它打印的约定命令"), view
    if need and major < need:
        return f"约定命令里的 java 是 Java {major}，这个检查器至少需要 Java {need}", view
    return None, view


def setup(contract, a, repo):
    """补全契约里的 formal 字段并冻结判定依据；返回需要复制进运行目录的文件。"""
    spec_rel = _repo_file(repo, a.formal_spec, "--formal-spec")
    try:
        with open(os.path.join(repo, spec_rel), encoding="utf-8") as f:
            spec = check_spec(json.load(f))
    except ValueError as e:
        fail(f"形式化检查清单不合法：{e}")
    if in_scope(spec_rel, contract["editable"]):
        fail("--formal-spec 不能位于 --editable 之内：删性质、缩范围、改参数都要先重新澄清")
    editable_models = [m for m in {c["model"] for c in spec["cases"]} if in_scope(m, contract["editable"])]
    mode = "design" if editable_models else "implement"
    frozen = [spec_rel] + [p for p in inputs(spec_rel, spec)
                           if p != spec_rel and not in_scope(p, contract["editable"])]
    for rel in frozen:
        _repo_file(repo, rel, "形式化输入")
        contract["frozen"][rel] = sha256_file(os.path.join(repo, rel))
        if rel not in contract["frozen_paths"]:
            contract["frozen_paths"].append(rel)
    checker = a.checker_path
    contract["formal"] = {"spec": spec_rel, "design": spec["design"], "mode": mode,
                          "model_cmd": a.model_cmd, "checker_path": checker,
                          "checker_sha256": a.checker_sha256.lower(),
                          "cases": [{"id": c["id"], "kind": c["kind"]} for c in spec["cases"]]}
    problem = checker_problem(contract, repo)
    if problem:
        fail(problem)
    problem, view = runtime(contract, repo)
    if problem:
        fail(problem)
    missing = module_problems(contract, spec, repo)
    if missing:
        fail(missing[0])
    contract["formal"]["runtime"] = {k: v for k, v in view.items() if v is not None}
    return {"formal-spec.json": os.path.join(repo, spec_rel)}


def load_spec(home):
    with open(home.file("formal-spec.json"), encoding="utf-8") as f:
        return check_spec(json.load(f))


# ---------------------------------------------------------------- 静态检查与摘要

def _read(path):
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _defined(text, name):
    return re.search(rf"^[ \t]*{re.escape(name)}[ \t]*(\([^)]*\))?[ \t]*==", text, re.M) is not None


def static_problems(spec, root):
    """不运行检查器就能发现的输入缺口：模块名、性质定义、故障动作、设计文档覆盖。"""
    problems, texts = [], {}
    for case in spec["cases"]:
        rel = case["model"]
        if rel not in texts:
            texts[rel] = _read(os.path.join(root, rel))
            if texts[rel] is None:
                problems.append(f"模型文件不存在：{rel}")
                continue
            module = os.path.splitext(os.path.basename(rel))[0]
            if not re.search(rf"^-{{4,}}\s*MODULE\s+{re.escape(module)}\s*-{{4,}}", texts[rel], re.M):
                problems.append(f"{rel} 的模块名必须是 {module}")
        text = texts[rel]
        if text is None:
            continue
        names = [case.get("spec"), case.get("init"), case.get("next")] + case["invariants"] + case["properties"]
        missing = [n for n in names if n and not _defined(text, n)]
        if missing:
            problems.append(f"案例 {case['id']} 引用的定义在 {rel} 里不存在：{missing}")
    models = "\n".join(t for t in texts.values() if t)
    for fault in spec["faults"]:
        if not _defined(models, fault):
            problems.append(f"注入的故障 {fault} 在模型里没有定义（把真实故障假设掉不能换来绿色结果）")
        elif len(re.findall(rf"\b{re.escape(fault)}\b", models)) < 2:
            problems.append(f"注入的故障 {fault} 定义了却没有出现在任何动作组合里")
    design = _read(os.path.join(root, spec["design"]))
    if design is None:
        problems.append(f"设计文档不存在：{spec['design']}")
    else:
        absent = [x for x in [r["id"] for r in spec["coverage"]] + spec["faults"] if x not in design]
        if absent:
            problems.append(f"设计文档没有提到这些需求或故障：{absent}")
    return problems


def digest(c, spec, root):
    files = {}
    for rel in inputs(c["formal"]["spec"], spec):
        path = os.path.join(root, rel)
        files[rel] = sha256_file(path) if os.path.isfile(path) else None
    return sha256_json({"files": files, "cfg": {k["id"]: cfg_text(k) for k in spec["cases"]},
                        "checker": c["formal"]["checker_sha256"], "cmd": c["formal"]["model_cmd"]})


# ---------------------------------------------------------------- 运行与解析

def parse(output, code, timed_out=False):
    """把检查器的 -tool 输出解析成 verified / counterexample / error。"""
    out = {"result": "error", "states": None}
    if timed_out:
        out["reason"] = "检查器超时"
        return out
    text = output or ""
    msgs = [(int(a), int(b), body) for a, b, body in MSG_RE.findall(text)]
    found = STATES_RE.findall(text)
    out["states"] = int(found[-1].replace(",", "")) if found else None
    violations = [body.strip() for m, s, body in msgs if m in VIOLATION_CODES and s != 0]
    errors = [body.strip() for m, s, body in msgs
              if s in (1, 2) and m not in VIOLATION_CODES and m not in QUIET_CODES]
    if violations or (code in VIOLATION_EXITS and not errors):
        trace = "\n\n".join(body.strip() for m, _, body in msgs if m == STATE_CODE).splitlines()
        out.update(result="counterexample", violation=(violations or [f"检查器退出码 {code}"])[0].splitlines()[0])
        out["trace"] = trace[:TRACE_CAP]
        if len(trace) > TRACE_CAP:
            out["trace_truncated"] = len(trace)
        return out
    if errors:
        out["reason"] = errors[0].splitlines()[0] if errors[0] else "检查器报错"
    elif code != 0:
        out["reason"] = f"检查器退出码 {code}"
    elif not any(m == SUCCESS_CODE and s == 0 for m, s, _ in msgs):
        out["reason"] = "输出里没有错误级别为 0 的完成消息；确认命令带了 -tool"
    elif not out["states"]:
        out["reason"] = "没有统计到任何不同状态；模型根本没有被探索"
    else:
        out["result"] = "verified"
    return out


def _quote(s):
    return shlex.quote(s) if os.name != "nt" else '"' + s + '"'


def _run_case(c, home, root, case, label, runner):
    os.makedirs(home.file("formal"), exist_ok=True)
    cfg = home.file(os.path.join("formal", case["id"] + ".cfg"))
    atomic_write_text(cfg, cfg_text(case))
    meta = home.file(os.path.join("formal", "meta", f"{label}-{case['id']}"))
    shutil.rmtree(meta, ignore_errors=True)
    cmd = c["formal"]["model_cmd"].format(
        checker=_quote(checker_file(c, root)), model=_quote(os.path.join(root, case["model"])),
        cfg=_quote(cfg), metadir=_quote(meta))
    env = tlc.locale_env([checker_file(c, root), os.path.join(root, case["model"]), cfg, meta])
    r, raw = runner(cmd, f"{label}.formal-{case['id']}.log", env)
    shutil.rmtree(meta, ignore_errors=True)
    res = parse(r.output, r.code, r.timed_out)
    hint = tlc.diagnose(r.output) if res["result"] == "error" else None
    if hint:
        res["reason"] = f"{res.get('reason') or '检查器出错'}；{hint}"
    res.update(kind=case["kind"], raw=raw, exit=r.code)
    return res


def _compact(res):
    keep = ("kind", "result", "states", "raw", "exit", "violation", "reason")
    return {k: res[k] for k in keep if res.get(k) is not None}


def evaluate(c, home, root, label, runner, rows=None, baseline=None):
    """在 root 上跑全部案例；给出 rows 时，摘要相同且无错误的旧结果直接复用。

    返回 (summary, output_text)。summary：digest / ok / cases / contract_open / findings / error。
    """
    spec = load_spec(home)
    problem = checker_problem(c, root)
    if problem:
        return {"ok": False, "error": problem}, problem
    static = static_problems(spec, root) + module_problems(c, spec, root)
    if static:
        msg = "形式化输入不完整：" + static[0]
        return {"ok": False, "error": msg, "problems": static[:12]}, "\n".join(static)
    d = digest(c, spec, root)
    if rows is not None:
        prev = reusable(rows, baseline, d)
        if prev:
            summary, source = prev
            return dict(summary, reused_from=source), _text(summary)
    cases, lines = {}, []
    for case in spec["cases"]:
        res = _run_case(c, home, root, case, label, runner)
        cases[case["id"]] = _compact(res)
        if res["result"] == "counterexample":
            lines += [f"[{case['id']}] {res['violation']}"] + res["trace"][-12:]
        elif res["result"] == "error":
            lines.append(f"[{case['id']}] error: {res['reason']}")
    summary = {"digest": d, "cases": cases}
    errs = [k for k, v in cases.items() if v["result"] == "error"]
    if errs:
        summary["error"] = f"案例 {errs[0]} 的检查器出错：{cases[errs[0]]['reason']}（见 {cases[errs[0]]['raw']}）"
    summary["contract_open"] = [k for k, v in cases.items() if v["kind"] == "contract" and v["result"] != "verified"]
    summary["findings"] = [k for k, v in cases.items() if v["kind"] == "probe" and v["result"] == "counterexample"]
    summary["ok"] = not errs and not summary["contract_open"]
    return summary, "\n".join(lines)


def _text(summary):
    return "\n".join(f"[{k}] {v.get('violation') or v.get('reason') or v['result']}"
                     for k, v in summary.get("cases", {}).items() if v["result"] != "verified")


def reusable(rows, baseline, d):
    if baseline and baseline.get("digest") == d and not baseline.get("error") and "cases" in baseline:
        return {k: v for k, v in baseline.items() if k != "reused_from"}, "baseline"
    for r in reversed(rows):
        f = r.get("formal")
        if r.get("kind") == "attempt" and f and f.get("digest") == d and not f.get("error") and "cases" in f:
            return {k: v for k, v in f.items() if k != "reused_from"}, r["n"]
    return None


def passed_before(c, rows):
    if (c.get("baseline") or {}).get("formal", {}).get("ok"):
        return True
    return any(r.get("kind") == "attempt" and r.get("verdict") in KEEP and (r.get("formal") or {}).get("ok")
               for r in rows)


# ---------------------------------------------------------------- 裁判接入

def baseline(contract, home, repo, copies):
    for name, path in copies.items():
        shutil.copyfile(path, home.file(name))

    def runner(cmd, raw_name, env=None):
        return run_command(cmd, repo, home.raw_path(raw_name), env=env), f"raw/{raw_name}"

    summary, _ = evaluate(contract, home, repo, "baseline", runner)
    if summary.get("error"):
        fail("形式化检查在基线上出错：" + summary["error"])
    if summary["contract_open"] and contract["formal"]["mode"] == "implement":
        fail(f"模型已冻结（不在 --editable 内），但约定案例 {summary['contract_open']} 在基线上有反例；"
             "按已验证设计实现之前，先在设计迭代模式里解决反例（把模型放进 --editable），或重新澄清 checks.json")
    return summary


def gate(c, home, wt, rows, label, runner, ctx):
    """attempt 的形式化门槛。返回 (summary, None) 表示放行，否则 (summary, (verdict, 退出码, extra))。"""
    summary, text = evaluate(c, home, wt, label, runner, rows, (c.get("baseline") or {}).get("formal"))
    if text:
        ctx["output"] = text
    if summary.get("error"):
        return summary, ("invalid", INVALID, {"reason": summary["error"], "stage": "formal"})
    if summary["contract_open"]:
        first = summary["contract_open"][0]
        why = summary["cases"][first].get("violation", "")
        reason = f"形式化约定案例 {first} 出现反例：{why}"
        if passed_before(c, rows):
            return summary, ("rejected", REJECTED, {"reason": "回退了已 verified 的形式化约定：" + reason,
                                                    "stage": "formal"})
        return summary, ("failing", REJECTED, {"reason": reason, "stage": "formal"})
    return summary, None


def verify(c, home, wt):
    def runner(cmd, raw_name, env=None):
        return run_command(cmd, wt, home.raw_path(raw_name), env=env), f"raw/{raw_name}"

    summary, _ = evaluate(c, home, wt, "verify", runner)
    return bool(summary.get("ok")), summary


def current(c, rows):
    """保留的最优提交对应的形式化结果：最近一次留下来的尝试，否则基线。"""
    for r in reversed(rows):
        if (r.get("kind") == "attempt" and r.get("commit") == c.get("best") and r.get("verdict") in KEEP
                and r.get("formal")):
            return r["formal"]
    return (c.get("baseline") or {}).get("formal")


def status(c, rows, out):
    f = current(c, rows) or {}
    view = {"mode": c["formal"]["mode"], "digest": f.get("digest"),
            "cases": {k: v["result"] for k, v in f.get("cases", {}).items()},
            "contract_open": f.get("contract_open", []), "findings": f.get("findings", [])}
    if f.get("error"):
        view["error"] = f["error"]
    out["formal"] = view
    out["formal_open"] = list(view["contract_open"]) + (["error"] if f.get("error") else [])
    out["goal_met"] = bool(out.get("goal_met")) and not out["formal_open"]


def next_hint(s):
    f = s.get("formal") or {}
    if f.get("error"):
        return "形式化检查出错，先修好输入或检查器：" + f["error"]
    if s.get("formal_open"):
        return ("让形式化约定案例全部 verified：" + " ".join(s["formal_open"]) + "。先把反例分类为"
                + "、".join(TRIAGE) + "，再改设计或模型；不得删性质、把真实故障假设掉或缩小范围")
    return None


def doctor(c, root, check, home=None):
    problem = checker_problem(c, root)
    check("formal_checker", not problem, problem or f"sha256 {c['formal']['checker_sha256'][:12]}… 与契约一致")
    if problem:
        return
    problem, view = runtime(c, root)
    if not problem and home is not None:
        missing = module_problems(c, load_spec(home), root)
        problem = missing[0] if missing else None
    if problem:
        check("formal_runtime", False, problem)
        return
    then = (c["formal"].get("runtime") or {}).get("java_detail")
    detail = view.get("java_detail") or "约定命令不以 java 开头，未检查 Java 版本"
    if view.get("required_java"):
        detail += f"（检查器需要 Java {view['required_java']}+）"
    if then and view.get("java_detail") and then != view["java_detail"]:
        detail += f"；与 init 时的 {then} 不同"
    check("formal_runtime", True, detail)


def resume_contract(c):
    f = c["formal"]
    return {"spec": f["spec"], "mode": f["mode"], "cases": [x["id"] for x in f["cases"]]}


# ---------------------------------------------------------------- 交付包

def _trace(home, raw):
    text = _read(home.file(raw)) if raw else None
    if not text:
        return []
    return parse(text, None).get("trace", [])


def _sub(title, inner):
    return f"<h3>{render.esc(title)}</h3>{inner}"


def _runtime_text(c):
    rt = c["formal"].get("runtime") or {}
    jar = (f"检查器 jar（{rt['bundle']}，自带社区模块）由 sha256 钉死；" if rt.get("bundle")
           else "检查器 jar 由 sha256 钉死，但它在清单之外依赖的文件不在哈希之内；")
    java = (f"Java 运行时（init 时为 {rt['java_detail']}）不在哈希之内，只检查了版本下限；" if rt.get("java_detail")
            else "Java 运行时不在哈希之内；")
    return render.esc(jar + java)


def report_section(home, c, rows, verification=None):
    esc = render.esc
    spec = load_spec(home)
    fresh = verification and verification.get("commit") == c.get("best") and verification.get("formal")
    f = verification["formal"] if fresh else (current(c, rows) or {})
    source = "最终验证的重跑" if fresh else "保留提交的最近一次裁决（未经 verify 重跑）"
    cases = f.get("cases", {})
    contracts = [x for x in spec["cases"] if x["kind"] == "contract"]
    done = sum(1 for x in contracts if cases.get(x["id"], {}).get("result") == "verified")
    mode = "设计迭代（模型可改）" if c["formal"]["mode"] == "design" else "按已验证设计实现（模型冻结）"
    body = render.stats([("模式", esc(mode)), ("约定案例 verified", f"{done}/{len(contracts)}"),
                         ("探针发现", len(f.get("findings", []))),
                         ("输入摘要", esc((f.get("digest") or "-")[:12])),
                         ("检查器 sha256", esc(c["formal"]["checker_sha256"][:12]))])
    if f.get("error"):
        body += f'<p class="bad">检查器出错：{esc(f["error"])}</p>'
    elif f and not f.get("contract_open"):
        body += (f'<p class="ok">{esc(CONCLUSION)}。</p><p>这句话不等于"系统正确"或"实现没有缺陷"：'
                 '被验证的是下面列出的抽象与参数范围，范围之外的任何延伸都需要新的证据。</p>')
    else:
        body += '<p class="bad">约定案例尚未全部 verified，形式化证据不成立。</p>'
    body += f'<p>结果来源：{esc(source)}' + (f'（复用了 {esc(f["reused_from"])} 的同摘要结果）'
                                            if f.get("reused_from") is not None else "") + "。</p>"
    rows_html = []
    for x in spec["cases"]:
        v = cases.get(x["id"], {})
        res = v.get("result", "未运行")
        cls = "ok" if res == "verified" else "warn" if x["kind"] == "probe" else "bad"
        word = {"verified": "verified", "counterexample": "反例", "error": "出错"}.get(res, res)
        props = "、".join(x["invariants"] + x["properties"])
        link = f'<a href="{esc(v["raw"])}">原始日志</a>' if v.get("raw") else "-"
        rows_html.append([esc(x["id"]), "约定" if x["kind"] == "contract" else "探针",
                          f'<span class="{cls}">{esc(word)}</span>', esc(v.get("states", "-")), esc(props), link])
    body += _sub("检查案例", render.table(["案例", "类型", "结果", "不同状态数", "性质", "证据"], rows_html))
    traces = ""
    for x in spec["cases"]:
        v = cases.get(x["id"], {})
        if v.get("result") != "counterexample":
            continue
        label = "探针发现（待人裁决）" if x["kind"] == "probe" else "约定被违反"
        q = f'<p>{esc(x["question"])}</p>' if x.get("question") else ""
        trace = "\n".join(_trace(home, v.get("raw"))) or "（原始日志里没有状态序列）"
        traces += (f'<p><b>{esc(x["id"])} · {label}</b></p>{q}<p>{esc(v.get("violation", ""))}</p>'
                   f'<pre>{esc(trace)}</pre>')
    if traces:
        traces += ("<p>每条反例都要分类为" + "、".join(TRIAGE) + "，再修订对应的输入重新检查；"
                   "删性质、把真实故障假设掉、缩小范围换来的绿色结果不算数。</p>")
        body += _sub("反例路径", traces)
    cov = [[esc(r["id"]), esc(r["requirement"]), esc("、".join(r["properties"])),
            esc("、".join(r["code"]) or "-"), esc("、".join(r["tests"]) or "-")] for r in spec["coverage"]]
    body += _sub("需求 → 性质 → 代码（实现交接）", render.table(
        ["需求", "内容", "性质", "对应代码", "回归测试"], cov)
        + "<p>实现者按已确定的语义实现；语义或原子性保不住时报阻塞，不得改模型去迁就代码。</p>")
    trig = "".join(f"<li>{esc(TRIGGERS[t])}</li>" for t in spec["screening"]["triggers"])
    body += _sub("筛选结论", f"<ul>{trig}</ul><p>{esc(spec['screening']['rationale'])}</p>"
                           "<p>设计修订引入新的相关行为时要重新筛选。</p>")
    limits = "".join(f"<li>{esc(u)}</li>" for u in spec["unmodeled"])
    extra = "".join(f"<li>假设：{esc(u)}</li>" for u in spec["assumptions"])
    faults = "、".join(spec["faults"]) or "无"
    body += _sub("证据边界", f"<ul>{limits}{extra}</ul>"
                           f"<p>注入的故障：{esc(faults)}。检查是有界的：只覆盖 checks.json 里的常量取值；"
                           "模型是抽象，被验证的是抽象而不是原物；" + _runtime_text(c) +
                           "裁判不拦截跳过建模的交付。</p>")
    return render.section("形式化设计验证", body)
