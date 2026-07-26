from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER = REPO_ROOT / "scripts" / "check_doc_contract.py"


class DocumentationContractTest(unittest.TestCase):
    def run_checker(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHECKER), "--root", str(root)],
            capture_output=True,
            check=False,
            text=True,
        )

    def test_repository_documentation_contract_passes(self) -> None:
        result = self.run_checker(REPO_ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("documentation contract: PASS", result.stdout)

    def test_readme_cannot_grow_a_parallel_quickstart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("# Project\n\n```bash\ndocker compose up\n```\n")
            (root / "SPEC.md").write_text(
                "## 0. Documentation contract\n"
                "## 11. Build prerequisites and operator inputs\n"
                "## 12. Executable implementation plan\n"
            )
            result = self.run_checker(root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("README.md contains forbidden normative token", result.stdout)

    def test_missing_local_markdown_link_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("[missing](does-not-exist.md)\n")
            (root / "SPEC.md").write_text(
                "## 0. Documentation contract\n"
                "## 11. Build prerequisites and operator inputs\n"
                "## 12. Executable implementation plan\n"
            )
            result = self.run_checker(root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing local link target", result.stdout)


if __name__ == "__main__":
    unittest.main()
