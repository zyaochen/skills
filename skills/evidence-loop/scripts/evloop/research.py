"""研究 / 文档场景：三层验收里的 L1 硬检查与 L2 细则评审，L3 仍是人工 approve。

- L1 硬检查（text.py + 可选命令）：标题、篇幅、占位符、注入文本、论断逐字核对来源快照、
  每个问题的不同来源域名数、逐问题验收命令、doctest、--test-cmd。只能否决。
- L2 细则评审（rubric.py）：冻结的细则 + 校准过的外部评审命令，K 次采样取中位数，
  低于通过线不能接受；已接受的草稿再被评低超过评审噪声，视为质量回退。只能否决。
- 裁决：
    诚信问题（编造引用、摘录对不上快照、注入、论断文件损坏）→ invalid，回滚；
    未完成（硬检查或评审未过）→ 尚无被接受的版本时 failing（保留进度），否则 rejected（回滚）；
    全部通过 → accepted。
"""
import json
import os
import shutil
import sys

from . import rubric as rb
from . import sources as src_mod
from . import text as tx
from .runner import run_command
from .util import ACCEPTED, INVALID, REJECTED, fail, in_scope, norm, sha256_file

SCENARIOS = ("research", "document")
DOC_FLAGS = ("draft", "doc_spec", "judge_cmd", "rubric", "golden_good", "golden_bad",
             "rubric_samples", "rubric_threshold")
FAIL_CAP = 12


def is_doc(c):
    return c.get("scenario") in SCENARIOS


class Steps:
    """把命令执行、原始日志与剩余预算捆在一起；评审命令也走这里。"""

    def __init__(self, home, cwd, ctx=None, remaining=None):
        self.home, self.cwd, self.ctx, self.remaining = home, cwd, ctx, remaining

    def __call__(self, cmd, raw_name, stdin_path=None, env=None, cwd=None, cap=None):
        timeout = self.ctx["remaining"] if self.ctx else None
        if cap is not None:
            timeout = cap if timeout is None else min(timeout, cap)
        r = run_command(cmd, cwd or self.cwd, self.home.raw_path(raw_name), timeout, env, stdin_path)
        if self.ctx is not None:
            self.ctx["output"] = r.output
            if self.remaining:
                self.ctx["remaining"] = self.remaining()
        return r, f"raw/{raw_name}"

    def prompt_path(self, name):
        return self.home.raw_path(name)


# ---------------------------------------------------------------- init

def validate_args(a):
    if a.scenario in SCENARIOS:
        if not a.draft:
            fail(f"{a.scenario} 场景需要 --draft（交付文档的路径）")
        if not a.doc_spec:
            fail(f"{a.scenario} 场景需要 --doc-spec（冻结的文档规格 JSON）")
        rubric_given = [n for n in ("judge_cmd", "rubric", "golden_good", "golden_bad", "rubric_threshold")
                        if getattr(a, n, None) is not None]
        if rubric_given and len(rubric_given) != 5:
            fail("细则评审需要同时给出 --judge-cmd、--rubric、--golden-good、--golden-bad、--rubric-threshold")
        if a.rubric_samples is not None and (a.rubric_samples < 1 or a.rubric_samples > 15):
            fail("--rubric-samples 必须在 1 到 15 之间")
        if a.rubric_samples is not None and a.judge_cmd is None:
            fail("--rubric-samples 只在配置了 --judge-cmd 时有意义")
    else:
        for name in DOC_FLAGS:
            if getattr(a, name, None) is not None:
                fail(f"--{name.replace('_', '-')} 只用于研究与文档场景")
        if getattr(a, "allow_local_sources", False):
            fail("--allow-local-sources 只用于研究与文档场景")


def _repo_file(repo, rel, flag):
    rel = norm(rel)
    if os.path.isabs(rel) or rel.startswith("../"):
        fail(f"{flag} 必须是仓库内的相对路径：{rel}")
    path = os.path.join(repo, rel)
    if not os.path.isfile(path):
        fail(f"{flag} 文件不存在：{rel}")
    return rel, path


def setup(contract, a, repo):
    """补全契约里的文档字段；返回需要复制进运行目录的文件 {名字: 源路径}。"""
    draft = norm(a.draft)
    if not in_scope(draft, contract["editable"]):
        fail("--draft 必须位于 --editable 之内")
    spec_rel, spec_path = _repo_file(repo, a.doc_spec, "--doc-spec")
    try:
        with open(spec_path, encoding="utf-8") as f:
            spec = tx.check_spec(json.load(f))
    except ValueError as e:
        fail(f"文档规格不合法：{e}")
    if a.scenario == "research" and not spec.get("claims"):
        fail("研究场景的文档规格必须给出 claims（论断文件路径）；论断要能逐字核对来源")
    if spec.get("claims") and not in_scope(spec["claims"], contract["editable"]):
        fail("文档规格里的 claims 必须位于 --editable 之内")
    ok, why = tx.discriminates(spec, require_claims=a.scenario == "research")
    if not ok:
        fail(f"硬检查没有区分度：{why}；在规格里补上必需标题、min_chars 或问题清单")
    contract.update(draft=draft, doc_spec=spec_rel, allow_local_sources=bool(a.allow_local_sources),
                    questions=[q["id"] for q in spec["questions"]],
                    accept={q["id"]: q["accept"] for q in spec["questions"] if q.get("accept")})
    frozen = [spec_rel]
    copies = {"doc-spec.json": spec_path}
    if a.judge_cmd:
        cfg = {"judge_cmd": a.judge_cmd, "samples": a.rubric_samples or 3, "threshold": a.rubric_threshold}
        for key, flag in (("rubric", "--rubric"), ("good", "--golden-good"), ("bad", "--golden-bad")):
            rel, path = _repo_file(repo, getattr(a, {"good": "golden_good", "bad": "golden_bad"}.get(key, key)),
                                   flag)
            cfg[key] = rel
            frozen.append(rel)
            copies[f"rubric-{key}" + os.path.splitext(rel)[1]] = path
        contract["rubric"] = cfg
    for rel in frozen:
        contract["frozen"][rel] = sha256_file(os.path.join(repo, rel))
        if rel not in contract["frozen_paths"]:
            contract["frozen_paths"].append(rel)
    return copies


def load_doc_spec(home):
    with open(home.file("doc-spec.json"), encoding="utf-8") as f:
        return tx.check_spec(json.load(f))


def baseline(contract, home, repo, copies):
    """复制冻结的规格，评估现有草稿，校准评审。返回 baseline 字段。"""
    for name, path in copies.items():
        shutil.copyfile(path, home.file(name))
    steps = Steps(home, repo)
    result = evaluate(contract, home, repo, [], steps, "baseline", rubric=False)
    base = {"hard_ok": result["hard_ok"], "failures": result["failures"][:FAIL_CAP]}
    if contract.get("rubric"):
        contract["rubric"]["calibration"] = rb.calibrate(contract["rubric"], repo, steps)
    return base


# ---------------------------------------------------------------- 评估

def _read(path):
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def doc_sources(home, c, rows):
    loaded = src_mod.load_sources(home, rows)
    if not c.get("allow_local_sources"):
        for s in loaded.values():
            if s.get("via") == "file" or s.get("domain") == "local":
                s["reject"] = "契约不接受本地文件来源（init 时没有 --allow-local-sources）"
    return loaded


def evaluate(c, home, root, rows, steps, label, rubric=True):
    """在 root 上跑全部检查。返回 dict：hard_ok / integrity / failures / doc / accept / rubric。"""
    spec = load_doc_spec(home)
    draft_path = os.path.join(root, c["draft"])
    text = _read(draft_path)
    claims_text = _read(os.path.join(root, spec["claims"])) if spec.get("claims") else None
    doc = tx.check_document(spec, text, claims_text, doc_sources(home, c, rows),
                            require_claims=c["scenario"] == "research")
    out = {"doc": doc, "integrity": list(doc["integrity"]), "failures": list(doc["failures"]),
           "raws": []}
    if out["integrity"]:
        out["hard_ok"] = False
        return out
    if c.get("test_cmd"):
        r, raw = steps(c["test_cmd"], f"{label}.log")
        out.update(exit=r.code, raw=raw)
        if r.code != 0:
            out["failures"].append("约定命令超时" if r.timed_out else f"约定命令退出码 {r.code}")
    accept = {}
    for qid, cmd in (c.get("accept") or {}).items():
        r, raw = steps(cmd, f"{label}.accept-{qid}.log")
        accept[qid] = {"exit": r.code, "raw": raw}
        if r.code != 0:
            out["failures"].append(f"问题 {qid} 的验收命令退出码 {r.code}")
    if accept:
        out["accept"] = accept
    if spec.get("doctest") and text is not None:
        r, raw = steps(f'"{sys.executable}" -m doctest -o NORMALIZE_WHITESPACE "{draft_path}"',
                       f"{label}.doctest.log")
        out["doctest"] = {"exit": r.code, "raw": raw}
        if r.code != 0:
            out["failures"].append("文档里的代码示例没有通过 doctest")
    out["hard_ok"] = not out["failures"]
    if rubric and out["hard_ok"] and c.get("rubric"):
        t = c["rubric"]["threshold"]
        res = rb.score_document(c["rubric"], root, draft_path, steps, label, stop_below=t)
        out["rubric"] = res
        if "error" in res:
            out["rubric_error"] = res["error"]
        elif res.get("early_stop"):
            low = sum(1 for x in res["scores"] if x < t)
            out["failures"].append(f"细则评审 {low}/{res['planned']} 次采样低于通过线 {t:g}，中位数注定不达标"
                                   f"（提前结束，省下 {res['planned'] - len(res['scores'])} 次调用）")
        elif res["median"] < t:
            out["failures"].append(f"细则评审中位数 {res['median']:g} 低于通过线 {t:g}")
    return out


def _summary(out):
    doc = out["doc"]
    s = {"chars": doc["chars"], "cited": len(doc["cited"]),
         "questions": {q: v["ok"] for q, v in doc["questions"].items()}}
    if out["failures"]:
        s["failures"] = out["failures"][:FAIL_CAP]
    if out.get("rubric") and "median" in out["rubric"]:
        s["rubric"] = {"median": out["rubric"]["median"], "scores": out["rubric"]["scores"]}
        if out["rubric"].get("early_stop"):
            s["rubric"]["early_stop"] = True
    if doc.get("numbers"):
        s["numbers"] = doc["numbers"]
    return s


# ---------------------------------------------------------------- 裁决

def judge(c, home, wt, n, ctx, record, rows, remaining):
    steps = Steps(home, wt, ctx, remaining)
    out = evaluate(c, home, wt, rows, steps, f"attempt-{n:03d}")
    if out.get("raw"):
        record["raw"] = out["raw"]
    extra = {"doc": _summary(out)}
    if out.get("accept"):
        extra["accept"] = out["accept"]
    if out.get("rubric", {}).get("raw"):
        extra["rubric_raw"] = out["rubric"]["raw"]
    if out["integrity"]:
        return "invalid", INVALID, dict(extra, reason="诚信检查未通过：" + out["integrity"][0])
    if out.get("rubric_error"):
        return "invalid", INVALID, dict(extra, reason=out["rubric_error"])
    ctx["output"] = "\n".join(out["failures"]) or ctx.get("output")
    has_accepted = c.get("best_passed", False)
    if out["failures"]:
        reason = out["failures"][0]
        if has_accepted:
            return "rejected", REJECTED, dict(extra, reason="回退了已通过的版本：" + reason)
        return "failing", REJECTED, dict(extra, reason=reason)
    if c.get("rubric"):
        median = out["rubric"]["median"]
        extra["score"] = median
        best = c.get("best_score")
        noise = c["rubric"]["calibration"]["noise"]
        if has_accepted and best is not None and median < best - noise:
            return "rejected", REJECTED, dict(extra, best=best,
                                              reason=f"评审中位数 {median:g} 比已接受版本的 {best:g} 低了超过噪声 {noise:g}")
    return "accepted", ACCEPTED, extra


def verify(c, home, wt, rows, rec):
    steps = Steps(home, wt)
    out = evaluate(c, home, wt, rows, steps, "verify")
    rec["doc"] = _summary(out)
    for key in ("raw", "exit", "accept", "doctest"):
        if key in out:
            rec[key] = out[key]
    if out.get("rubric"):
        rec["rubric"] = {k: out["rubric"][k] for k in ("median", "scores", "raw", "error", "early_stop")
                         if k in out["rubric"]}
        if "median" in out["rubric"]:
            rec["score"] = out["rubric"]["median"]
    ok = not out["failures"] and not out["integrity"] and not out.get("rubric_error")
    if not ok:
        rec["reason"] = (out["integrity"] or out["failures"] or [out.get("rubric_error")])[0]
    return ok


def live_state(home, c, root, rows):
    """报告与状态用：不跑任何命令，只做纯文本检查。"""
    spec = load_doc_spec(home)
    text = _read(os.path.join(root, c["draft"]))
    claims_text = _read(os.path.join(root, spec["claims"])) if spec.get("claims") else None
    return spec, tx.check_document(spec, text, claims_text, doc_sources(home, c, rows),
                                   require_claims=c["scenario"] == "research")
