"""交付包与进度快照：handoff.html / progress.html，优化场景另出 process.svg 与 caption.json。"""
import os
import shlex

from . import formal as fm
from . import gitops as g
from . import render
from . import research as rs
from . import scenarios as sc
from . import sources as src_mod
from .contract import Home
from .judge import (emit, execution_status, last_verification, load_spec, review_state,
                    verification_required, warn)
from .util import ACCEPTED, PROG, atomic_write_json, atomic_write_text, fail, iso, sha256_file, utc_now

esc = render.esc

VERDICT_WORDS = {"simplified": "简化接受", "accepted": "接受", "rejected": "拒绝", "invalid": "无效",
                 "failing": "未通过",
                 "green": "通过", "checkpoint": "检查点", "baseline": "基线",
                 "verified": "已验证", "failed": "验证失败"}
SCENARIO_WORDS = {"bugfix": "缺陷修复", "development": "功能开发", "optimization": "性能优化",
                  "research": "研究调研", "document": "文档撰写"}


def _word(verdict):
    return VERDICT_WORDS.get(verdict, verdict)


def _raw_link(rec):
    return f'<a href="{esc(rec["raw"])}">原始日志</a>' if rec and rec.get("raw") else "-"


def _short(sha):
    return (sha or "-")[:10]


def _diff(rec):
    d = rec.get("diff") if rec else None
    return f'+{d["added"]}/-{d["deleted"]}' if d else "-"


def cmd_report(a):
    home = Home(a.home)
    with home.lock():
        return _report_locked(a, home)


def _report_locked(a, home):
    c = home.load()
    rows = home.attempts()
    progress = a.progress
    name = "progress" if progress else "handoff"
    output = os.path.abspath(a.out or home.file(name + ".html"))
    if progress:
        protected = [home.file(p) for p in ("handoff.html", "process.svg", "caption.json")]
        if c.get("report"):
            protected.append(c["report"]["path"])
        if any(os.path.realpath(output) == os.path.realpath(p) for p in protected):
            fail("进度快照不能覆盖交付包文件")
    wt = c.get("worktree")
    source = g.head(wt) if wt and os.path.isdir(wt) and g.is_work_tree(wt) else None
    clean = bool(source and not g.stray_files(wt, c.get("generated", [])) and not g.hidden_state_files(wt))
    builder = {"bugfix": report_bugfix, "development": report_development,
               "research": report_document, "document": report_document}.get(
        c["scenario"], report_optimization)
    title, subtitle, body, extra = builder(home, c, rows, progress=progress)
    verification = review_state(c, rows)["verification"]
    if c.get("formal"):
        body += fm.report_section(home, c, rows, verification)
    result = "未运行" if verification_required(c) else "未配置"
    cls = "warn"
    if verification:
        if verification["commit"] != c.get("best"):
            result = "已过期"
        else:
            result = _word(verification["verdict"])
            cls = "ok" if verification["verdict"] == "verified" else "bad"
    evidence = ""
    if verification:
        evidence = " · " + _raw_link(verification)
        if verification.get("score") is not None:
            evidence += f' · 实测分数 {esc(verification["score"])}'
    state = execution_status(home, c, rows)
    body = (checkpoint_view(home, c, rows, state, progress)
            + f'<p class="{cls}">最终验证：{result}{evidence}</p>' + body)
    if progress:
        title = "执行快照 — " + SCENARIO_WORDS.get(c["scenario"], c["scenario"])
        phase = "进行中" if state["decision"] == "continue" else "待评审"
        if state["approved"]:
            phase = "已批准"
        subtitle = f'<span class="badge">{phase} · 快照</span> ' + subtitle
    render.write_page(output, title, subtitle, body)
    if not progress:
        c["report"] = {"path": output, "commit": source, "source_clean": clean,
                       "sha256": sha256_file(output),
                       "verification_n": verification["n"] if verification else None}
        c.pop("approved", None)
        home.save(c)
        if not clean:
            warn("工作区不干净或 HEAD 无法读取；这份交付包不能用于审批")
    artifacts = [{"kind": name, "path": output}] + extra
    cmd = render.open_command(output)
    manifest = {name: output, "artifacts": artifacts,
                "open": shlex.join(cmd) if cmd else f'start "" "{output}"'}
    emit(manifest)
    if a.open_ and not render.open_path(output):
        warn(f"没有打开查看器；请手动打开：{output}")
    return ACCEPTED


def checkpoint_view(home, c, rows, state, progress):
    head = state.get("head") or "不可用"
    body = render.section("当前状态", render.stats([
        ("场景", esc(SCENARIO_WORDS.get(c["scenario"], c["scenario"]))),
        ("基线提交", _short(c["baseline"]["source"])),
        ("保留的提交", _short(c.get("best") or "未开始")),
        ("工作区 HEAD", _short(head))]))
    if "head" in state and (not state["worktree_clean"] or not state["head_is_best"]):
        body += ('<p class="warn">工作区里有记录在案的检查没有覆盖到的改动，'
                 '下面的图可能描述的是未提交或未裁决的工作。</p>')
    next_action = state["next"]
    if (not progress and state["decision"] == "handoff" and state.get("worktree_clean")
            and state.get("head_is_best") and state["verification_current"]
            and not state.get("frozen_changed") and not state["constitution_drift"]):
        next_action = f"审阅这份评审包及其证据边界；合并之前用 {PROG}.py --home <run> approve 记录人工批准。"
    body += render.section("下一步", f'<p class="next-action">{esc(next_action)}</p>')
    review = home.file("review.md")
    if os.path.isfile(review):
        with open(review, encoding="utf-8", errors="replace") as f:
            notes = f.read()
        body += render.section("AI 评审 · 判断与局限",
                               '<p class="mute">由智能体撰写的解读，不是测试裁决。</p>'
                               f'<pre class="review-notes">{esc(notes)}</pre>')
    else:
        body += render.section("AI 评审 · 判断与局限",
                               '<p class="warn">没有提供评审说明。本报告不评估语义覆盖度与未经验证的行为。</p>')
    recent = []
    for r in [r for r in rows if r.get("kind") == "attempt"][-8:]:
        rcls = "ok" if r["verdict"] in ("accepted", "green") else "warn"
        detail = r.get("reason") or r.get("note") or r.get("route") or "—"
        if r.get("failure"):
            detail += " · " + r["failure"][-1]
        verdict = "simplified" if r.get("simplified") else r["verdict"]
        recent.append([r["n"], f'<code>{_short(r.get("commit"))}</code>',
                       f'<span class="{rcls}">{esc(_word(verdict))}</span>',
                       esc(detail), _diff(r), _raw_link(r)])
    body += render.section("最近的检查记录", render.table(
        ["尝试", "提交", "裁决", "改动或失败原因", "增删行", "原始证据"], recent)
        if recent else '<p class="mute">还没有裁决过任何尝试。</p>')
    scope = ", ".join(c["editable"])
    frozen = ", ".join(c["frozen_paths"]) or "未记录"
    body += render.section("约定的边界",
                           f'<p>可编辑：<code>{esc(scope)}</code><br>'
                           f'冻结：<code>{esc(frozen)}</code></p>'
                           f'<p class="mute">快照生成于 {esc(iso(utc_now()))}。重新运行 report 并刷新页面'
                           '即可看到最新状态。记录在案的命令不能证明未被测试的行为。</p>')
    return body


# ---------------------------------------------------------------- 缺陷修复

def report_bugfix(home, c, rows, progress=False):
    attempts = [r for r in rows if r.get("kind") == "attempt"]
    verification = last_verification(rows)
    if verification and verification["commit"] != c.get("best"):
        verification = None
    final = verification or (attempts[-1] if attempts else None)
    b = c["baseline"]
    passed = bool(final and (final.get("passed") or final.get("verdict") == "verified"))

    def result(rec):
        text = "通过" if rec.get("passed") or rec.get("verdict") == "verified" else "失败"
        return text + (f'（退出码 {rec["exit"]}）' if "exit" in rec else "")

    run_rows = [["基线", f'<span class="bad">{result(b)}</span>', _raw_link(b), "—"]]
    for r in attempts:
        rcls = "ok" if r["verdict"] == "accepted" else "bad" if r["verdict"] == "invalid" else "warn"
        run_rows.append([f'尝试 {r["n"]}', f'<span class="{rcls}">{_word(r["verdict"])}</span> / {result(r)}',
                         _raw_link(r), esc(r.get("note") or r.get("reason") or "")])
    if verification:
        run_rows.append(["最终验证", result(verification), _raw_link(verification), "—"])
        red = verification.get("baseline_red")
        if red is not None:
            run_rows.append(["红绿检查（基线重跑）",
                             '<span class="ok">基线上仍失败</span>' if red
                             else '<span class="bad">基线上也通过——测试不能证明修复</span>',
                             f'<a href="{esc(verification["baseline_raw"])}">原始日志</a>', "—"])
    body = render.stats([
        ("基线", f'<span class="bad">{result(b)}</span>'),
        ("最终", f'<span class="{"ok" if passed else "bad"}">{result(final) if final else "未运行"}</span>'),
        ("尝试次数", len(attempts))])
    body += render.section("约定测试的运行记录", render.table(["运行", "结果", "证据", "说明"], run_rows))
    body += render.section("复现方式",
                           f'<p>测试命令：<code>{esc(c["test_cmd"])}</code><br>'
                           f'基线源码 <code>{_short(b["source"])}</code>；交付 '
                           f'<code>{_short(c.get("best"))}</code>。'
                           '原始日志在本目录的 <code>raw/</code> 下。</p>')
    subtitle = (f'<span class="badge {"ok" if passed else "bad"}">'
                f'{"约定测试全部通过" if passed else "尚未完成"}</span> '
                f'共记录 {len(attempts)} 次尝试')
    return "交付包 — 缺陷修复", subtitle, body, []


# ---------------------------------------------------------------- 功能开发

def report_development(home, c, rows, progress=False):
    blueprint = load_spec(home.file("blueprint.json"))
    wt = c.get("worktree") or c["repo"]
    asbuilt, asbuilt_err = None, None
    asbuilt_path = os.path.join(wt, c["asbuilt"])
    if os.path.isfile(asbuilt_path):
        try:
            asbuilt = render.load_diagram(asbuilt_path)
        except (OSError, ValueError) as e:
            asbuilt_err = str(e)
    deps = c.get("depends", {})
    claims = sc.element_progress(c["elements"], deps, rows)
    covered = render.node_ids(asbuilt) if asbuilt else set()
    done = claims["done"]
    body = '<div class="diagram-pair">' + render.section("约定的蓝图", render.graph_svg(blueprint))
    heading = "当前实现" if progress else "竣工图（交付）"
    if asbuilt is not None:
        body += render.section(heading, render.graph_svg(asbuilt))
    else:
        body += render.section(heading, f'<p class="bad">竣工图缺失或无法解析：'
                                        f'<code>{esc(c["asbuilt"])}</code> {esc(asbuilt_err or "")}</p>')
    body += ('</div><p class="mute">图描述的是实现声明。节点一致、检查变绿都不能证明语义一致；'
             '请结合代码与上面的证据边界审阅。</p>')
    cov_rows = []
    for e in c["elements"]:
        needs = ", ".join(f"<code>{esc(d)}</code>" for d in deps.get(e, [])) or "-"
        commit = claims["realized_in"].get(e)
        claim_state = "等待检查" if e in claims["pending"] else "已记录完成" if commit else "未认领"
        cov_rows.append([f"<code>{esc(e)}</code>", needs,
                         f'<code>{_short(commit)}</code>' if commit else '<span class="bad">未实现</span>',
                         '<span class="ok">是</span>' if e in covered else '<span class="bad">否</span>',
                         claim_state])
    accept = c.get("accept") or {}
    if accept:
        for row, e in zip(cov_rows, c["elements"]):
            row.append(f"<code>{esc(accept[e])}</code>" if e in accept else '<span class="mute">无</span>')
    headers = ["元素", "依赖", "认领记录于", "在竣工图中", "认领状态"] + (["验收命令"] if accept else [])
    body += render.section("元素覆盖", render.table(headers, cov_rows))
    new = set(c.get("elements_new", []))
    batches = c.get("batches", [c["elements"]])
    body += render.section("构建顺序", '<ol class="batches">' + "".join(
        "<li>" + " ".join(f"<code>{esc(e)}</code>" + (' <span class="mute">新增</span>' if e in new else "")
                          for e in batch) + "</li>"
        for batch in batches) + "</ol>")
    dep_spec = {"nodes": [{"id": e, "label": e} for e in c["elements"]],
                "edges": [{"from": d, "to": e} for e in c["elements"] for d in deps.get(e, [])]}
    pmap = {e: "done" for e in done}
    pmap.update({e: "pending" for e in claims["pending"]})
    body += render.section("依赖图",
                           '<p class="mute">绿色：在检查变绿或人工检查点时认领；'
                           '琥珀色：在检查失败时认领。两者都不是逐元素的证明。</p>'
                           + render.graph_svg(dep_spec, pmap))
    evidence = f'<p>交付提交 <code>{_short(c.get("best"))}</code>。'
    if c.get("check_cmd"):
        evidence += f' 复跑检查：<code>{esc(c["check_cmd"])}</code>。'
    evidence += ' 契约证据：<a href="attempts.jsonl">attempts.jsonl</a>、<code>raw/</code>。</p>'
    body += render.section("证据", evidence)
    subtitle = (f'<span class="badge">功能开发</span> '
                f'{len(done)}/{len(c["elements"])} 个元素已记录完成')
    extra = [{"kind": "diagram", "path": home.file(n + ".html")} for n in ("blueprint", "asis")]
    return "交付包 — 功能开发", subtitle, body, extra


# ---------------------------------------------------------------- 性能优化

def report_optimization(home, c, rows, progress=False):
    pts = [r for r in rows if r.get("kind") in ("baseline", "attempt")]
    unit, direction = c["score"]["unit"], c["score"]["direction"]
    target, baseline = c.get("target"), c["baseline"]["score"]
    if not pts:
        pts = [{"kind": "baseline", "verdict": "baseline", "score": baseline,
                "commit": c["baseline"]["source"]}]
    svg = render.chart_svg(pts, unit, direction, target, baseline)
    prefix = "progress-" if progress else ""
    svg_name, caption_name = prefix + "process.svg", prefix + "caption.json"
    svg_path = home.file(svg_name)
    atomic_write_text(svg_path, svg + "\n")
    final = c.get("best_score")
    if final is None:
        final = baseline
    imp = (baseline - final) if direction == "lower" else (final - baseline)
    pct = None if baseline == 0 else imp / abs(baseline) * 100
    routes = sc.route_tallies(pts)
    met = sc.contract_meets_target(c, final)
    verification = last_verification(rows)
    if verification and verification["commit"] != c.get("best"):
        verification = None
    caption = {"baseline": baseline, "final": final, "unit": unit, "direction": direction,
               "improvement": imp, "improvement_pct": pct, "target": target,
               "target_met": met, "attempts": len([r for r in pts if r.get("kind") == "attempt"]),
               "routes": routes, "delta": c.get("delta"), "noise": c["baseline"].get("noise"),
               "score_basis": "recorded best", "verification": verification,
               "delivered_commit": c.get("best"), "rerun": c["test_cmd"], "chart": svg_path,
               "secondary": ({"direction": c["secondary"]["direction"],
                              "baseline": c["baseline"].get("secondary"), "final": c.get("best_secondary")}
                             if c.get("secondary") else None),
               "prefer_simpler": bool(c.get("prefer_simpler")),
               "tokens_used": sum(int(r.get("tokens") or 0) for r in pts if r.get("kind") == "attempt")}
    caption_path = home.file(caption_name)
    atomic_write_json(caption_path, caption)
    body = render.stats([
        ("基线", f"{baseline:g} {esc(unit)}"),
        ("记录的最优", f"{final:g} {esc(unit)}"),
        ("改进", f'{imp:g} {esc(unit)}' + (f"（{pct:.1f}%）" if pct is not None else "")),
        ("目标", (f'<span class="{"ok" if met else "bad"}">{target:g} {"达成" if met else "未达成"}</span>'
                 if target is not None else '<span class="mute">未设目标线（纯改进，按预算交付）</span>')),
        ("δ / 噪声", f'{c.get("delta", 0):g} / {c["baseline"].get("noise", 0):g}')]
        + ([("次要指标", f'{c["baseline"]["secondary"]:g} → {c.get("best_secondary"):g}')]
           if c.get("secondary") and c.get("best_secondary") is not None else []))
    body += render.section("过程", svg)
    route_rows = [[esc(k), v.get("accepted", 0), v.get("simplified", 0), v.get("rejected", 0),
                   v.get("invalid", 0)] for k, v in routes.items()]
    body += render.section("路线 — 接受 / 其中简化 / 拒绝 / 无效",
                           render.table(["路线", "接受", "其中简化", "拒绝", "无效"], route_rows)
                           if route_rows else '<p class="mute">还没有尝试。</p>')
    body += render.section("证据",
                           f'<p>交付提交 <code>{_short(c.get("best"))}</code>。'
                           f'复跑基准：<code>{esc(c["test_cmd"])}</code>。'
                           '<a href="attempts.jsonl">attempts.jsonl</a> · '
                           f'<a href="{caption_name}">{caption_name}</a> · '
                           f'<a href="{svg_name}">{svg_name}</a>；原始日志在 <code>raw/</code> 下。</p>')
    outcome, cls = "待验证", "warn"
    if verification:
        outcome, cls = "验证失败", "bad"
        if verification["verdict"] == "verified":
            if target is None:
                outcome, cls = ("已改进", "ok") if imp > 0 else ("未改进", "warn")
            else:
                outcome, cls = ("目标达成", "ok") if met else ("目标未达成", "warn")
    subtitle = (f'<span class="badge {cls}">{outcome}</span> '
                f'基线 {baseline:g} → 记录的最优 {final:g} {esc(unit)} · {caption["attempts"]} 次尝试')
    extra = [{"kind": "chart", "path": svg_path}, {"kind": "caption", "path": caption_path}]
    return "交付包 — 性能优化", subtitle, body, extra


# ---------------------------------------------------------------- 研究 / 文档

def report_document(home, c, rows, progress=False):
    """论断 → 来源对照表、问题覆盖图、细则评审的校准与得分。"""
    wt = c.get("worktree")
    root = wt if wt and os.path.isdir(wt) else c["repo"]
    spec, doc = rs.live_state(home, c, root, rows)
    srcs = src_mod.registered(rows)
    loaded = rs.doc_sources(home, c, rows)
    attempts = [r for r in rows if r.get("kind") == "attempt"]
    accepted = bool(attempts) and sc.kept(rows) and sc.kept(rows)[-1]["verdict"] == "accepted"
    covered = sum(1 for v in doc["questions"].values() if v["ok"])
    body = render.stats([
        ("正文字符", doc["chars"]),
        ("被引用的论断", len(doc["cited"])),
        ("登记的来源", len(srcs)),
        ("问题覆盖", f'{covered}/{len(doc["questions"])}' if doc["questions"] else "未约定"),
        ("数字出处", ("未约定" if "numbers" not in doc else
                  ("全部有出处" if not any(doc["numbers"].values())
                   else f'{doc["numbers"]["uncited"]} 句无引用 / {doc["numbers"]["unsupported"]} 个数字对不上'))),
        ("细则评审", esc(c.get("best_score")) if c.get("rubric") and c.get("best_score") is not None
         else ("未配置" if not c.get("rubric") else "未评"))])
    if doc["failures"]:
        body += render.section("硬检查未满足", "<ul>" + "".join(
            f'<li class="bad">{esc(f)}</li>' for f in doc["failures"][:rs.FAIL_CAP]) + "</ul>")
    q_rows = []
    for qid, v in doc["questions"].items():
        cls = "ok" if v["ok"] else "bad"
        q_rows.append([f"<code>{esc(qid)}</code>", esc(v["text"]),
                       f'<span class="{cls}">{v.get("distinct", len(v["domains"]))}/{v["min_sources"]}</span>',
                       esc(", ".join(v["domains"]) or "—"), esc(", ".join(v["claims"]) or "—")])
    if q_rows:
        body += render.section("问题覆盖", render.table(
            ["问题", "内容", "不同域名 / 要求", "来源域名", "有效论断"], q_rows))
    c_rows = []
    for cid, st in doc["claims"].items():
        src = srcs.get(st["source"])
        link = (f'<a href="{esc(src["snapshot"])}">快照</a> · <code>{esc(src["sha256"][:10])}</code>'
                if src else "—")
        url = src["url"] if src else ""
        url_html = (f'<a href="{esc(url)}">{esc(url)}</a>' if url.startswith(("http://", "https://"))
                    else esc(url or "未登记"))
        state = ('<span class="ok">逐字核对通过</span>' if st["ok"]
                 else f'<span class="{"bad" if st["cited"] else "warn"}">{esc(st.get("reason", ""))}</span>')
        c_rows.append([f"<code>{esc(cid)}</code>", esc(st.get("question") or "—"),
                       "是" if st["cited"] else "否", url_html, link, state])
    body += render.section("论断 → 来源", render.table(
        ["论断", "问题", "草稿引用", "来源", "快照", "核对"], c_rows) if c_rows
        else '<p class="mute">没有论断记录。</p>')
    tampered = [sid for sid, s in loaded.items() if s["text"] is None]
    if tampered:
        body += f'<p class="bad">来源快照被改动或删除：{esc(", ".join(tampered))}</p>'
    flagged = [(sid, r) for sid, r in srcs.items() if r.get("duplicate_of") or r.get("injection")]
    if flagged:
        items = []
        for sid, r in flagged:
            notes = []
            if r.get("duplicate_of"):
                notes.append(f'与 {esc(r["duplicate_of"])} 内容完全相同，只算一个来源')
            if r.get("injection"):
                notes.append(f'快照含疑似评审指令文本：{esc(r["injection"][0])}')
            items.append(f'<li class="warn"><code>{esc(sid)}</code>：{"；".join(notes)}</li>')
        body += render.section("来源提示", "<ul>" + "".join(items) + "</ul>")
    rub = c.get("rubric")
    if rub:
        cal = rub.get("calibration", {})
        scored = [r for r in attempts if r.get("score") is not None]
        body += render.section("细则评审（只能否决）", render.stats([
            ("通过线", esc(rub["threshold"])), ("每次采样", esc(rub["samples"])),
            ("好样本中位数", esc(cal.get("good"))), ("差样本中位数", esc(cal.get("bad"))),
            ("评审噪声", esc(cal.get("noise")))]) + (render.table(
                ["尝试", "裁决", "中位数", "各次得分"],
                [[r["n"], esc(_word(r["verdict"])), esc(r["score"]),
                  esc(", ".join(f"{x:g}" for x in r.get("doc", {}).get("rubric", {}).get("scores", [])))]
                 for r in scored]) if scored else '<p class="mute">还没有评过分。</p>')
            + '<p class="mute">评审分只用于否决：硬检查与验收命令没过时，分数再高也不能接受。</p>')
    body += render.section("复现方式",
                           f'<p>草稿：<code>{esc(c["draft"])}</code>；规格：<code>{esc(c["doc_spec"])}</code>'
                           + (f'；论断：<code>{esc(spec["claims"])}</code>' if spec.get("claims") else "")
                           + '。来源快照在本目录的 <code>sources/</code> 下，按内容哈希命名；'
                           '原始日志在 <code>raw/</code> 下。</p>')
    word = SCENARIO_WORDS[c["scenario"]]
    ok = accepted and doc["ok"] and not tampered
    subtitle = (f'<span class="badge {"ok" if ok else "bad"}">{"检查全部通过" if ok else "尚未完成"}</span> '
                f'共记录 {len(attempts)} 次尝试')
    return f"交付包 — {word}", subtitle, body, []

