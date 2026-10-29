"""Run a plan into one consolidated output folder: output/plans/<plan-name>/."""

from dataclasses import dataclass
import json
from pathlib import Path

from financial_simulations.reporting.ledger import write_ledger_report
from financial_simulations.retirement.ledger import LedgerResult, run_ledger
from financial_simulations.retirement.plan import build_inputs, normalize_plan, plan_to_toml, slug
from financial_simulations.runner import code_manifest


DEFAULT_ROOT = Path("output") / "plans"


@dataclass(frozen=True)
class PlanRun:
    plan: dict
    result: LedgerResult
    notes: list
    folder: Path | None
    rules_manifest: dict


def run_plan(plan: dict, output_root: str | Path | None = DEFAULT_ROOT) -> PlanRun:
    """Validate, run and (unless ``output_root`` is None) write the plan's single output folder.

    The folder holds plan.toml (the exact inputs), daily.csv, events.csv,
    annual.json, ledger.png and manifest.json. A rerun replaces it.
    """
    plan = normalize_plan(plan)
    path, scenario, years, notes = build_inputs(plan)
    result = run_ledger(path, scenario, years)
    rules = {fy: r.manifest() for fy, r in years.items()}
    folder = None
    if output_root is not None:
        folder = Path(output_root) / slug(plan["plan"]["name"])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "plan.toml").write_text(plan_to_toml(plan), encoding="utf-8", newline="\n")
        manifest = {"plan": plan["plan"], "notes": notes, "rules": rules, "code": code_manifest(),
                    "market": "deterministic assumed AUD total returns per asset"}
        write_ledger_report(result, folder, plan["plan"]["name"], manifest)
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8", newline="\n")
    return PlanRun(plan, result, notes, folder, rules)
