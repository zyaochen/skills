"""纯逻辑与渲染的单元测试：不起子进程、不碰 git。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

import helpers  # noqa: F401 —— 把 scripts/ 加入 sys.path
from evloop import render
from evloop import scenarios as sc
from evloop.util import in_scope, norm, overlaps
from helpers import ENV, RENDER


class ScoreTests(unittest.TestCase):
    def test_extract_last_match_and_group(self):
        self.assertEqual(sc.extract_score(r"t=([0-9.]+)", "t=3\nt=4.5\n"), 4.5)
        self.assertEqual(sc.extract_score(r"[0-9]+", "a 7 b 9"), 9.0)

    def test_extract_rejects_non_numbers(self):
        self.assertIsNone(sc.extract_score(r"t=(\w+)", "t=abc"))
        self.assertIsNone(sc.extract_score(r"t=(\w+)", "t=nan"))
        self.assertIsNone(sc.extract_score(r"t=(\w+)", "t=inf"))
        self.assertIsNone(sc.extract_score(r"t=(\d+)", "nothing"))
        self.assertIsNone(sc.extract_score(r"(", "x"))

    def test_improves_requires_strictly_more_than_delta(self):
        self.assertTrue(sc.improves("lower", 5, 94, 100))
        self.assertFalse(sc.improves("lower", 5, 95, 100))
        self.assertTrue(sc.improves("higher", 5, 106, 100))
        self.assertFalse(sc.improves("higher", 5, 105, 100))

    def test_meets_target(self):
        self.assertTrue(sc.meets_target("lower", 10, True, 10))
        self.assertFalse(sc.meets_target("lower", 10, False, 10))
        self.assertTrue(sc.meets_target("higher", 10, False, 11))
        self.assertFalse(sc.meets_target("higher", 10, True, None))


class RouteTests(unittest.TestCase):
    rows = [
        {"kind": "baseline", "n": 0, "verdict": "baseline"},
        {"kind": "attempt", "n": 1, "route": "a", "verdict": "rejected", "base": "B0"},
        {"kind": "attempt", "n": 2, "route": "b", "verdict": "invalid", "base": "B0"},
        {"kind": "attempt", "n": 3, "route": "c", "verdict": "invalid", "base": "B0", "raw": "raw/x"},
        {"kind": "attempt", "n": 4, "route": "d", "verdict": "accepted", "base": "B0"},
        {"kind": "attempt", "n": 5, "route": "a", "verdict": "rejected", "base": "B1"},
    ]

    def test_ruled_out_is_relative_to_best(self):
        self.assertEqual(sc.ruled_out(self.rows, "B0"), {"a": [1], "c": [3]})
        self.assertEqual(sc.ruled_out(self.rows, "B1"), {"a": [5]})

    def test_tallies(self):
        t = sc.route_tallies(self.rows)
        self.assertEqual(t["a"]["rejected"], 2)
        self.assertEqual(t["d"]["accepted"], 1)
        self.assertNotIn("-", t)


class ElementTests(unittest.TestCase):
    elements = ["db", "api", "ui"]
    deps = {"api": ["db"], "ui": ["api"]}

    def test_progress_and_pending(self):
        rows = [{"kind": "attempt", "n": 1, "verdict": "failing", "elements": ["db"], "commit": "c1"},
                {"kind": "attempt", "n": 2, "verdict": "invalid", "elements": ["api"], "commit": "c2"},
                {"kind": "attempt", "n": 3, "verdict": "green", "commit": "c3"}]
        p = sc.element_progress(self.elements, self.deps, rows[:2])
        self.assertEqual((p["done"], p["pending"], p["ready"]), ([], ["db"], ["db"]))
        p = sc.element_progress(self.elements, self.deps, rows)
        self.assertEqual(p["done"], ["db"])
        self.assertEqual(p["realized_in"], {"db": "c3"})
        self.assertEqual((p["ready"], p["blocked"]), (["api"], ["ui"]))

    def test_unmet_dependencies(self):
        self.assertEqual(sc.unmet_dependencies(["ui"], self.deps, []), ["api"])
        self.assertEqual(sc.unmet_dependencies(["ui", "api"], self.deps, ["db"]), [])

    def test_blueprint_depends_validation(self):
        spec = {"depends": {"api": ["db", "db"]}}
        self.assertEqual(sc.blueprint_depends(spec, self.elements), ({"api": ["db"]}, None))
        self.assertIsNotNone(sc.blueprint_depends({"depends": {"api": ["api"]}}, self.elements)[1])
        self.assertIsNotNone(sc.blueprint_depends({"depends": {"x": []}}, self.elements)[1])


class PathTests(unittest.TestCase):
    def test_scope_rules(self):
        self.assertTrue(in_scope("src/a.py", ["src"]))
        self.assertFalse(in_scope("srcx/a.py", ["src"]))
        self.assertTrue(in_scope("anything", ["."]))
        self.assertTrue(in_scope("src", ["./src/"]))
        self.assertTrue(overlaps("a/b", "a"))
        self.assertFalse(overlaps("a/b", "a/c"))
        self.assertEqual(norm("./x/y/"), "x/y")


class DiagramTests(unittest.TestCase):
    good = {"nodes": [{"id": "a", "label": "A"}, {"id": "b"}], "edges": [{"from": "a", "to": "b"}],
            "regions": [{"label": "R", "wraps": ["a", "b"]}], "depends": {"b": ["a"]}}

    def bad(self, spec):
        with self.assertRaises(render.DiagramError):
            render.check_diagram(spec)

    def test_validation(self):
        render.check_diagram(self.good)
        self.bad({"nodes": []})
        self.bad({"nodes": [{"id": "has space"}]})
        self.bad({"nodes": [{"id": "a"}, {"id": "a"}]})
        self.bad({"nodes": [{"id": "a", "label": 3}]})
        self.bad({"nodes": [{"id": "a"}], "edges": [{"from": "a", "to": "z"}]})
        self.bad({"nodes": [{"id": "a"}], "edges": {"from": "a"}})
        self.bad({"nodes": [{"id": "a"}], "regions": [{"wraps": "a"}]})
        self.bad({"nodes": [{"id": "a"}], "depends": {"a": "a"}})
        self.bad({"nodes": [{"id": "a"}], "depends": {"a": ["z"]}})
        self.bad([])

    def test_signature_ignores_layout_and_title(self):
        moved = json.loads(json.dumps(self.good))
        moved["meta"] = {"title": "x"}
        moved["nodes"][0]["row"] = 3
        moved["depends"] = {"b": ["a", "a"]}
        self.assertEqual(render.diagram_signature(moved), render.diagram_signature(self.good))
        moved["edges"] = []
        self.assertNotEqual(render.diagram_signature(moved), render.diagram_signature(self.good))

    def test_topo_batches(self):
        self.assertEqual(render.topo_batches(["a", "b", "c"], {"c": ["a"], "b": ["c"]}),
                         ([["a"], ["c"], ["b"]], []))
        self.assertEqual(render.topo_batches(["a", "b"], {"a": ["b"], "b": ["a"]}), ([], ["a", "b"]))

    def test_long_chain_does_not_recurse(self):
        n = 3000
        spec = {"nodes": [{"id": f"n{i}"} for i in range(n)],
                "edges": [{"from": f"n{i}", "to": f"n{i + 1}"} for i in range(n - 1)]}
        self.assertEqual(max(render._depths(spec).values()), n - 1)

    def test_cyclic_edges_still_render(self):
        spec = {"nodes": [{"id": "a"}, {"id": "b"}],
                "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}]}
        self.assertIn("<svg", render.graph_svg(spec))

    def test_graph_escapes_labels(self):
        spec = {"nodes": [{"id": "a", "label": "<script>"}]}
        svg = render.graph_svg(spec)
        self.assertNotIn("<script>", svg)
        self.assertIn("&lt;script&gt;", svg)

    def test_chart_handles_single_point_and_flat_series(self):
        pts = [{"kind": "baseline", "verdict": "baseline", "score": 5.0, "commit": "x"}]
        self.assertIn("<svg", render.chart_svg(pts, "ms", "lower", 5.0, 5.0))
        pts.append({"kind": "attempt", "n": 1, "verdict": "rejected", "score": 5.0})
        self.assertIn("<svg", render.chart_svg(pts, "ms", "higher", 5.0, 5.0))


class RenderCliTests(unittest.TestCase):
    def test_render_cli(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "g.json")
            with open(src, "w", encoding="utf-8") as f:
                json.dump(DiagramTests.good, f)
            r = subprocess.run([sys.executable, RENDER, src], text=True, capture_output=True, env=ENV)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.isfile(os.path.join(d, "g.html")))
            with open(src, "w", encoding="utf-8") as f:
                f.write("{bad")
            r = subprocess.run([sys.executable, RENDER, src], text=True, capture_output=True, env=ENV)
            self.assertEqual(r.returncode, 3)

    def test_example_blueprint_renders(self):
        path = os.path.join(helpers.SKILL, "assets", "blueprint.json")
        spec = render.load_diagram(path)
        self.assertIn("<svg", render.graph_svg(spec))
        deps, err = sc.blueprint_depends(spec, [n["id"] for n in spec["nodes"]])
        self.assertIsNone(err)
        self.assertEqual(render.topo_batches([n["id"] for n in spec["nodes"]], deps)[1], [])


if __name__ == "__main__":
    unittest.main()
