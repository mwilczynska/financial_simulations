"""Command-line entry point for portable baseline scenarios."""

import argparse
import json

from financial_simulations.runner import run_scenario
from financial_simulations.scenario import load_scenario


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="financial-simulations")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run a daily deterministic historical baseline.")
    run.add_argument("scenario")
    run.add_argument("--output", required=True)
    run.add_argument("--parquet", action="store_true", help="Also write the daily ledger as Parquet.")
    reconcile = commands.add_parser("reconcile", help="Compare both accounting policies with the local optimiser.")
    reconcile.add_argument("scenario")
    reconcile.add_argument("--optimiser-root", required=True)
    reconcile.add_argument("--output", required=True)
    compare = commands.add_parser("compare", help="Compare daily generators, assumptions and optional target/risk evaluation.")
    compare.add_argument("experiment")
    compare.add_argument("--output", required=True)
    paired = commands.add_parser("paired", help="Compare portfolios on shared draws across generators and source windows.")
    paired.add_argument("study")
    paired.add_argument("--output", required=True)
    holdout = commands.add_parser("holdout", help="Score generators against realised rolling holdouts.")
    holdout.add_argument("study")
    holdout.add_argument("--output", required=True)
    plan = commands.add_parser("plan", help="Run a retirement plan file into output/plans/<plan-name>/.")
    plan.add_argument("plan_file")
    plan.add_argument("--output", default="output/plans", help="Parent folder for the plan's output folder.")
    ui = commands.add_parser("ui", help="Open the browser app for editing, importing, exporting and running plans.")
    ui.add_argument("--port", type=int, default=8501)
    args = parser.parse_args(argv)
    if args.command == "ui":
        import subprocess
        import sys
        from pathlib import Path

        app = Path(__file__).resolve().parent / "ui" / "app.py"
        return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app), "--server.port", str(args.port),
                                "--server.headless", "true", "--browser.gatherUsageStats", "false",
                                "--client.toolbarMode", "minimal"])
    try:
        if args.command in ("paired", "holdout"):
            from financial_simulations import studies

            if args.command == "paired":
                manifest = studies.run_paired(studies.load_paired(args.study), args.output)
                keys = ("model", "cases", "paths_evaluated")
            else:
                manifest = studies.run_holdout(studies.load_holdout(args.study), args.output)
                keys = ("model", "scored_folds", "incomplete_folds", "generated_paths")
            print(json.dumps({key: manifest[key] for key in keys}, indent=2))
            return 0
        if args.command == "compare":
            from financial_simulations.comparison import load_comparison, run_comparison

            manifest = run_comparison(load_comparison(args.experiment), args.output)
            print(json.dumps({key: manifest[key] for key in ("model", "cases", "paths_evaluated", "trace_paths")}, indent=2))
            return 0
        if args.command == "plan":
            from pathlib import Path

            from financial_simulations.retirement.plan import load_plan_text
            from financial_simulations.retirement.run_plan import run_plan

            file = Path(args.plan_file)
            run = run_plan(load_plan_text(file.read_text(encoding="utf-8"), file.name), args.output)
            final = run.result.annual[-1] if run.result.annual else None
            print(json.dumps({"folder": str(run.folder), "notes": run.notes, "years_assessed": len(run.result.annual),
                              "end_wealth": round(float(run.result.daily["total"].iloc[-1]), 2),
                              "total_shortfall": round(sum(a["shortfall"] for a in run.result.annual), 2),
                              "last_year": final["financial_year"] if final else None}, indent=2))
            return 0
        scenario = load_scenario(args.scenario)
        if args.command == "run":
            manifest = run_scenario(scenario, args.output, parquet=args.parquet)
            print(json.dumps(manifest["summary"], indent=2, allow_nan=False))
        else:
            from financial_simulations.validation import reconcile_optimiser

            print(json.dumps(reconcile_optimiser(scenario, args.optimiser_root, args.output), indent=2))
    except (ValueError, OSError, KeyError, ImportError) as exc:
        parser.exit(2, f"{parser.prog}: {exc}\n")
    return 0
