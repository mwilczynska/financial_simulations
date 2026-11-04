# ADR 0047: a compact retirement workspace and spending adequacy overview

Date: 2026-11-04.

Status: accepted; implemented. Validation is recorded in the methodology.

## Context and requirements

The user requested a coherent UI redesign, fewer and smaller plots, less setup
navigation and removal of the space consumed by the permanent sidebar. They
also asked to distinguish ruin from paths receiving Age Pension, and to see
average retirement spending for individual paths and path groups.

## Alternatives

- Restyle the existing five tabs and long results page: leaves the navigation
  and information hierarchy problems intact.
- Remove diagnostic charts: simplifies the page but loses useful audit tools.
- Show essentials together, then progressively disclose inputs and results:
  preserves control and auditability while reducing the initial workload.

## Decision

The app has just **Plan** and **Results** as primary tabs. The Plan screen shows
timing, income, spending and balances together. Detailed settings remain in
expanders, and file management moves to a header popover. A completed run
selects Results. The permanent sidebar is removed.

Results open with retirement adequacy: disjoint outcome groups, wealth bands
and average spending by group. Cash flow, risk and tax diagnostics, path
inspection, portfolio analysis and downloads have separate views. Compared
strategies retain their tabs and independent choices from ADR 0046. Only the
selected result view is rendered. Charts use a shared theme and role-specific
heights, generally 280–420 pixels, instead of 520–670 pixels. Large audit
tables have bounded height. Existing PNG outputs retain their data conventions;
new PNGs and CSVs use the same adequacy functions as the UI.

### Outcome classification

Supported paths belong to exactly one group, with shortfall taking priority:

1. Spending or tax shortfall: existing `Status == depleted`, including the
   existing terminal tax-liability check.
2. Funded with Age Pension: no shortfall, but any positive Age Pension receipt.
3. Funded without Age Pension: neither of the above.

Receipt is a user-requested warning signal, not a new definition of ruin and
not proof of counterfactual dependence. A small part-pension also qualifies.
The overview separately shows receipt in the final reported financial year,
which may be partial; it does not claim payment on the exact final date.

### Spending averages

For each path, average spending actually paid over complete retired financial
years, including zero-spending years. Exclude partial first and final years;
explicitly check the simulation start as well as the existing full-retired-year
flag. No eligible year means missing, not zero. Group averages give each
eligible path equal weight. Also show the median and 10th percentile of those
path averages and the eligible path count. Wealth-ranked groups follow the
existing explorer's floor/ceiling rank selection and may overlap outcome groups.

## Reasons and consequences

- **User requirements:** compact setup, no permanent sidebar, clear ruin and
  Age Pension outcomes, and average spending for paths and groups.
- **Engineering judgement:** progressive disclosure, chart sizing, colours and
  equal weighting of path averages. These are not sourced tax-policy changes.
- Daily return generation, ledger accounting, pension eligibility, tax rules,
  spending policies and wealth percentile calculations are unchanged.
- A favourable mean can conceal poor years. Spending cuts, annual ranges,
  shortfalls and individual ledgers remain available.
- The new group average supplements the existing group medians from ADR 0040;
  it does not replace their meanings. ADR 0046's retained strategy choices
  continue to apply across the new detail views.

## References and evidence

- User instructions in this task, 4 November 2026.
- [Planner methodology](../methodology/plan-and-app.md), including equations,
  examples, export names and validation evidence.
- `tests/test_adequacy.py`: independent arithmetic, shortfall/pension overlap,
  unsupported exclusion, partial years, zero years, empty cohorts and exports.
- `tests/test_plan.py`: full plan runs, two-tab navigation, view switching and
  per-strategy choice persistence.
