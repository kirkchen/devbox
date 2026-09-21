import sys, os, glob, tempfile, unittest, importlib.util
from unittest import mock

# executable_model-router.py has a hyphen in its name (chezmoi's `executable_` prefix
# strips down to `model-router.py` on deploy), so it can't be `import`ed by name like the
# other tool-reduce modules — load it from its file path instead.
HOOK_PATH = os.path.join(
    os.path.dirname(__file__),
    "../../chezmoi/private_dot_config/claude/hooks/executable_model-router.py",
)
_spec = importlib.util.spec_from_file_location("model_router_hook", HOOK_PATH)
mr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mr)


def _write(tmpdir, name, content):
    path = os.path.join(tmpdir, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


class TestParseFrontmatterModel(unittest.TestCase):
    """_parse_frontmatter_model: only the first ---delimited block counts."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_model_from_frontmatter(self):
        p = _write(self.tmp.name, "a.md", "---\nname: a\nmodel: opus\n---\nbody\n")
        self.assertEqual(mr._parse_frontmatter_model(p), "opus")

    def test_quoted_model_value_is_unquoted(self):
        p = _write(self.tmp.name, "a.md", '---\nmodel: "opus"\n---\n')
        self.assertEqual(mr._parse_frontmatter_model(p), "opus")

    def test_model_inherit_is_returned_as_literal_string(self):
        # inherit is parsed like any other value; deciding it's "not a pin" is is_pinned's job.
        p = _write(self.tmp.name, "a.md", "---\nmodel: inherit\n---\n")
        self.assertEqual(mr._parse_frontmatter_model(p), "inherit")

    def test_missing_model_key_returns_none(self):
        p = _write(self.tmp.name, "a.md", "---\nname: a\ntools: Read\n---\nbody\n")
        self.assertIsNone(mr._parse_frontmatter_model(p))

    def test_model_in_body_after_closing_delimiter_is_ignored(self):
        p = _write(self.tmp.name, "a.md",
                    "---\nname: a\n---\nSome prose about the model: opus release.\nmodel: opus\n")
        self.assertIsNone(mr._parse_frontmatter_model(p))

    def test_file_with_no_frontmatter_block_returns_none(self):
        p = _write(self.tmp.name, "a.md", "just a plain markdown file\nmodel: opus\n")
        self.assertIsNone(mr._parse_frontmatter_model(p))

    def test_missing_file_returns_none_not_raise(self):
        self.assertIsNone(mr._parse_frontmatter_model(os.path.join(self.tmp.name, "nope.md")))

    def test_undecodable_file_returns_none_not_raise(self):
        p = os.path.join(self.tmp.name, "binary.md")
        with open(p, "wb") as fh:
            fh.write(b"\xff\xfe\x00\x01 not valid utf-8 at all")
        self.assertIsNone(mr._parse_frontmatter_model(p))


class TestAgentFileCandidates(unittest.TestCase):
    """_agent_file: candidate paths, in priority order, for a subagent_type."""

    def test_non_plugin_name_yields_project_then_user_path(self):
        candidates = list(mr._agent_file("some-agent"))
        self.assertEqual(candidates, [
            os.path.join(os.getcwd(), ".claude", "agents", "some-agent.md"),
            os.path.expanduser("~/.claude/agents/some-agent.md"),
        ])

    def test_plugin_name_splits_on_first_colon_and_globs_plugin_cache(self):
        expected = glob.glob(os.path.expanduser(
            "~/.claude/plugins/cache/*/codex/*/agents/codex-rescue.md"))
        self.assertEqual(list(mr._agent_file("codex:codex-rescue")), expected)
        # Sanity: this machine actually has the plugin installed (see README's file table).
        self.assertTrue(expected, "expected a real codex plugin cache hit on this machine")


class TestResolvePinnedModelWithFakeAgentFile(unittest.TestCase):
    """resolve_pinned_model / is_pinned / is_routable, with _agent_file patched to a
    tempfile so these don't depend on any file outside the repo."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _patched(self, path):
        return mock.patch.object(mr, "_agent_file", lambda name: iter([path]))

    def test_inherit_is_not_a_pin_and_routes(self):
        p = _write(self.tmp.name, "a.md", "---\nmodel: inherit\n---\n")
        with self._patched(p):
            self.assertEqual(mr.resolve_pinned_model("whatever"), "inherit")
            self.assertFalse(mr.is_pinned("whatever"))
            self.assertTrue(mr.is_routable("whatever"))

    def test_frontmatter_with_no_model_key_routes(self):
        p = _write(self.tmp.name, "a.md", "---\nname: a\n---\n")
        with self._patched(p):
            self.assertIsNone(mr.resolve_pinned_model("whatever"))
            self.assertTrue(mr.is_routable("whatever"))

    def test_concrete_pinned_model_skips(self):
        p = _write(self.tmp.name, "a.md", "---\nmodel: opus\n---\n")
        with self._patched(p):
            self.assertTrue(mr.is_pinned("whatever"))
            self.assertFalse(mr.is_routable("whatever"))

    def test_unparseable_file_routes_rather_than_raising(self):
        p = os.path.join(self.tmp.name, "bad.md")
        with open(p, "wb") as fh:
            fh.write(b"\xff\xfe\x00\x01 not utf8 at all")
        with self._patched(p):
            try:
                routable = mr.is_routable("whatever")
            except Exception as e:  # pragma: no cover - the point is this must not happen
                self.fail(f"is_routable raised instead of failing open: {e!r}")
            self.assertTrue(routable)

    def test_no_candidate_file_exists_routes(self):
        missing = os.path.join(self.tmp.name, "nope.md")
        with mock.patch.object(mr, "_agent_file", lambda name: iter([missing])):
            self.assertIsNone(mr.resolve_pinned_model("whatever"))
            self.assertTrue(mr.is_routable("whatever"))


class TestIsRoutableDecisionTable(unittest.TestCase):
    """Encodes the verified decision table against real files on this machine
    (~/.claude/agents/eval-judge.md and the two plugin caches listed in the task)."""

    ROUTES = [
        "general-purpose", "Explore", "Plan", "claude",
        "claude-code-guide", "statusline-setup", "totally-unknown-agent-xyz",
    ]
    SKIPS = {
        "eval-judge": "opus",
        "codex:codex-rescue": "sonnet",
        "code-simplifier:code-simplifier": "opus",
    }

    def test_pinned_real_agents_skip(self):
        for name, model in self.SKIPS.items():
            with self.subTest(name=name):
                self.assertEqual(mr.resolve_pinned_model(name), model)
                self.assertTrue(mr.is_pinned(name))
                self.assertFalse(mr.is_routable(name))

    def test_agent_types_with_no_definition_file_route(self):
        for name in self.ROUTES:
            with self.subTest(name=name):
                self.assertIsNone(mr.resolve_pinned_model(name))
                self.assertTrue(mr.is_routable(name))

    def test_fork_skips_via_explicit_skip_set_despite_no_file(self):
        self.assertIsNone(mr.resolve_pinned_model("fork"))
        self.assertFalse(mr.is_routable("fork"))

    def test_omitted_subagent_type_normalises_to_general_purpose_and_routes(self):
        self.assertTrue(mr.is_routable(None))
        self.assertTrue(mr.is_routable(""))


if __name__ == "__main__":
    unittest.main()
