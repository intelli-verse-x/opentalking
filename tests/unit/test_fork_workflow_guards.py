"""Static publication boundary; never import executable frontend configs."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ForkWorkflowGuards(unittest.TestCase):
    def test_docs_writer_has_upstream_owner_guard_before_checkout(self):
        text = (ROOT / ".github/workflows/docs-pages.yml").read_text()
        job = text.split("  build-versioned-docs:\n", 1)[1].split("\n  deploy-pages:", 1)[0]
        condition = re.search(r"^    if: (.+)$", job, re.MULTILINE)
        self.assertIsNotNone(condition)
        self.assertEqual(condition.group(1),
                         "github.repository == 'datascale-ai/opentalking' && "
                         "(github.event_name == 'workflow_dispatch' || github.ref == 'refs/heads/main')")
        self.assertLess(condition.start(), job.index("    steps:"))
        # The writer is inside the guarded job, not an unguarded second job.
        self.assertIn("mike deploy --push", job)
        self.assertIn("mike set-default --push", job)

    def test_pr_validation_token_is_read_only_and_not_persisted(self):
        text = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertIn("permissions:\n  contents: read\n", text)
        self.assertNotIn("secrets.", text)
        checkouts = list(re.finditer(r"uses: actions/checkout@v6\n", text))
        self.assertEqual(len(checkouts), 4)
        for checkout in checkouts:
            self.assertTrue(text[checkout.end():].startswith(
                "        with:\n          persist-credentials: false\n"))


if __name__ == "__main__":
    unittest.main()
