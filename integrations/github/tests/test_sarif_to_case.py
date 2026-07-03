"""Tests for SARIF → case conversion."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from integrations.github.sarif_to_case import (  # noqa: E402
    build_case_from_result,
    parse_sarif_document,
    sarif_result_to_alert,
)
from integrations.github.snippet_extract import normalize_repo_uri, primary_file_from_alert  # noqa: E402


FIXTURE = Path(__file__).parent / "fixtures" / "minimal.sarif"


class SarifToCaseTests(unittest.TestCase):
    def test_normalize_uri(self) -> None:
        self.assertEqual(normalize_repo_uri("%SRCROOT%/src/Foo.java"), "src/Foo.java")

    def test_minimal_sarif_parses(self) -> None:
        sarif = json.loads(FIXTURE.read_text(encoding="utf-8"))
        results = parse_sarif_document(sarif)
        self.assertEqual(len(results), 1)
        alert = sarif_result_to_alert(results[0])
        self.assertEqual(alert["ruleId"], "java/xss")
        self.assertEqual(primary_file_from_alert(alert), "src/main/App.java")

    def test_build_case_from_benchmark_corpus(self) -> None:
        corpus = ROOT / "benchmark/corpora/phase2_fp_test/OWASP_BenchmarkTest01125.json"
        if not corpus.is_file():
            self.skipTest("benchmark corpus not available")
        case = json.loads(corpus.read_text(encoding="utf-8"))
        alert = case["raw_output"]["CodeQL"][0]
        bench_java = ROOT.parent / "BenchmarkJava"
        if not bench_java.is_dir():
            self.skipTest("BenchmarkJava clone not available")
        built = build_case_from_result(
            alert,
            repo_root=bench_java,
            owner="owasp",
            repo="benchmark",
            attach_snippets=True,
        )
        self.assertTrue(built.get("code_snippets"))
        files = {s["file"] for s in built["code_snippets"]}
        self.assertIn(built["file"], files)


if __name__ == "__main__":
    unittest.main()
