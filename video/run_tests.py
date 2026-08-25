#!/usr/bin/env python3
"""
run_tests.py
Unified Standalone Test Runner for Screen Recording & Capture Application.
Supports Tier-based filtering, Feature-based filtering, verbose reporting,
rich summary tables, JSON export, and POSIX exit codes.
"""

import sys
import os
import time
import argparse
import unittest
import json
from typing import List, Dict, Any, Optional

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ANSI Colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


class RichE2ETestResult(unittest.TestResult):
    """Custom TestResult collecting execution metrics, timing, and failure traces."""

    def __init__(self, verbose: bool = False):
        super().__init__()
        self.verbose = verbose
        self.records: List[Dict[str, Any]] = []
        self._test_start_time: Optional[float] = None

    def startTest(self, test: unittest.TestCase):
        super().startTest(test)
        self._test_start_time = time.monotonic()
        if self.verbose:
            sys.stdout.write(f"  RUN  {test.id()} ... ")
            sys.stdout.flush()

    def addSuccess(self, test: unittest.TestCase):
        super().addSuccess(test)
        elapsed = time.monotonic() - (self._test_start_time or time.monotonic())
        self.records.append({
            "id": test.id(),
            "status": "PASS",
            "duration": elapsed,
            "error": None,
        })
        if self.verbose:
            sys.stdout.write(f"{GREEN}PASS{RESET} ({elapsed*1000:.1f}ms)\n")
        else:
            sys.stdout.write(f"{GREEN}.{RESET}")
            sys.stdout.flush()

    def addFailure(self, test: unittest.TestCase, err):
        super().addFailure(test, err)
        elapsed = time.monotonic() - (self._test_start_time or time.monotonic())
        trace = self._exc_info_to_string(err, test)
        self.records.append({
            "id": test.id(),
            "status": "FAIL",
            "duration": elapsed,
            "error": trace,
        })
        if self.verbose:
            sys.stdout.write(f"{RED}FAIL{RESET} ({elapsed*1000:.1f}ms)\n")
        else:
            sys.stdout.write(f"{RED}F{RESET}")
            sys.stdout.flush()

    def addError(self, test: unittest.TestCase, err):
        super().addError(test, err)
        elapsed = time.monotonic() - (self._test_start_time or time.monotonic())
        trace = self._exc_info_to_string(err, test)
        self.records.append({
            "id": test.id(),
            "status": "ERROR",
            "duration": elapsed,
            "error": trace,
        })
        if self.verbose:
            sys.stdout.write(f"{RED}ERROR{RESET} ({elapsed*1000:.1f}ms)\n")
        else:
            sys.stdout.write(f"{RED}E{RESET}")
            sys.stdout.flush()

    def addSkip(self, test: unittest.TestCase, reason: str):
        super().addSkip(test, reason)
        elapsed = time.monotonic() - (self._test_start_time or time.monotonic())
        self.records.append({
            "id": test.id(),
            "status": "SKIP",
            "duration": elapsed,
            "error": reason,
        })
        if self.verbose:
            sys.stdout.write(f"{YELLOW}SKIP{RESET} ({reason})\n")
        else:
            sys.stdout.write(f"{YELLOW}S{RESET}")
            sys.stdout.flush()


def collect_tests(
    tier: Optional[str] = None,
    feature: Optional[str] = None,
    keyword: Optional[str] = None,
) -> unittest.TestSuite:
    """Discovers and filters test suites based on user-supplied options."""
    loader = unittest.defaultTestLoader
    tests_dir = os.path.join(PROJECT_ROOT, "tests")
    discovered = loader.discover(start_dir=tests_dir, pattern="test_*.py", top_level_dir=PROJECT_ROOT)

    filtered_suite = unittest.TestSuite()

    def _filter_suite(suite):
        for item in suite:
            if isinstance(item, unittest.TestSuite):
                _filter_suite(item)
            elif isinstance(item, unittest.TestCase):
                test_id = item.id()

                # Tier filter
                if tier and tier.lower() != "all":
                    tier_tag = f"tier{tier}_"
                    if tier_tag not in test_id.lower():
                        continue

                # Feature filter (e.g. F1, F6, f14, b01)
                if feature:
                    feat_num = feature.lower().lstrip("fb0")
                    # Match f01, f1, b01, b1, etc.
                    f_tag1 = f"f{feat_num.zfill(2)}"
                    f_tag2 = f"f{feat_num}"
                    b_tag1 = f"b{feat_num.zfill(2)}"
                    b_tag2 = f"b{feat_num}"
                    if not any(tag in test_id.lower() for tag in (f_tag1, f_tag2, b_tag1, b_tag2, feature.lower())):
                        continue

                # Keyword filter
                if keyword and keyword.lower() not in test_id.lower():
                    continue

                filtered_suite.addTest(item)

    _filter_suite(discovered)
    return filtered_suite


def print_summary_table(records: List[Dict[str, Any]], total_elapsed: float) -> None:
    """Renders a structured summary table breaking down metrics by Tier and Status."""
    tier_stats: Dict[str, Dict[str, int]] = {
        "Tier 1: Feature Coverage": {"total": 0, "pass": 0, "fail": 0, "error": 0, "skip": 0},
        "Tier 2: Boundary Cases": {"total": 0, "pass": 0, "fail": 0, "error": 0, "skip": 0},
        "Tier 3: Combinations": {"total": 0, "pass": 0, "fail": 0, "error": 0, "skip": 0},
        "Tier 4: Scenarios": {"total": 0, "pass": 0, "fail": 0, "error": 0, "skip": 0},
        "Other / Unit Tests": {"total": 0, "pass": 0, "fail": 0, "error": 0, "skip": 0},
    }

    for r in records:
        test_id = r["id"]
        status = r["status"]
        if "tier1_" in test_id:
            cat = "Tier 1: Feature Coverage"
        elif "tier2_" in test_id:
            cat = "Tier 2: Boundary Cases"
        elif "tier3_" in test_id:
            cat = "Tier 3: Combinations"
        elif "tier4_" in test_id:
            cat = "Tier 4: Scenarios"
        else:
            cat = "Other / Unit Tests"

        tier_stats[cat]["total"] += 1
        if status == "PASS":
            tier_stats[cat]["pass"] += 1
        elif status == "FAIL":
            tier_stats[cat]["fail"] += 1
        elif status == "ERROR":
            tier_stats[cat]["error"] += 1
        elif status == "SKIP":
            tier_stats[cat]["skip"] += 1

    print("\n" + "=" * 80)
    print(f"{BOLD}E2E TEST EXECUTION SUMMARY REPORT{RESET}")
    print("=" * 80)
    print(f"{'Test Suite / Tier':<30} | {'Total':>6} | {'Pass':>6} | {'Fail':>6} | {'Error':>6} | {'Skip':>6} | {'Pass %':>7}")
    print("-" * 80)

    total_tests = total_pass = total_fail = total_error = total_skip = 0
    for cat, s in tier_stats.items():
        if s["total"] == 0:
            continue
        total_tests += s["total"]
        total_pass += s["pass"]
        total_fail += s["fail"]
        total_error += s["error"]
        total_skip += s["skip"]
        rate = (s["pass"] / s["total"] * 100.0) if s["total"] > 0 else 0.0
        print(f"{cat:<30} | {s['total']:>6} | {s['pass']:>6} | {s['fail']:>6} | {s['error']:>6} | {s['skip']:>6} | {rate:>6.1f}%")

    print("-" * 80)
    total_rate = (total_pass / total_tests * 100.0) if total_tests > 0 else 0.0
    print(f"{BOLD}{'TOTAL':<30} | {total_tests:>6} | {total_pass:>6} | {total_fail:>6} | {total_error:>6} | {total_skip:>6} | {total_rate:>6.1f}%{RESET}")
    print("=" * 80)
    print(f"Total Execution Time: {total_elapsed:.3f}s\n")


def main():
    parser = argparse.ArgumentParser(description="Unified Standalone Test Runner for E2E Test Suite")
    parser.add_argument("--tier", type=str, default="all", help="Select tier (1, 2, 3, 4, 5, or all)")
    parser.add_argument("--feature", type=str, default=None, help="Filter by feature (e.g. F1..F14)")
    parser.add_argument("-k", "--keyword", type=str, default=None, help="Filter test names by substring")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose test execution output")
    parser.add_argument("--failfast", action="store_true", help="Stop execution on first failure")
    parser.add_argument("--json", type=str, default=None, help="Export results to JSON report file")

    args = parser.parse_args()

    suite = collect_tests(tier=args.tier, feature=args.feature, keyword=args.keyword)
    test_count = suite.countTestCases()

    print(f"{BOLD}Starting E2E Test Suite Execution ({test_count} tests discovered)...{RESET}")
    if not args.verbose:
        print("Progress: ", end="", flush=True)

    result = RichE2ETestResult(verbose=args.verbose)
    result.failfast = args.failfast

    start_time = time.monotonic()
    suite.run(result)
    total_elapsed = time.monotonic() - start_time

    if not args.verbose:
        print()

    print_summary_table(result.records, total_elapsed)

    # Print failures and errors
    if result.failures or result.errors:
        print(f"\n{BOLD}{RED}FAILED TESTS & TRACES:{RESET}")
        for r in result.records:
            if r["status"] in ("FAIL", "ERROR"):
                print("-" * 80)
                print(f"{BOLD}{r['id']} [{r['status']}]{RESET}")
                print(r["error"])

    # Export JSON report if requested
    if args.json:
        report_data = {
            "total_tests": test_count,
            "duration_sec": total_elapsed,
            "passed": len([r for r in result.records if r["status"] == "PASS"]),
            "failed": len(result.failures),
            "errors": len(result.errors),
            "skipped": len(result.skipped),
            "tests": result.records,
        }
        with open(args.json, "w") as f:
            json.dump(report_data, f, indent=2)
        print(f"JSON test report saved to: {args.json}")

    # Return exit code: 0 on success, 1 on failure/error
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
