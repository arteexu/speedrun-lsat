#!/usr/bin/env python3
"""Unified Speedrun CLI with subcommands for dashboard, drill, export, etc.

Usage:
    python speedrun/tools/speedrun_cli.py dashboard --base ~/.ankidata
    python speedrun/tools/speedrun_cli.py drill --count 3
    python speedrun/tools/speedrun_cli.py export --out report.html
    python speedrun/tools/speedrun_cli.py coverage
    python speedrun/tools/speedrun_cli.py calibrate
    python speedrun/tools/speedrun_cli.py transfer-gap
    python speedrun/tools/speedrun_cli.py health
    python speedrun/tools/speedrun_cli.py leakage-check
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _open_col(args):
    from speedrun.tools.import_seed_deck import _open_collection

    return _open_collection(args)


def cmd_dashboard(args) -> int:
    col = _open_col(args)
    try:
        from speedrun.dashboard import render_dashboard_html

        print(render_dashboard_html(col))
    finally:
        col.close()
    return 0


def cmd_drill(args) -> int:
    from speedrun.tools.schema_drill import main as drill_main

    return drill_main(
        [
            *(["--col", args.col] if args.col else []),
            *(["--base", args.base] if args.base else []),
            *(["--count", str(args.count)] if args.count else []),
            "--limit",
            str(args.limit),
        ]
    )


def cmd_export(args) -> int:
    col = _open_col(args)
    try:
        from speedrun.export import export_html

        out = Path(args.out or "speedrun_export.html")
        export_html(col, out)
        print(f"Wrote {out.resolve()}")
    finally:
        col.close()
    return 0


def cmd_coverage(args) -> int:
    from speedrun.tools.coverage_map import main as cov_main

    return cov_main(["--json"] if args.json else [])


def cmd_calibrate(args) -> int:
    col = _open_col(args)
    try:
        from speedrun.eval.calibration import calibration_report

        report = calibration_report(col)
        if report.gave_up:
            print(f"Abstain: {report.reason}")
        else:
            print(f"Brier={report.brier:.3f} log_loss={report.log_loss:.3f} n={report.n_total}")
    finally:
        col.close()
    return 0


def cmd_transfer_gap(args) -> int:
    col = _open_col(args)
    try:
        from speedrun.eval.transfer_gap import transfer_gap_report

        report = transfer_gap_report(col)
        print(report.format_report())
    finally:
        col.close()
    return 0


def cmd_health(args) -> int:
    from speedrun.tools.health_check import main as health_main

    return health_main(
        [
            *(["--col", args.col] if args.col else []),
            *(["--base", args.base] if args.base else []),
        ]
    )


def cmd_gaps(args) -> int:
    col = _open_col(args)
    try:
        from speedrun.coverage_gap import coverage_gap_report
        from speedrun.coverage_gap import format_gap_report

        gaps = coverage_gap_report(col, top_n=args.top)
        print(format_gap_report(gaps))
    finally:
        col.close()
    return 0


def cmd_pretest(args) -> int:
    col = _open_col(args)
    try:
        from speedrun.pretest import render_pretest_results_html
        from speedrun.pretest import simulate_pretest_from_revlog

        session = simulate_pretest_from_revlog(col, block_size=args.block)
        score = session.performance or {}
        print(render_pretest_results_html(session, score))
    finally:
        col.close()
    return 0


def cmd_ai_eval(args) -> int:
    from speedrun.eval.ai_eval import format_report, run_ai_eval

    report = run_ai_eval()
    print(format_report(report))
    return 0 if report.passed else 1


def cmd_leakage_check(args) -> int:
    """Leakage check (spec 7e / §14.3): scan the training/seed data for held-out
    gold items (or near-copies). Exits non-zero when NOT clean — leaked test data
    zeroes the AI score, so this blocks a release."""
    from speedrun.eval.leakage_check import leakage_check

    report = leakage_check(threshold=args.threshold)
    print(
        f"Leakage check (threshold {report.threshold}): "
        f"{'CLEAN' if report.clean else 'LEAK'} — {report.reason}"
    )
    for hit in report.hits[: args.show]:
        print(
            f"  test {hit.test_id} ~ train {hit.train_id} "
            f"(jaccard {hit.jaccard:.2f}): {hit.shared_sample}"
        )
    return 0 if report.clean else 1


def cmd_grounding_eval(args) -> int:
    """Offline, deterministic pre-ship gate: grounded retrieval vs keyword/vector.
    Exits non-zero when the grounded method fails its cutoff (blocks a release)."""
    from speedrun.eval.grounding_eval import format_report, run_grounding_eval

    report = run_grounding_eval()
    print(format_report(report))
    return 0 if report.passed else 1


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--col", help="path to collection.anki2")
    ap.add_argument("--base", help="ANKI_BASE profile dir")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("dashboard", help="render three-score dashboard HTML").set_defaults(
        func=cmd_dashboard
    )

    drill = sub.add_parser("drill", help="weakest-schema drill queue")
    drill.add_argument("--count", type=int)
    drill.add_argument("--limit", type=int, default=25)
    drill.set_defaults(func=cmd_drill)

    exp = sub.add_parser("export", help="export offline HTML report")
    exp.add_argument("--out", help="output path")
    exp.set_defaults(func=cmd_export)

    cov = sub.add_parser("coverage", help="deck coverage map")
    cov.add_argument("--json", action="store_true")
    cov.set_defaults(func=cmd_coverage)

    sub.add_parser("calibrate", help="memory calibration report").set_defaults(
        func=cmd_calibrate
    )
    sub.add_parser("transfer-gap", help="recall vs transfer gap").set_defaults(
        func=cmd_transfer_gap
    )
    sub.add_parser("health", help="health check").set_defaults(func=cmd_health)
    sub.add_parser(
        "ai-eval", help="AI vs baseline eval on held-out gold set"
    ).set_defaults(func=cmd_ai_eval)
    sub.add_parser(
        "grounding-eval",
        help="offline grounded-vs-baseline pre-ship gate (deterministic)",
    ).set_defaults(func=cmd_grounding_eval)
    leak = sub.add_parser(
        "leakage-check",
        help="scan training/seed data for held-out gold leakage; non-zero if not clean",
    )
    leak.add_argument("--threshold", type=float, default=0.6,
                      help="gold/seed jaccard at/above this is flagged as a leak")
    leak.add_argument("--show", type=int, default=10, help="max leak rows to print")
    leak.set_defaults(func=cmd_leakage_check)

    gaps = sub.add_parser("gaps", help="coverage gap report from collection")
    gaps.add_argument("--top", type=int, default=20)
    gaps.set_defaults(func=cmd_gaps)

    pt = sub.add_parser("pretest", help="simulate pre-test from recent reviews")
    pt.add_argument("--block", type=int, default=10)
    pt.set_defaults(func=cmd_pretest)

    args = ap.parse_args(argv)
    if not args.col and not args.base and args.cmd not in (
        "coverage",
        "calibrate",
        "ai-eval",
        "grounding-eval",
        "leakage-check",
    ):
        ap.error("Pass --col or --base for this subcommand")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
