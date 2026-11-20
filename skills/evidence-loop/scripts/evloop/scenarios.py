"""三种场景的纯逻辑：不碰 git、不碰文件系统，便于单测。"""
import re

# ---------------------------------------------------------------- 优化


def extract_score(regex, output):
    """取最后一个匹配；有捕获组时取第一组。无法转成数字返回 None。"""
    try:
        matches = re.findall(regex, output, re.MULTILINE)
    except re.error:
        return None
    if not matches:
        return None
    m = matches[-1]
    if isinstance(m, tuple):
        m = m[0] if m else ""
    try:
        value = float(m)
    except (TypeError, ValueError):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def improves(direction, delta, score, best):
    """超过当前最优至少 δ 才算改进；噪声范围内的波动一律拒绝。"""
    if direction == "lower":
        return score < best - delta
    return score > best + delta


def worse_by(direction, score, best):
    """score 比 best 差了多少（为负表示更好）。"""
    return score - best if direction == "lower" else best - score


def within_noise(direction, delta, score, best):
    """没有变差到 δ 或以上：视为与当前最优持平。"""
    return worse_by(direction, score, best) < delta


def meets_target(direction, target, inclusive, score):
    if target is None or score is None:
        return False
    if direction == "lower":
        return score <= target if inclusive else score < target
    return score >= target if inclusive else score > target


def contract_improves(c, score, best):
    return improves(c["score"]["direction"], c["delta"], score, best)


def contract_meets_target(c, score):
    return meets_target(c["score"]["direction"], c.get("target"), c.get("inclusive", True), score)


ROUTE_RE = re.compile(r"[A-Za-z0-9_.-]+")


def ruled_out(rows, best):
    """在当前最优之上已被证伪的路线：{route: [n…]}。

    拒绝，或在真正跑过命令（留有 raw）后判为无效，都算证伪；最优一旦前进，旧证伪自动失效。
    """
    dead = {}
    for r in rows:
        refuted = r.get("verdict") == "rejected" or (r.get("verdict") == "invalid" and r.get("raw"))
        if r.get("kind") == "attempt" and r.get("route") and refuted and r.get("base") == best:
            dead.setdefault(r["route"], []).append(r["n"])
    return dead


def route_tallies(rows):
    routes = {}
    for r in rows:
        if r.get("kind") != "attempt":
            continue
        tally = routes.setdefault(r.get("route") or "-",
                                  {"accepted": 0, "rejected": 0, "invalid": 0, "simplified": 0})
        if r.get("simplified"):
            tally["simplified"] += 1
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
    return routes


# ---------------------------------------------------------------- 开发


def blueprint_depends(spec, elements):
    """规范化 depends：去重、拒绝未知 ID 与自依赖。返回 (deps, 错误信息或 None)。"""
    deps = {}
    known = set(elements)
    for node, needs in spec.get("depends", {}).items():
        needs = list(dict.fromkeys(needs))
        unknown = [e for e in [node, *needs] if e not in known]
        if unknown:
            return None, f'"depends" 引用了 nodes 中不存在的 ID：{unknown}'
        if node in needs:
            return None, f"元素 {node} 依赖了自己"
        deps[node] = needs
    return deps, None


def kept(rows):
    """参与进度计算的尝试：被判无效的不算。"""
    return [r for r in rows if r.get("kind") == "attempt" and r.get("verdict") != "invalid"]


def element_progress(elements, depends, rows):
    """按记录推导元素进度。

    检查失败时认领的元素进入 pending；下一次检查变绿（或无检查命令时的人工检查点）
    把 pending 与本次认领一起记为完成，完成提交取第一次变绿的那次。
    """
    pending, realized = set(), {}
    for r in kept(rows):
        claimed = set(r.get("elements", []))
        if r["verdict"] == "failing":
            pending |= claimed
        elif r["verdict"] in ("green", "checkpoint"):
            for e in sorted(pending | claimed):
                realized.setdefault(e, r["commit"])
            pending = set()
    done = [e for e in elements if e in realized]
    open_ = [e for e in elements if e not in realized]
    ready = [e for e in open_ if set(depends.get(e, [])) <= set(done)]
    return {"done": done, "ready": ready, "blocked": [e for e in open_ if e not in ready],
            "pending": [e for e in open_ if e in pending], "realized_in": realized}


def unmet_dependencies(claimed, depends, done):
    return sorted({d for e in claimed for d in depends.get(e, [])} - set(done) - set(claimed))
