"""Financial-year money in and out for one daily ledger path, for plain-language reporting.

``household_flows`` splits each year's change in total wealth into money
arriving (take-home salary, super contributions), money leaving (spending,
tax) and investment returns. Its rows reconcile exactly with the ledger's
daily wealth identity. ``account_flows`` shows money moving into and out of
each investment account. Investment returns and super distributions
reinvested inside super are excluded there, because they are growth, not a
transfer.
"""

from datetime import date

import pandas as pd

from financial_simulations.rules.au.parameters import load_ruleset
from financial_simulations.rules.au.superannuation import access_date, birthday


HOUSEHOLD = (("salary", "Take-home salary", 1), ("employer_contributions", "Super contributions", 1),
             ("market_pnl", "Investment returns", 1), ("interest", "Interest on cash", 1), ("age_pension", "Age Pension", 1),
             ("spending_paid", "Spending", -1),
             ("tax_paid", "Income tax", -1), ("contributions_tax", "Contributions tax", -1),
             ("fund_tax", "Super fund tax", -1), ("division_296", "Division 296 tax", -1))


def financial_year_end(day) -> int:
    """The calendar year in which the 1 July to 30 June financial year containing ``day`` ends."""
    return day.year + (day.month >= 7)


def _financial_years(index: pd.DatetimeIndex) -> pd.Index:
    """``financial_year_end`` of every date in a daily index, computed for the whole index at once."""
    return index.year + (index.month >= 7)


def household_flows(daily: pd.DataFrame, inflation: bool = False) -> pd.DataFrame:
    """One row per financial year and flow; ``AUD`` is signed (in positive, out negative).

    ``Opening`` and ``Closing`` are total wealth before the year's first day and
    at its last; ``Net change`` equals the sum of the year's flows. For a frame
    in today's dollars (``real_daily``) pass ``inflation=True``: an
    ``Inflation`` flow then carries the buying power wealth lost in the year, so
    the flows still sum to the net change.
    """
    years = _financial_years(daily.index)
    rows = []
    for year, part in daily.groupby(years):
        position = daily.index.get_loc(part.index[0])
        opening = float(daily["total"].iloc[position - 1]) if position else float(part["total"].iloc[0] - _flows(part.iloc[:1]))
        closing = float(part["total"].iloc[-1])
        for column, label, sign in HOUSEHOLD:
            rows.append({"FY ending": int(year), "Flow": label, "AUD": sign * float(part[column].sum()) if column in part else 0.0,
                         "Opening": opening, "Closing": closing, "Net change": closing - opening,
                         "Days": len(part)})
        if inflation:
            rows.append({"FY ending": int(year), "Flow": "Inflation", "AUD": closing - opening - _flows(part),
                         "Opening": opening, "Closing": closing, "Net change": closing - opening, "Days": len(part)})
    return pd.DataFrame(rows)


def _flows(rows: pd.DataFrame) -> float:
    return float(sum(sign * rows[column].sum() for column, _, sign in HOUSEHOLD if column in rows))


def account_flows(daily: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Money into (+) and out of (−) outside investments, super accumulation and the pension, by financial year."""
    rows = []

    def add(day, account, label, amount):
        if abs(amount) > 1e-9:
            rows.append({"FY ending": financial_year_end(day), "Account": account, "Flow": label, "AUD": float(amount)})

    yearly = daily.groupby(_financial_years(daily.index)).sum(numeric_only=True)
    for year, values in yearly.iterrows():
        d = date(int(year), 6, 30)
        add(d, "Super (accumulation)", "Contributions after 15% tax", values["employer_contributions"] - values["contributions_tax"])
        add(d, "Super (accumulation)", "Fund tax", -values["fund_tax"])
        add(d, "Super (accumulation)", "Lump sums withdrawn", -values["lump_sums"])
        add(d, "Account-based pension", "Pension payments", -values["pension_payments"])
        if "division_296" in values:
            add(d, "Super (accumulation)", "Division 296 tax released", -values["division_296"])
    if not events.empty:
        purpose = events["purpose"] if "purpose" in events else pd.Series("", index=events.index)
        kind = events["event"]
        # Only these events are transfers; selecting them first avoids walking every event row by row.
        wanted = (((kind == "buy") & (events["account"] == "outside") & (purpose == "investment"))
                  | ((kind == "sale") & (purpose == "withdrawal"))
                  | kind.isin(("pension_commencement", "non_concessional_contribution")))
        chosen = events.loc[wanted]
        for when, event, amount in zip(chosen["date"], chosen["event"], chosen["amount"]):
            d = when if isinstance(when, date) else pd.Timestamp(when).date()
            if event == "buy":
                add(d, "Outside investments", "Savings invested", amount)
            elif event == "sale":
                add(d, "Outside investments", "Sold to pay spending or tax", -amount)
            elif event == "pension_commencement":
                add(d, "Super (accumulation)", "Moved to pension", -amount)
                add(d, "Account-based pension", "Moved from super", amount)
            else:
                add(d, "Super (accumulation)", "Non-concessional contributions", amount)
    frame = pd.DataFrame(rows, columns=["FY ending", "Account", "Flow", "AUD"])
    return frame.groupby(["FY ending", "Account", "Flow"], as_index=False)["AUD"].sum()


def milestones(plan, start, end):
    """Retirement, super access and pension start as dated markers, with their financial-year positions."""
    born = plan["person"]["date_of_birth"]
    retire = birthday(born, plan["person"]["retirement_age"])
    events = {retire: [f"Retire at {plan['person']['retirement_age']}"]}
    events.setdefault(access_date(born, load_ruleset("2026-27"), retire), []).append("Super accessible")
    if plan["pension"]["start_age"]:
        events.setdefault(max(start, birthday(born, int(plan["pension"]["start_age"]))), []).append("Pension starts")
    rows = []
    for i, (day, labels) in enumerate(sorted((d, l) for d, l in events.items() if start < d <= end)):
        fy_end = day.year + (day.month >= 7)
        fraction = (day - date(fy_end - 1, 7, 1)).days / 365.25
        rows.append({"Date": pd.Timestamp(day), "Event": " · ".join(labels), "FY ending": fy_end,
                     "Position": fy_end - 0.5 + fraction, "Offset": 10 + 15 * i})
    return pd.DataFrame(rows, columns=["Date", "Event", "FY ending", "Position", "Offset"])
