"""文档一致性：链接存在、提到的参数真实存在、不夹带外部来源信息。"""
import os
import re
import unittest

import helpers  # noqa: F401 —— 把 scripts/ 加入 sys.path
from evloop import cli, constitution, evals, matrix, render, tlc

SKILL = helpers.SKILL
DOCS = [os.path.join(SKILL, "SKILL.md")] + sorted(
    os.path.join(SKILL, "references", n) for n in os.listdir(os.path.join(SKILL, "references"))
    if n.endswith(".md"))
AGENTS_MD = os.path.join(SKILL, "assets", "AGENTS.md")
# 拼接构造，避免本文件自己命中
# 文档里提到的外部命令行参数（git、codex、claude 自己的参数），不属于本技能
EXTERNAL_FLAGS = {"--no-ff", "--no-local", "--single-branch",
                  "--json", "--add-dir", "--model", "--output-format", "--permission-mode",
                  "--effort", "--resume", "--skip-git-repo-check", "--hard"}
FORBIDDEN = ["auto" + "dev", "Momo" + "yeyu", "cann" + "2026", "git" + "hub.com", r"\bM" + r"oE\b",
             "auto" + "pilot"]


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def parser_options(parser):
    """递归收集所有层级子命令的参数（source add、plan init 等嵌套动作也算）。"""
    opts = set(parser._option_string_actions)
    if parser._subparsers is not None:
        for action in parser._subparsers._group_actions:
            for sub in action.choices.values():
                opts |= parser_options(sub)
    return opts


def all_options():
    return (parser_options(cli.build_parser()) | parser_options(evals.build_parser())
            | parser_options(matrix.build_parser()) | parser_options(tlc.build_parser()))


def frontmatter(text):
    """极简 YAML 子集解析：顶层 key: value，以及一层缩进的映射。"""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None
    meta, parent = {}, None
    for line in m.group(1).splitlines():
        if not line.strip():
            continue
        key, _, value = line.strip().partition(":")
        value = value.strip().strip('"')
        if line.startswith((" ", "\t")) and parent:
            meta[parent][key] = value
        elif value:
            meta[key], parent = value, None
        else:
            meta[key], parent = {}, key
    return meta


class DocTests(unittest.TestCase):
    def test_frontmatter(self):
        text = read(DOCS[0])
        meta = frontmatter(text)
        self.assertIsNotNone(meta, "SKILL.md 缺少 frontmatter")
        self.assertEqual(meta.get("name"), "evidence-loop")
        self.assertGreater(len(meta.get("description", "")), 20)

    def test_frontmatter_follows_skill_spec(self):
        text = read(DOCS[0])
        meta = frontmatter(text)
        name = meta["name"]
        self.assertEqual(name, os.path.basename(SKILL), "name 必须与目录名一致")
        self.assertRegex(name, r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertLessEqual(len(name), 64)
        self.assertLessEqual(len(meta["description"]), 1024)
        self.assertLessEqual(len(meta.get("compatibility", "")), 500)
        self.assertLess(text.count("\n"), 500, "SKILL.md 正文应少于 500 行")
        md = meta.get("metadata", {})
        self.assertIsInstance(md, dict)
        self.assertTrue(all(isinstance(v, str) for v in md.values()))
        from evloop import __version__
        self.assertEqual(md.get("version"), __version__, "frontmatter 版本与代码版本不一致")
        allowed = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
        self.assertLessEqual(set(meta), allowed)

    def test_agent_side_files(self):
        self.assertIn("SKILL.md", read(AGENTS_MD))
        yaml = read(os.path.join(SKILL, "assets", "openai.yaml"))
        for key in ("interface:", "display_name:", "short_description:", "default_prompt:"):
            self.assertIn(key, yaml)

    def test_examples_are_valid(self):
        ex = os.path.join(SKILL, "assets")
        spec = render.load_diagram(os.path.join(ex, "blueprint.json"))
        self.assertTrue(spec["nodes"])
        law, rel = constitution.load(ex, "constitution.json")
        self.assertEqual(rel, "constitution.json")
        self.assertTrue(law)

    def test_links_resolve(self):
        for doc in DOCS + [AGENTS_MD]:
            for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", read(doc)):
                if "://" in target:
                    continue
                path = os.path.normpath(os.path.join(os.path.dirname(doc), target))
                self.assertTrue(os.path.exists(path), f"{os.path.basename(doc)} 链接失效：{target}")

    def test_all_references_are_linked_from_skill(self):
        skill = read(DOCS[0])
        for doc in DOCS[1:]:
            self.assertIn("references/" + os.path.basename(doc), skill)

    def test_mentioned_flags_exist(self):
        known = all_options()
        for doc in DOCS + [AGENTS_MD]:
            for flag in set(re.findall(r"(?<![\w-])--[a-z][a-z0-9-]+", read(doc))):
                if flag in EXTERNAL_FLAGS:
                    continue
                self.assertIn(flag, known, f"{os.path.basename(doc)} 提到了不存在的参数 {flag}")

    def test_mentioned_commands_exist(self):
        parser = cli.build_parser()
        commands = set(parser._subparsers._group_actions[0].choices)
        for name in ("init", "start", "smoke", "attempt", "status", "verify", "report",
                     "approve", "relocate", "doctor", "resume", "source", "plan"):
            self.assertIn(name, commands)
            self.assertIn(f"`{name}", read(DOCS[0]))

    def test_no_foreign_identifiers(self):
        pattern = re.compile("|".join(FORBIDDEN), re.I)
        for root, dirs, files in os.walk(SKILL):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in files:
                path = os.path.join(root, name)
                hit = pattern.search(read(path))
                self.assertIsNone(hit, f"{os.path.relpath(path, SKILL)} 含有 {hit and hit.group(0)}")


if __name__ == "__main__":
    unittest.main()
