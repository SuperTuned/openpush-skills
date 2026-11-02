from pathlib import Path
import unittest


from openpush_scan import bundle


# An openpush checkout keeps the skill at <repo>/skills and a packaged copy in
# scan/openpush_scan/skills; the public repository and installs have one copy.
ROOT = bundle.package_dir().parents[1]
PACKAGED = bundle.package_dir() / "skills" / "openpush-scan"
CANONICAL = ROOT / "skills" / "openpush-scan"
IN_MONOREPO = (CANONICAL / "SKILL.md").exists() and (PACKAGED / "SKILL.md").exists()
SKILL = bundle.skill_dir()


class SkillDocumentationTests(unittest.TestCase):
    def test_router_has_required_frontmatter_and_rules(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        for key in ("name:", "description:", "argument-hint:", "allowed-tools:"):
            self.assertIn(key, text)
        for command in ("scan", "review", "login", "workspace", "share", "suggest", "instrument", "document", "ci"):
            self.assertIn(f"`{command}", text)
        for agent in ("openpush-scanner", "openpush-program-reviewer", "openpush-instrumenter", "openpush-documenter"):
            self.assertIn(agent, text)
        self.assertIn("STOP", text)
        self.assertIn("`openpush-scan:openpush-scanner`", text)
        self.assertIn("`openpush_scanner`", text)
        self.assertIn("or the named agent is not installed", text)
        self.assertIn("⚠️ DEGRADED: single-context", text)
        self.assertIn("Never read", text)
        self.assertNotIn("--yes", text)

    def test_frontmatter_follows_the_agent_skills_spec(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        front = text[4:].split("\n---\n", 1)[0]
        keys = [line.split(":", 1)[0] for line in front.splitlines() if line and not line.startswith(" ")]
        fields = {line.split(":", 1)[0]: line.split(":", 1)[1].strip()
                  for line in front.splitlines() if line and not line.startswith(" ")}
        # Spec fields, plus argument-hint, which Claude Code and VS Code read and others ignore.
        self.assertLessEqual(set(keys), {"name", "description", "license", "compatibility",
                                         "metadata", "allowed-tools", "argument-hint"})
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(fields["name"], SKILL.name)
        self.assertRegex(fields["name"], r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertLessEqual(len(fields["name"]), 64)
        self.assertTrue(0 < len(fields["description"]) <= 1024)
        self.assertTrue(0 < len(fields["compatibility"]) <= 500)
        self.assertEqual(fields["allowed-tools"], "", "allowed-tools is a block list, not flow YAML")
        self.assertLess(len(text.splitlines()), 500)

    def test_local_routing_and_two_consent_stops(self):
        router = (SKILL / "SKILL.md").read_text()
        scan_route = next(line for line in router.splitlines() if line.startswith("| `scan"))
        self.assertNotIn("then `suggest`", scan_route)
        self.assertIn("Never automatically continue", scan_route)
        self.assertIn("reference/review.md", scan_route)
        self.assertIn("Scanner completion is not command completion", scan_route)
        self.assertIn("`openpush-scan scan .` is the only command the user needs to invoke", router)
        self.assertIn("Do you want to share this final selection with OpenPush?", router)
        self.assertIn("Do not send a final response containing only scan findings", router)
        self.assertIn("never request login, an API key, or an OpenPush connection", router)
        self.assertIn("does not authorize authentication or upload", router)
        self.assertIn("only when the user explicitly proceeds to `share`/upload", router)
        self.assertIn("effective emitted events", router)
        self.assertIn("scanner may edit only the local manifest's `events` array", router)
        self.assertIn("openpush-scan validate --manifest", router)
        review = (SKILL / "reference/review.md").read_text()
        local, upload = review.split("# Explicit share/upload")
        self.assertIn("**STOP**", local)
        self.assertNotIn("openpush_prepare_manifest", local)
        self.assertNotIn("OPENPUSH_API_KEY", local)
        self.assertIn("final upload-preview confirmation before `openpush_confirm_action`", upload)
        self.assertIn("Upload this reviewed manifest? [y/N]", upload)
        self.assertIn("without a code fence", local)
        self.assertIn("Do not expose a bare review prompt", local)
        self.assertIn("`save` or `looks good`", local)
        self.assertIn("Do you want to share this final selection with OpenPush?", local)
        for text in (router, review, (SKILL / "reference/suggest.md").read_text()):
            for location in ("chat", "commands", "files", "manifests", "profiles", "agent packets"):
                self.assertIn(location, text)

    def test_suggestions_require_previously_shared_evidence(self):
        text = (SKILL / "reference/suggest.md").read_text()
        self.assertIn("Use only a manifest the user has explicitly shared", text)
        self.assertIn("do not initiate authentication", text)
        self.assertIn("not newer unshared local findings", text)

    @unittest.skipUnless(IN_MONOREPO, "monorepo only: compares the two skill copies")
    def test_packaged_skill_is_byte_identical(self):
        packaged = PACKAGED
        canonical_files = {p.relative_to(SKILL) for p in SKILL.rglob("*") if p.is_file()}
        packaged_files = {p.relative_to(packaged) for p in packaged.rglob("*") if p.is_file()}
        self.assertEqual(canonical_files, packaged_files)
        for relative in canonical_files:
            with self.subTest(file=str(relative)):
                self.assertEqual((SKILL / relative).read_bytes(), (packaged / relative).read_bytes())

    def test_references_name_their_agent_and_packet_fields(self):
        expected = {
            "review.md": "openpush-scanner",
            "suggest.md": "openpush-program-reviewer",
            "instrument.md": "openpush-instrumenter",
            "document.md": "openpush-documenter",
            "ci.md": "workflow",
        }
        for filename, needle in expected.items():
            text = (SKILL / "reference" / filename).read_text(encoding="utf-8")
            self.assertIn(needle, text)

    def test_degraded_files_end_with_disclosure(self):
        for path in (SKILL / "degraded").glob("*.md"):
            self.assertTrue(path.read_text(encoding="utf-8").strip().endswith("⚠️ DEGRADED: single-context (no sub-agent tool exposed)"))

    @unittest.skipUnless(IN_MONOREPO, "monorepo only: checks <repo>/skills/README.md")
    def test_readme_names_installer(self):
        self.assertIn("openpush-scan install-skill", (ROOT / "skills" / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
