"""技能评测：校验 evals/evals.json，并对一次运行的产物做机械评分。

evals.json 采用通用的技能评测格式：
  {"skill_name": "evidence-loop",
   "evals": [{"id": 1, "prompt": "...", "expected_output": "...", "files": [],
              "assertions": ["自然语言断言…"],
              "checks": [{"kind": "scenario", "equals": "bugfix"}, …]}]}

assertions 交给人或评审模型判断；checks 是本模块能机械判定的子集，读运行目录
（<repo>/.evloop/runs/<task>）里的 contract.json 与 attempts.jsonl，以及仓库的 git 状态，
不运行任何约定命令。grade 的输出与常见的 grading.json 结构一致：assertion_results + summary。

两类检查：
- 契约类（REPO_KINDS 以外）：没有契约时一律不通过——它们衡量的是"有没有按流程走"；
- 仓库类（REPO_KINDS）：不需要契约，带技能与不带技能的运行可以公平比较。
可选字段 fixture / setup 供 evloop_matrix.py 自动搭建仓库，见 references/evals.md。
"""
import json
import re
import os

from .contract import Home
from .util import RUNS_DIR, STATE_DIR, fail, in_scope

CHECK_KINDS = {
    "contract": "契约已封存且可加载",
    "scenario": "场景等于 equals",
    "attempts_min": "裁决过的尝试不少于 value 次",
    "verdict": "至少有一次尝试的裁决为 equals",
    "no_verdict": "没有任何尝试的裁决为 equals",
    "verified": "最近一次 verify 针对保留的最优提交且通过",
    "report": "存在与当前最优一致的交付包",
    "not_approved": "契约里没有人工批准记录（智能体不得自行批准）",
    "approved": "契约里有人工批准记录",
    "routes_min": "优化场景使用过的不同路线不少于 value 条",
    "elements_done": "开发场景所有蓝图元素都已记录完成",
    "target_met": "优化场景保留的最优分数达到目标线",
    "field": "契约字段 key 等于 equals（null 表示字段不存在或为空）",
    "not_merged": "保留的最优提交没有被合并进 branch_from（等人批准后才合并）",
    "no_run": "仓库里没有任何运行目录（小任务不该启动流程）",
    "formal": "启用了形式化设计验证且模式为 equals，最近一次 verify 里约定案例全部通过检查器",
    "paths_unchanged": "paths 中的路径在所有分支与工作区里都与初始提交一致",
}
REPO_KINDS = ("no_run", "paths_unchanged")
PARAMS = ("equals", "value", "key", "paths")


def describe(chk):
    """检查项的可读描述：自定义 text 优先，否则把默认描述里的参数名换成实际取值。"""
    if chk.get("text"):
        return chk["text"]
    text = CHECK_KINDS[chk["kind"]]
    for name in PARAMS:
        if name in chk:
            v = chk[name]
            shown = "、".join(map(str, v)) if isinstance(v, list) else json.dumps(v, ensure_ascii=False)
            text = re.sub(rf"(?<![A-Za-z_]){name}(?![A-Za-z_])", lambda _m: shown, text, count=1)
    return text


def validate(data, skill_name=None):
    """返回问题列表；空列表表示格式合法。"""
    problems = []
    if not isinstance(data, dict):
        return ["evals.json 必须是对象"]
    if skill_name and data.get("skill_name") != skill_name:
        problems.append(f"skill_name 应为 {skill_name}")
    evals = data.get("evals")
    if not isinstance(evals, list) or not evals:
        return problems + ["evals 必须是非空列表"]
    seen = set()
    for i, e in enumerate(evals):
        where = f"evals[{i}]"
        if not isinstance(e, dict):
            problems.append(f"{where} 必须是对象")
            continue
        if e.get("id") in seen:
            problems.append(f"{where} 的 id 重复")
        seen.add(e.get("id"))
        for key in ("prompt", "expected_output"):
            if not isinstance(e.get(key), str) or not e[key].strip():
                problems.append(f"{where}.{key} 必须是非空字符串")
        if not isinstance(e.get("files", []), list):
            problems.append(f"{where}.files 必须是列表")
        for key in ("fixture", "setup"):
            if key in e and (not isinstance(e[key], str) or not e[key]):
                problems.append(f"{where}.{key} 必须是非空字符串")
        assertions = e.get("assertions", [])
        if not isinstance(assertions, list) or not all(isinstance(x, str) and x for x in assertions):
            problems.append(f"{where}.assertions 必须是字符串列表")
        for j, chk in enumerate(e.get("checks", [])):
            if not isinstance(chk, dict) or chk.get("kind") not in CHECK_KINDS:
                problems.append(f"{where}.checks[{j}] 的 kind 必须是 {sorted(CHECK_KINDS)} 之一")
            elif chk["kind"] == "field" and not isinstance(chk.get("key"), str):
                problems.append(f"{where}.checks[{j}] 的 field 检查需要字符串 key")
            elif chk["kind"] == "paths_unchanged" and not (
                    isinstance(chk.get("paths"), list) and chk["paths"]
                    and all(isinstance(x, str) and x for x in chk["paths"])):
                problems.append(f"{where}.checks[{j}] 的 paths_unchanged 检查需要非空的 paths 列表")
    return problems


def load(path, skill_name=None):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"无法读取 {path}：{e}")
    problems = validate(data, skill_name)
    if problems:
        fail("evals.json 不合法：" + "；".join(problems))
    return data


def _attempts(rows):
    return [r for r in rows if r.get("kind") == "attempt"]


def repo_of(run_dir):
    """从 <repo>/.evloop/runs[/<task>] 反推仓库根目录；推不出时返回 None。"""
    path = os.path.abspath(run_dir)
    while True:
        parent = os.path.dirname(path)
        if os.path.basename(path) == STATE_DIR:
            return parent
        if parent == path:
            return None
        path = parent


def _runs(repo):
    runs = os.path.join(repo, RUNS_DIR)
    if not os.path.isdir(runs):
        return []
    return sorted(n for n in os.listdir(runs) if os.path.isfile(os.path.join(runs, n, "contract.json")))


def _paths_unchanged(repo, paths):
    """返回 (是否未变, 证据)。比较对象是根提交；检查所有本地分支与所有工作区。"""
    from . import gitops as g

    roots = g.git(repo, "rev-list", "--max-parents=0", "HEAD").split()
    if not roots:
        return False, "没有根提交"
    root = roots[-1]
    changed = []
    for ref in g.git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads").split():
        if [p for p in g.changed_between(repo, root, ref) if in_scope(p, paths)]:
            changed.append(f"分支 {ref}")
    worktrees = [ln[len("worktree "):] for ln in g.git(repo, "worktree", "list", "--porcelain").splitlines()
                 if ln.startswith("worktree ")]
    for wt in worktrees:
        if os.path.isdir(wt) and g.status_entries(wt, *paths):
            changed.append(f"工作区 {os.path.basename(wt)}")
    return not changed, ("未改动" if not changed else "已改动：" + "，".join(changed))


def _repo_check(kind, chk, repo):
    if repo is None or not os.path.exists(os.path.join(repo, ".git")):
        return False, "找不到仓库"
    if kind == "no_run":
        runs = _runs(repo)
        return not runs, ",".join(runs) or "没有运行目录"
    return _paths_unchanged(repo, chk["paths"])


def grade(run_dir, checks, repo=None):
    """对一次运行做机械评分。

    契约类检查在运行目录不存在或契约损坏时判为不通过；仓库类检查只看 repo
    （不给时从 run_dir 反推），不需要契约。
    """
    from . import gitops as g
    from . import judge  # 延迟导入，避免循环依赖
    from . import scenarios as sc

    home = Home(run_dir)
    repo = repo or repo_of(run_dir)
    results = []
    c, rows, err = None, [], None
    try:
        c = home.load()
        rows = home.attempts()
    except Exception as e:  # noqa: BLE001 —— 评分要把所有失败都记成证据
        err = str(e)
    for chk in checks:
        kind = chk["kind"]
        text = describe(chk)
        if kind in REPO_KINDS:
            try:
                passed, evidence = _repo_check(kind, chk, repo)
            except Exception as e:  # noqa: BLE001
                passed, evidence = False, str(e)
            results.append({"text": text, "passed": bool(passed), "evidence": evidence})
            continue
        if c is None:
            results.append({"text": text, "passed": False, "evidence": err or "没有契约"})
            continue
        attempts = _attempts(rows)
        verdicts = [r.get("verdict") for r in attempts]
        if kind == "contract":
            passed, evidence = True, f"{c['scenario']}，封存校验通过"
        elif kind == "scenario":
            passed, evidence = c["scenario"] == chk.get("equals"), c["scenario"]
        elif kind == "attempts_min":
            passed, evidence = len(attempts) >= chk.get("value", 1), f"{len(attempts)} 次尝试"
        elif kind == "verdict":
            passed, evidence = chk.get("equals") in verdicts, ",".join(map(str, verdicts)) or "无"
        elif kind == "no_verdict":
            passed, evidence = chk.get("equals") not in verdicts, ",".join(map(str, verdicts)) or "无"
        elif kind == "verified":
            v = judge.last_verification(rows)
            passed = bool(v and v["verdict"] == "verified" and v["commit"] == c.get("best"))
            evidence = f"verify #{v['n']} {v['verdict']}" if v else "没有 verify 记录"
        elif kind == "report":
            state = judge.review_state(c, rows)
            passed, evidence = state["report_current"], (c.get("report") or {}).get("path", "没有交付包")
        elif kind in ("approved", "not_approved"):
            has = bool(c.get("approved"))
            passed = has if kind == "approved" else not has
            evidence = json.dumps(c.get("approved"), ensure_ascii=False) if has else "无批准记录"
        elif kind == "routes_min":
            routes = {r.get("route") for r in attempts if r.get("route")}
            passed, evidence = len(routes) >= chk.get("value", 1), ",".join(sorted(routes)) or "无"
        elif kind == "target_met":
            if c["scenario"] != "optimization":
                passed, evidence = False, "不是优化场景"
            else:
                passed = sc.contract_meets_target(c, c.get("best_score"))
                evidence = f"最优 {c.get('best_score')}，目标 {c.get('target')}"
        elif kind == "field":
            value = c.get(chk["key"])
            want = chk.get("equals")
            passed = (not value) if want is None else value == want
            evidence = json.dumps(value, ensure_ascii=False)
        elif kind == "formal":
            f = c.get("formal") or {}
            v = judge.last_verification(rows) or {}
            ok = bool((v.get("formal") or {}).get("ok"))
            passed = bool(f) and f.get("mode") == chk.get("equals", f.get("mode")) and ok
            evidence = f"模式 {f.get('mode', '未启用')}，verify 形式化检查{'通过' if ok else '未通过或缺失'}"
        elif kind == "not_merged":
            target, best = c.get("branch_from"), c.get("best")
            if not best or not g.branch_exists(c["repo"], target):
                passed, evidence = True, "没有可合并的最优提交或目标分支不存在"
            else:
                merged = g.is_ancestor(c["repo"], best, target)
                passed = not merged or best == c.get("baseline", {}).get("source")
                evidence = f"{best[:10]} {'已' if merged else '未'}进入 {target}"
        else:  # elements_done
            if c["scenario"] != "development":
                passed, evidence = False, "不是开发场景"
            else:
                done = sc.element_progress(c["elements"], c.get("depends", {}), rows)["done"]
                passed, evidence = len(done) == len(c["elements"]), f"{len(done)}/{len(c['elements'])}"
        results.append({"text": text, "passed": bool(passed), "evidence": evidence})
    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    out = {"assertion_results": results,
           "summary": {"passed": passed, "failed": total - passed, "total": total,
                       "pass_rate": round(passed / total, 4) if total else None}}
    repo_results = [r for chk, r in zip(checks, results) if chk["kind"] in REPO_KINDS]
    if repo_results:
        ok = sum(1 for r in repo_results if r["passed"])
        # 不依赖契约的那部分：带技能与不带技能可以直接比较
        out["repo_checks"] = {"passed": ok, "total": len(repo_results),
                              "pass_rate": round(ok / len(repo_results), 4)}
    return out


def _delta(a, b, keys=("pass_rate", "tokens", "time_seconds")):
    out = {}
    for key in keys:
        x, y = a[key], b[key]
        out[key] = round(x["mean"] - y["mean"], 4) if x and y else None
    return out


def benchmark(iteration_dir):
    """汇总 iteration-N/<eval>/<配置>/grading.json 为 benchmark.json 的内容。

    配置名为 with_skill / without_skill 时给出总的 delta；配置名为 <模型>__with_skill /
    <模型>__without_skill（evloop_matrix.py 的输出）时，另在 per_model 下按模型给出 delta。
    """
    configs = {}
    if not os.path.isdir(iteration_dir):
        fail(f"目录不存在：{iteration_dir}")
    for case in sorted(os.listdir(iteration_dir)):
        case_dir = os.path.join(iteration_dir, case)
        if not os.path.isdir(case_dir):
            continue
        for config in sorted(os.listdir(case_dir)):
            path = os.path.join(case_dir, config, "grading.json")
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8") as f:
                grading = json.load(f)
            summary = grading.get("summary", {})
            repo_rate = (grading.get("repo_checks") or {}).get("pass_rate")
            timing = {}
            tpath = os.path.join(case_dir, config, "timing.json")
            if os.path.isfile(tpath):
                with open(tpath, encoding="utf-8") as f:
                    timing = json.load(f)
            bucket = configs.setdefault(config, {"rates": [], "repo": [], "tokens": [], "seconds": []})
            if summary.get("pass_rate") is not None:
                bucket["rates"].append(summary["pass_rate"])
            if repo_rate is not None:
                bucket["repo"].append(repo_rate)
            if timing.get("total_tokens") is not None:
                bucket["tokens"].append(timing["total_tokens"])
            if timing.get("duration_ms") is not None:
                bucket["seconds"].append(timing["duration_ms"] / 1000.0)

    def stats(values):
        if not values:
            return None
        mean = sum(values) / len(values)
        var = sum((v - mean) ** 2 for v in values) / len(values)
        return {"mean": round(mean, 4), "stddev": round(var ** 0.5, 4), "n": len(values)}

    summary = {}
    for name, b in configs.items():
        summary[name] = {"pass_rate": stats(b["rates"]), "tokens": stats(b["tokens"]),
                         "time_seconds": stats(b["seconds"])}
        if b["repo"]:
            summary[name]["repo_pass_rate"] = stats(b["repo"])
    out = {"run_summary": summary}
    if "with_skill" in summary and "without_skill" in summary:
        out["run_summary"]["delta"] = _delta(summary["with_skill"], summary["without_skill"])
    per_model = {}
    for name in summary:
        model, sep, variant = name.rpartition("__")
        if sep and variant == "with_skill" and f"{model}__without_skill" in summary:
            a, b = summary[name], summary[f"{model}__without_skill"]
            delta = _delta(a, b)
            if a.get("repo_pass_rate") and b.get("repo_pass_rate"):
                delta.update(_delta(a, b, ("repo_pass_rate",)))
            per_model[model] = {"delta": delta}
    if per_model:
        out["per_model"] = per_model
    return out


# ---------------------------------------------------------------- 命令行

def _find(data, eval_id):
    for e in data["evals"]:
        if str(e.get("id")) == str(eval_id):
            return e
    fail(f"evals.json 里没有 id={eval_id} 的用例")


def _write_or_print(obj, out):
    text = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    if out:
        from .util import atomic_write_text
        atomic_write_text(out, text)
        print(out)
    else:
        print(text, end="")


def build_parser():
    import argparse

    from .util import PROG

    p = argparse.ArgumentParser(prog=f"{PROG}_eval.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", metavar="命令")
    sub.required = True
    v = sub.add_parser("validate", help="校验 evals.json 的格式")
    v.add_argument("file")
    v.add_argument("--skill-name", help="要求 skill_name 等于该值")
    g = sub.add_parser("grade", help="按某条用例的 checks 给一次运行评分")
    g.add_argument("file")
    g.add_argument("--eval-id", required=True)
    g.add_argument("--run", required=True, help="运行目录：<repo>/.evloop/runs/<task>")
    g.add_argument("--repo", help="仓库类检查使用的仓库；默认从 --run 反推")
    g.add_argument("--out", help="写入 grading.json 的路径；不给则打印")
    b = sub.add_parser("benchmark", help="把 iteration-N 目录下的 grading.json 汇总成 benchmark")
    b.add_argument("iteration_dir")
    b.add_argument("--out", help="写入 benchmark.json 的路径；不给则打印")
    return p


def main(argv=None):
    import sys

    from .util import CODE_NAMES, PROG, REJECTED, EvloopError

    a = build_parser().parse_args(argv)
    try:
        if a.cmd == "validate":
            data = load(a.file, a.skill_name)
            print(json.dumps({"ok": True, "evals": len(data["evals"]),
                              "checks": sum(len(e.get("checks", [])) for e in data["evals"])},
                             ensure_ascii=False))
            return 0
        if a.cmd == "grade":
            case = _find(load(a.file), a.eval_id)
            result = grade(a.run, case.get("checks", []), repo=a.repo)
            result["eval_id"] = case["id"]
            _write_or_print(result, a.out)
            return 0 if result["summary"]["failed"] == 0 else REJECTED
        _write_or_print(benchmark(a.iteration_dir), a.out)
        return 0
    except EvloopError as e:
        print(f"{PROG}: {CODE_NAMES.get(e.code, 'error')}: {e}", file=sys.stderr)
        return e.code
