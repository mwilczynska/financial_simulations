"""Later income years derived from the verified 2026-27 rule set with declared treatments.

Each parameter is one of:

* **Enacted.** Legislated changes (the 14% first rate, the Working Australians
  Tax Offset, the CGT reform's minimum tax) and amounts the law does not
  index (personal thresholds, LITO, Division 293, $500,000 carry-forward
  test).
* **Projected.** Statutorily indexed amounts, indexed with the assumed CPI or
  wage growth and rounded down to the statutory increment.
* **Assumption.** Amounts set by legislation each year (Medicare low-income
  thresholds, including the SAPTO thresholds), frozen at the latest value.
  Also the assumed index rates and the Working Australians amount.

Age Pension amounts (single): the maximum basic rate grows with assumed wage
growth, standing in for the MTAWE benchmark that has usually set increases
since 2009. The pension supplement grows with CPI. The energy supplement is
held at its current amount. Assets-test limits, the income-test free area and
deeming thresholds grow with CPI each 1 July and are rounded to the published
increments ($250, $2 and $200). Deeming rates, set by the Minister, and the
Work Bonus are held at current values. SAPTO amounts are set by regulation
and are frozen.

Indexation compounds an unrounded tracked amount from the 2026-27 published
value. The law indexes from base amounts with actual index ratios, so a
projected cap can lag the true value by up to one increment.
"""

from dataclasses import dataclass
from math import floor, isfinite

from financial_simulations.rules.au.parameters import Parameter, RuleSet


SOURCES = {
    "act-2026-49-wato": {"id": "act-2026-49-wato", "title": "Act No. 49, 2026, Schedule 3: Working Australians Tax Offset (s61-155, s61-160)",
                         "url": "https://www.legislation.gov.au/C2026A00049/asmade/2026-06-26/text/original/epub/OEBPS/document_1/document_1.html"},
    "act-2026-49-min-tax": {"id": "act-2026-49-min-tax", "title": "Act No. 49, 2026, Schedule 1 Part 2: Division 119 minimum tax on capital gains",
                            "url": "https://www.legislation.gov.au/C2026A00049/asmade/2026-06-26/text/original/epub/OEBPS/document_1/document_1.html"},
    "itaa97-960-275": {"id": "itaa97-960-275", "title": "ITAA 1997 s960-275 indexation factor (consolidated)",
                       "url": "https://www.austlii.edu.au/cgi-bin/viewdoc/au/legis/cth/consol_act/itaa1997240/s960.275.html"},
    "project-assumption": {"id": "project-assumption", "title": "Project assumption declared in the projection inputs", "url": "https://github.com/mwilczynska/financial_simulations/blob/main/docs/rules/au-projection.md"},
}


@dataclass(frozen=True)
class ProjectionAssumptions:
    """Assumed annual index growth for statutory indexation, and the Working Australians amount."""

    cpi_annual: float
    wage_growth_annual: float
    wato_amount: float = 250.0

    def __post_init__(self):
        for name in ("cpi_annual", "wage_growth_annual"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or not -0.5 < value < 0.5:
                raise ValueError(f"{name} must be a finite annual rate between -50% and 50%.")
        if not 0 <= self.wato_amount <= 250:
            raise ValueError("The Working Australians Tax Offset is the lesser of $250 and a ministerial amount.")


def _round_down(value, step):
    return float(floor(value / step + 1e-9) * step)


def project_rulesets(base: RuleSet, through: str, assumptions: ProjectionAssumptions) -> dict:
    """Rule sets from ``base`` through financial year ``through`` (inclusive), keyed by label."""
    first, last = int(base.financial_year[:4]), int(through[:4])
    if last < first:
        raise ValueError("Projection must end at or after the base year.")
    rulesets = {base.financial_year: base}
    tracked = {"concessional_cap": float(base["concessional_cap"]), "transfer_balance_cap": float(base["transfer_balance_cap"]),
               "mls": [float(v) for v in base["mls_single_thresholds"]],
               "large": float(base["division_296"]["large_balance"]), "very_large": float(base["division_296"]["very_large_balance"]),
               "basic": float(base["age_pension_rate"]["basic"]), "supplement": float(base["age_pension_rate"]["supplement"]),
               "supplement_taxable": float(base["age_pension_rate"]["supplement_taxable"]),
               "homeowner": float(base["age_pension_assets_test"]["homeowner"]),
               "non_homeowner": float(base["age_pension_assets_test"]["non_homeowner"]),
               "free_area": float(base["age_pension_income_test"]["free_area"]),
               "deeming_threshold": float(base["deeming"]["threshold"])}
    previous = base
    wage, cpi = 1 + assumptions.wage_growth_annual, 1 + assumptions.cpi_annual
    for year in range(first + 1, last + 1):
        label = f"{year}-{(year + 1) % 100:02d}"
        tracked["concessional_cap"] *= wage
        tracked["transfer_balance_cap"] *= cpi
        tracked["mls"] = [v * wage for v in tracked["mls"]]
        tracked["large"] *= cpi
        tracked["very_large"] *= cpi
        tracked["basic"] *= wage
        for name in ("supplement", "supplement_taxable", "homeowner", "non_homeowner", "free_area", "deeming_threshold"):
            tracked[name] *= cpi
        cc = _round_down(tracked["concessional_cap"], 2500)
        tbc = _round_down(tracked["transfer_balance_cap"], 100000)
        ncc = 4 * cc
        projected = lambda name, value, why, units="": Parameter(name, value, "projected", "project-assumption", why, units)
        division = dict(previous["division_296"], large_balance=_round_down(tracked["large"], 150000),
                        very_large_balance=_round_down(tracked["very_large"], 500000))
        nearest = lambda value, step: round(float(round(value / step) * step), 2)
        pension_rate = dict(previous["age_pension_rate"], basic=nearest(tracked["basic"], 0.1),
                            supplement=nearest(tracked["supplement"], 0.1),
                            supplement_taxable=nearest(tracked["supplement_taxable"], 0.1))
        assets_test = dict(previous["age_pension_assets_test"], homeowner=nearest(tracked["homeowner"], 250),
                           non_homeowner=nearest(tracked["non_homeowner"], 250))
        income_test = dict(previous["age_pension_income_test"], free_area=nearest(tracked["free_area"], 2))
        deeming = dict(previous["deeming"], threshold=nearest(tracked["deeming_threshold"], 200))
        changes = {
            "resident_tax_rates": Parameter("resident_tax_rates", [0.14, 0.30, 0.37, 0.45], "enacted", "act-2025-28",
                                            "First marginal rate 14% from 2027-28 (Act No. 28, 2025)."),
            "wato": Parameter("wato", {"amount": assumptions.wato_amount, "net_labour_income_above": 18200}, "assumption",
                              "act-2026-49-wato", "Enacted from 2027-28 as the lesser of $250 and a ministerial amount; the amount is assumed."),
            "minimum_capital_gains_rate": Parameter("minimum_capital_gains_rate", 0.30, "enacted", "act-2026-49-min-tax",
                                                    "Division 119 minimum tax on post-reform capital gains."),
            "assumed_cpi_annual": Parameter("assumed_cpi_annual", assumptions.cpi_annual, "assumption", "project-assumption",
                                            "Australian CPI growth used for cost-base indexation and CPI-indexed thresholds."),
            "assumed_wage_growth_annual": Parameter("assumed_wage_growth_annual", assumptions.wage_growth_annual, "assumption",
                                                    "project-assumption", "AWOTE growth used for wage-indexed caps and thresholds."),
            "concessional_cap": projected("concessional_cap", cc, "AWOTE-indexed, rounded down to $2,500."),
            "non_concessional_cap": projected("non_concessional_cap", ncc, "Four times the concessional cap."),
            "maximum_contribution_base": projected("maximum_contribution_base", _round_down(cc * 100 / (100 * base["super_guarantee_rate"]), 10),
                                                   "Concessional cap x 100 / SG percentage, rounded down to $10."),
            "transfer_balance_cap": projected("transfer_balance_cap", tbc, "CPI-indexed, rounded down to $100,000."),
            "bring_forward": projected("bring_forward", {"age_limit": 75, "three_year_below": tbc - 2 * ncc, "two_year_below": tbc - ncc},
                                       "Transfer balance cap less two or one years of the non-concessional cap."),
            "mls_single_thresholds": projected("mls_single_thresholds", [_round_down(v, 1000) for v in tracked["mls"]],
                                               "AWOTE-indexed, rounded down to $1,000."),
            "division_296": projected("division_296", division, "CPI-indexed in $150,000 and $500,000 increments."),
            "medicare_low_income_lower": Parameter("medicare_low_income_lower", previous["medicare_low_income_lower"], "assumption",
                                                   "ato-medicare-low-income", "Set by legislation each year; frozen at the latest value."),
            "medicare_low_income_upper": Parameter("medicare_low_income_upper", previous["medicare_low_income_upper"], "assumption",
                                                   "ato-medicare-low-income", "Set by legislation each year; frozen at the latest value."),
            "age_pension_rate": projected("age_pension_rate", pension_rate,
                                          "Basic rate grown with assumed wage growth (MTAWE benchmark); pension supplement "
                                          "with CPI; energy supplement held. Rounded to 10 cents a fortnight.", "AUD a fortnight; single"),
            "age_pension_assets_test": projected("age_pension_assets_test", assets_test,
                                                 "CPI-indexed each 1 July, rounded to $250; taper unchanged."),
            "age_pension_income_test": projected("age_pension_income_test", income_test,
                                                 "Free area CPI-indexed, rounded to $2 a fortnight; taper and Work Bonus unchanged."),
            "deeming": projected("deeming", deeming, "Threshold CPI-indexed, rounded to $200; deeming rates held at current values."),
            "division_296_cgt_factor": Parameter("division_296_cgt_factor", {2027: 0.4, 2028: 0.6, 2029: 0.8}.get(year, 1.0),
                                                 "enacted", "ato-div296-apra",
                                                 "Prescribed Division 296 CGT factor: 0.4, 0.6, 0.8 to 2029-30, then 1.0."),
        }
        previous = previous.derive(label, changes, SOURCES)
        rulesets[label] = previous
    return rulesets
