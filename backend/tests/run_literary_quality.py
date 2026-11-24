"""Dependency-light runner for the deterministic literary regression suite."""
import argparse
import json
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

PATTERNS = (
    "test_fidelity_profile.py",
    "test_review_guard.py",
    "test_translation_resume.py",
    "test_output_quality.py",
    "test_translation_http_integration.py",
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    suite = unittest.TestSuite()
    for pattern in PATTERNS:
        suite.addTests(unittest.defaultTestLoader.discover(str(BACKEND / "tests"), pattern=pattern))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {
        "suite": "literary-deterministic-regression",
        "tests": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "passed": result.wasSuccessful(),
        "real_model_inference": "not_run",
        "http_transport": "loopback_fixture_server",
        "database": "temporary_sqlite",
        "semantic_fidelity_certified": False,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
