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
    compare = commands.add_parser("compare", help="Compare daily replay and joint bootstrap sensitivities.")
    compare.add_argument("experiment")
    compare.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "compare":
            from financial_simulations.comparison import load_comparison, run_comparison

            manifest = run_comparison(load_comparison(args.experiment), args.output)
            print(json.dumps({key: manifest[key] for key in ("model", "cases", "paths_evaluated", "trace_paths")}, indent=2))
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
