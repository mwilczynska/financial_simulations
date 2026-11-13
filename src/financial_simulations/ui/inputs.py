"""The Plan page: every input, in four tabs. Each widget writes straight into the plan dictionary in session state."""

import calendar
from datetime import date
import os

import streamlit as st

from financial_simulations.data.plan_markets import CUSTOM_TICKERS, TICKERS
from financial_simulations.retirement.paths import CPU_HEADROOM, automatic_workers
from financial_simulations.retirement.ledger import Mortgage
from financial_simulations.retirement.plan import RENT_KEPT, sacrifice_per_year
from financial_simulations.rules.au.parameters import load_ruleset
from financial_simulations.rules.au.tax import IncomeYear, assess
from financial_simulations.ui.state import cached_market, calculation_cores, key
from financial_simulations.ui.theme import card, explain


MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
REBALANCE_LABELS = {"annual": "Rebalance every January", "none": "Buy and hold (weights drift)"}
RULE_LABELS = {"fixed": "Fixed: the same buying power every year (default)", "guyton_klinger": "Guyton–Klinger guardrails",
               "vanguard": "Vanguard ceiling and floor", "percent": "A percentage of wealth each year"}
START_LABELS = {"same": "The same as now", "amount": "A different amount", "percent": "A percentage of wealth at retirement"}


def percent(label, value, name, *, low=-50.0, high=50.0, step=0.1, help=None):
    return st.number_input(label, float(low), float(high), round(float(value) * 100, 4), float(step), key=key(name),
                           format="%.2f", help=help) / 100


def money(label, value, name, help=None):
    return float(st.number_input(label, 0.0, 1e9, float(value), 1000.0, key=key(name), format="%.0f", help=help))


def date_fields(label, current, name, first_year, last_year):
    """Year, month and day fields: typing a year is quicker than paging a calendar back decades."""
    st.markdown(f"**{label}**")
    y, m, d = st.columns([1, 1.6, 0.9])
    year = int(y.number_input("Year", first_year, last_year, min(max(current.year, first_year), last_year), 1,
                              key=key(f"{name}_year")))
    month = MONTHS.index(m.selectbox("Month", MONTHS, index=current.month - 1, key=key(f"{name}_month"))) + 1
    last = calendar.monthrange(year, month)[1]
    day = int(d.number_input("Day", 1, last, min(current.day, last), 1, key=key(f"{name}_day")))
    return date(year, month, day).isoformat()


def weights_editor(current, assets, name):
    weights = {}
    columns = st.columns(2)
    for i, asset in enumerate(assets):
        with columns[i % 2]:
            weights[asset] = st.number_input(f"{asset} %", 0.0, 100.0, round(current.get(asset, 0.0) * 100, 4), 5.0,
                                             key=key(f"{name}_{asset}"), format="%.1f") / 100
    total = sum(weights.values())
    if abs(total - 1) > 1e-6:
        st.warning(f"These weights total {total:.1%}; adjust them to 100%.")
    else:
        st.caption("Weights total 100%. The balance today and future purchases use this mix.")
    return {a: w for a, w in weights.items() if w > 0}


def rebalance_choice(current, name, help):
    return st.radio("Rebalancing", list(REBALANCE_LABELS), index=list(REBALANCE_LABELS).index(current), horizontal=True,
                    format_func=REBALANCE_LABELS.get, key=key(name), help=help)


def inputs_you(plan):
    person, employment = plan["person"], plan["employment"]
    left, right = st.columns([1.15, 1], gap="medium")
    with left:
        with card("you"):
            st.subheader("About you")
            person["date_of_birth"] = date_fields("Date of birth", date.fromisoformat(person["date_of_birth"]), "born", 1930, 2010)
            a, b = st.columns(2)
            person["retirement_age"] = int(a.number_input("Planned retirement age", 18, 80, int(person["retirement_age"]), 1,
                                                          key=key("retire"), help="Salary stops on this birthday."))
            with b:
                st.markdown("&nbsp;")
                person["private_hospital_cover"] = st.checkbox(
                    "Private hospital cover", person["private_hospital_cover"], key=key("cover"),
                    help="Cover avoids the Medicare levy surcharge.")
        with card("work"):
            st.subheader("Work")
            employment["annual_salary"] = money("Gross annual salary (AUD, excluding super)", employment["annual_salary"], "salary",
                                                help="Paid fortnightly until retirement. This is this year's salary.")
            employment["salary_indexed"] = st.checkbox(
                f"Salary rises each year with wage growth ({plan['assumptions']['wage_growth_annual']:.1%})",
                employment.get("salary_indexed", True), key=key("salary_indexed"),
                help="Each 1 July salary and salary sacrifice rise by the wage-growth assumption (Assumptions tab). "
                     "Untick to keep salary the same dollar amount every year, which means a real pay cut each year.")
            mode = st.radio("Salary sacrifice to super, on top of the 12% super guarantee", ["% of salary", "Dollars per year"],
                            index=0 if employment["salary_sacrifice_per_year"] == 0 else 1, horizontal=True,
                            key=key("sacrifice_mode"))
            if mode == "% of salary":
                employment["salary_sacrifice_percent"] = percent("Salary sacrifice % of salary",
                                                                 employment["salary_sacrifice_percent"], "sacrifice_pct",
                                                                 low=0, high=100, step=0.5)
                employment["salary_sacrifice_per_year"] = 0.0
            else:
                employment["salary_sacrifice_per_year"] = money("Salary sacrifice per year",
                                                                employment["salary_sacrifice_per_year"], "sacrifice")
                employment["salary_sacrifice_percent"] = 0.0
    with right:
        with card("pay"):
            work_summary(plan)
        with card("mortgage"):
            home_inputs(plan)
        with card("investment_property"):
            property_inputs(plan)


def home_inputs(plan):
    """The home you live in: whether you own it, its value and running costs (ADR 0055) and its loan (ADR 0052), or
    the rent you pay."""
    st.subheader("Your home")
    person, house = plan["person"], plan["home"]
    person["homeowner"] = st.checkbox(
        "I own the home I live in", person["homeowner"], key=key("homeowner"),
        help="Only the home you live in, not a property you rent out (that goes in the Investment property card). Your "
             "home is exempt from the Age Pension assets test, and homeowners have a lower assets limit ($333,000 "
             "instead of $600,000 for a full pension).")
    if not person["homeowner"]:
        person["weekly_rent"] = float(st.number_input(
            "Rent you pay where you live, weekly (0 = none)", 0.0, 1e5, float(person["weekly_rent"]), 10.0,
            key=key("rent_paid"), format="%.0f",
            help="Paid monthly before spending and rising with CPI, so a spending rule never cuts it. Leave it out of "
                 "spending. It stops if you move into your investment property."))
        plan["mortgage"]["balance"], house["value"] = 0.0, 0.0
        st.caption("Rent Assistance is not modelled.")
        return
    person["weekly_rent"] = 0.0
    house["value"] = money("Home value today (0 = not modelled)", house["value"], "home_value",
                           help="Optional. With a value, the home's running costs are paid separately from spending and "
                                "grow with its value; take rates, insurance and repairs out of spending. The home is not "
                                "counted in total wealth or the Age Pension assets test.")
    if house["value"] > 0:
        with st.expander("More: running costs and growth"):
            c, d = st.columns(2)
            with c:
                house["running_costs"] = percent("Running costs, % of value a year", house["running_costs"],
                                                 "home_costs", low=0, high=10, step=0.1,
                                                 help="Repairs, council rates and insurance. Paid monthly, before "
                                                      "spending.")
            with d:
                house["growth"] = percent("Value growth, % a year", house["growth"], "home_growth", low=-10, high=20,
                                          help="Applied monthly, the same on every market path.")
        st.caption(f"Running costs about {dollars(house['running_costs'] * house['value'], escape=True)} in the first "
                   "year, paid before spending. Take them out of spending.")
    loan = plan["mortgage"]
    loan["balance"] = money("Loan on your home, still owed today (0 = none)", loan["balance"], "mortgage_balance",
                            help="The balance owing on the loan for the home you live in, from your latest statement. A "
                                 "loan on a property you rent out goes in the Investment property card instead. Leave "
                                 "your repayments out of spending: the planner pays them separately.")
    if loan["balance"] <= 0:
        st.caption("No home loan.")
        return
    a, b = st.columns(2)
    with a:
        loan["interest_rate"] = percent("Interest rate, % a year", loan["interest_rate"], "mortgage_rate", low=0, high=30,
                                        step=0.05, help="Fixed for the whole run. Interest is worked out daily and "
                                                        "charged monthly, as Australian lenders do.")
    loan["years"] = float(b.number_input("Years left on the loan", 0.5, 40.0, float(loan["years"]), 0.5,
                                         key=key("mortgage_years"),
                                         help="Sets the required repayment: the fortnightly amount that clears the "
                                              "balance in this many years."))
    share = st.slider("Of the money you would invest, % paid off the loan instead", 0, 100,
                      int(round(loan["extra_share"] * 100)), 5, key=key("mortgage_extra"),
                      help="0 pays only the required repayments and invests the rest. 100 puts every spare dollar into "
                           "the loan until it is gone, then invests. In between splits each dollar.")
    loan["extra_share"] = share / 100
    rate, n = loan["interest_rate"] / 26, max(1, round(loan["years"] * 26))
    repayment = loan["balance"] / n if rate == 0 else loan["balance"] * rate / (1 - (1 + rate) ** -n)
    st.metric("Required repayment", f"${repayment:,.0f} a fortnight", help=f"${repayment * 26:,.0f} a year, fixed in "
              "dollars until the loan is repaid. It comes before spending and saving.")
    explain("Each fortnight on payday the required repayment is paid from cash (or, if cash runs short, from sales of "
            "outside investments and then accessible super; anything still unpaid is a shortfall and stays on the "
            "loan). Then your chosen share of whatever would be invested goes off the loan instead. Extra repayments can "
            "be redrawn: when cash runs short for spending or tax, they are drawn back before any investments are "
            "sold. Total wealth is shown net of the loan. Interest is not tax deductible, and the loan does not reduce assets for the Age "
            "Pension, because your home is not counted either.", "How the home loan is modelled")


def dollars(amount, escape=False):
    """Whole dollars with a true minus sign; ``escape`` for Markdown, where a bare $ starts maths."""
    sign = "−" if amount < -0.5 else ""
    return f"{sign}{'\\$' if escape else '$'}{abs(amount):,.0f}"


def property_first_year(estate):
    """First-year estimate for an investment property: rent kept, running costs, loan interest, required repayments
    and net cash (rent less costs and repayments)."""
    rent = estate["weekly_rent"] * 52 * RENT_KEPT
    costs = estate["running_costs"] * estate["value"]
    interest = repayments = 0.0
    if estate["loan"] > 0:
        loan = Mortgage(estate["loan"], estate["interest_rate"], estate["years"], date(2026, 7, 1),
                        interest_only_years=min(estate["interest_only_years"], estate["years"] - 0.5))
        io = min(26, loan.interest_only_fortnights)
        repayments = io * loan.interest_only_repayment + (26 - io) * loan.repayment
        interest = estate["loan"] * estate["interest_rate"]  # about a year's interest on the opening balance
    return {"rent": rent, "costs": costs, "interest": interest, "repayments": repayments,
            "net": rent - costs - repayments, "profit": rent - costs - interest}


def property_inputs(plan):
    """An investment property, its rent and its loan (ADR 0054)."""
    st.subheader("Investment property")
    estate = plan["investment_property"]
    estate["value"] = money("Property value today (0 = none)", estate["value"], "property_value",
                            help="A home you let to tenants, not the one you live in (that is the Your home card). Leave "
                                 "its costs and repayments out of spending, and leave the property out of other assets "
                                 "for the Age Pension: the planner counts them separately.")
    if estate["value"] <= 0:
        st.caption("No investment property.")
        return
    estate["weekly_rent"] = float(st.number_input("Weekly rent", 0.0, 1e5, float(estate["weekly_rent"]), 10.0,
                                                  key=key("property_rent"), format="%.0f",
                                                  help=f"Rises with CPI each 1 July. {1 - RENT_KEPT:.0%} is allowed for "
                                                       "vacancy and the property manager."))
    estate["loan"] = money("Loan on this property, still owed today (0 = none)", estate["loan"], "property_loan",
                           help="The balance owing on the loan for this rental property, from your latest statement. "
                                "A loan on the home you live in goes in the Home loan card instead.")
    with st.expander("More: growth, loan terms, running costs and tax"):
        c, d = st.columns(2)
        with c:
            estate["growth"] = percent("Value growth, % a year", estate["growth"], "property_growth", low=-10, high=20,
                                       help="Applied monthly, the same on every market path: a fixed assumption, so the "
                                            "property adds no market risk.")
            estate["interest_rate"] = percent("Loan interest rate, % a year", estate["interest_rate"], "property_rate",
                                              low=0, high=30, step=0.05, help="Fixed for the whole run.")
            estate["interest_only_years"] = float(st.number_input(
                "Interest-only years left", 0.0, 15.0, float(estate["interest_only_years"]), 0.5,
                key=key("property_io"), help="Repayments cover only interest for this long, then the loan is repaid "
                                             "over the rest of its years."))
        with d:
            estate["running_costs"] = percent(
                "Running costs, % of value a year", estate["running_costs"], "property_costs", low=0, high=10,
                step=0.1, help="Repairs (about 1%) plus council rates, insurance, strata and land tax (about 0.5%). "
                               "Paid monthly and tax deductible.")
            estate["years"] = float(st.number_input("Loan years left", 0.5, 40.0, float(estate["years"]), 0.5,
                                                    key=key("property_years")))
            st.markdown("&nbsp;")
            estate["losses_offset_salary"] = st.checkbox(
                "Losses reduce tax on salary", estate["losses_offset_salary"], key=key("property_offset"),
                help="Only for a property you held before 7.30 pm AEST on 12 May 2026, or a new build. Otherwise, from "
                     "1 July 2027 a rental loss cannot reduce tax on other income: it is carried forward against later "
                     "rent. Unticked, the planner carries losses forward in every year.")
    if not plan["person"]["homeowner"]:
        moving = st.checkbox("I'll move into it", estate["move_in_date"] is not None, key=key("property_move"),
                             help="From that day it is your home: the rent from tenants and any rent you pay stop, its "
                                  "loan becomes a home loan (no tax deduction), its running costs become the home "
                                  "rate, and the Age Pension treats it as your exempt home. It then leaves total wealth, "
                                  "like any home.")
        if moving:
            start = date.fromisoformat(plan["plan"]["start_date"])
            current = (date.fromisoformat(estate["move_in_date"]) if estate["move_in_date"]
                       else date(start.year + 5, start.month, start.day))
            estate["move_in_date"] = date_fields("Move-in date", current, "property_move_date", start.year,
                                                 start.year + 80)
            if estate["move_in_date"] <= plan["plan"]["start_date"]:
                st.warning("The move-in date must be after the plan's start date.")
        else:
            estate["move_in_date"] = None
    else:
        estate["move_in_date"] = None
    if estate["loan"] > 0 and estate["interest_only_years"] >= estate["years"]:
        st.warning("Interest-only years must be shorter than the loan's years left.")
        return
    year = property_first_year(estate)
    st.metric("Net cash, first year", dollars(year["net"]),
              help=f"Rent kept ${year['rent']:,.0f} less running costs ${year['costs']:,.0f} and loan repayments "
                   f"${year['repayments']:,.0f}. A negative amount is paid from your pay or savings before investing.")
    st.caption(f"Taxable rental result about {dollars(year['profit'], escape=True)} in the first year (rent less costs "
               f"and about \\${year['interest']:,.0f} of interest)."
               + (" A loss is carried forward against later rent." if year["profit"] < 0 and not estate["losses_offset_salary"]
                  else ""))
    explain("Rent arrives monthly into cash; running costs and loan repayments are paid from cash before spending (then "
            "from sales and accessible super, as for spending). Rent less interest and running costs is taxed each year. "
            "The value grows at a fixed rate and counts in total wealth, net of the loan, but the property is never sold, "
            "so a percentage-of-wealth spending rule leaves it out. If money runs out, the result shows the equity that "
            "selling could have used. For the Age Pension, the value less the loan is an assessable asset and net rent is "
            "income.", "How the investment property is modelled")


def work_summary(plan):
    """First-year estimate of where pay goes, using the 2026-27 rules."""
    st.subheader("Where your pay goes")
    employment = plan["employment"]
    salary = employment["annual_salary"]
    if salary <= 0:
        st.caption("No salary: spending is paid from cash, outside investments and, once accessible, super.")
        return
    rules = load_ruleset("2026-27")
    sacrifice = min(sacrifice_per_year(plan), salary)
    sg = rules["super_guarantee_rate"] * min(salary, rules["maximum_contribution_base"])
    concessional = sg + sacrifice
    tax = assess(IncomeYear(labour_income=salary - sacrifice, reportable_employer_super=sacrifice,
                            low_tax_contributions=concessional,
                            private_hospital_cover=plan["person"]["private_hospital_cover"]), rules)
    loan = plan["mortgage"]
    repayments = 0.0
    if loan["balance"] > 0:
        rate, n = loan["interest_rate"] / 26, max(1, round(loan["years"] * 26))
        repayments = 26 * (loan["balance"] / n if rate == 0 else loan["balance"] * rate / (1 - (1 + rate) ** -n))
    estate = plan["investment_property"]
    property_net = property_first_year(estate)["net"] if estate["value"] > 0 else 0.0
    housing = plan["person"]["weekly_rent"] * 52 + plan["home"]["running_costs"] * plan["home"]["value"]
    surplus = (salary - sacrifice - tax.net_tax - tax.division_293_tax - plan["spending"]["annual"] - repayments
               + property_net - housing)
    fixed = plan["outside"]["saving"] == "fixed"
    invested = min(plan["outside"]["contribution_per_year"], max(surplus, 0)) if fixed else max(surplus, 0)
    extra = invested * loan["extra_share"] if loan["balance"] > 0 else 0.0
    invested -= extra
    st.caption("First-year estimate under the 2026-27 rules, before investment income.")
    a, b = st.columns(2)
    a.metric("Into super per year", f"${concessional:,.0f}",
             help=f"Super guarantee ${sg:,.0f} (12%) plus salary sacrifice ${sacrifice:,.0f}, before 15% contributions tax.")
    b.metric("Concessional cap 2026-27", f"${rules['concessional_cap']:,.0f}",
             help="Contributions above the cap (plus any carried-forward unused cap) are not modelled; the run stops.")
    a.metric("Income tax, first year", f"${tax.net_tax + tax.division_293_tax:,.0f}",
             help="Estimated on salary less sacrifice, before investment income and capital gains.")
    b.metric("Added to outside investments", f"${invested:,.0f}/yr",
             help=("Your fixed contribution, limited to what is left after tax and spending." if fixed else
                   "Take-home pay less tax and spending, all invested.") + " Set this on the Investments tab; contributions "
                  "from pay stop at retirement, after which spare cash above the buffer is reinvested.")
    if repayments:
        st.caption(f"Home loan: \\${repayments:,.0f} a year of required repayments"
                   + (f" and about \\${extra:,.0f} of extra repayments" if extra > 1 else "") + " in the first year.")
    if housing:
        st.caption(f"Your home: about \\${housing:,.0f} a year of "
                   + ("rent" if plan["person"]["weekly_rent"] else "running costs") + ", paid before spending.")
    if property_net:
        st.caption(f"Investment property: about \\${abs(property_net):,.0f} a year "
                   + ("added from rent after its costs and repayments." if property_net > 0
                      else "of costs and repayments beyond its rent, paid from pay.") + " Tax on its rent is not included.")
    if fixed and surplus > invested + extra + 1:
        st.caption(f"About ${surplus - invested - extra:,.0f} a year of leftover pay stays in cash, earning the cash interest rate.")
    if fixed and plan["outside"]["contribution_per_year"] > max(surplus, 0) + 1:
        st.warning("The fixed outside contribution is more than is left after tax and spending; only what is available "
                   "above the cash buffer is invested each payday.")
    if concessional > rules["concessional_cap"]:
        st.warning(f"Super guarantee plus salary sacrifice (${concessional:,.0f}) is above the ${rules['concessional_cap']:,.0f} "
                   "concessional cap. Unless you have carried-forward unused cap, the run will stop with an "
                   "excess-contributions message.")
    explain("Each fortnight your salary after sacrifice goes into cash. Spending (monthly) and tax (each 31 October) are "
            "paid from it. Then either everything above the cash buffer, or your fixed contribution, buys the outside "
            "portfolio (choose on the Investments tab). From retirement, all cash above the buffer is reinvested "
            "instead. After the first year "
            + ("salary rises with wage growth." if employment.get("salary_indexed", True)
               else "salary stays the same dollar amount."), "How saving outside super works")


def inputs_investments(plan):
    with card("tickers"):
        st.subheader("Tickers")
        plan["assets"] = st.multiselect(
            "Tickers available to both portfolios", TICKERS, default=plan["assets"], key=key("tickers"),
            format_func=lambda ticker: f"{ticker} · {'long-history dataset' if ticker in CUSTOM_TICKERS else 'fund history'}",
            help="Custom series extend back to 1970; fund tickers begin at their observed inception. Return and "
                 "cash-contribution estimates come from local processed data.")
        names = plan["assets"]
        if names:
            try:
                preview = cached_market(tuple(names))
                summary = preview.asset_summary[["Ticker", "First", "Last", "Full-sample CAGR", "Cash contribution proxy"]].copy()
                summary["Coverage"] = summary["First"].astype(str) + "–" + summary["Last"].astype(str)
                summary = summary[["Ticker", "Coverage", "Full-sample CAGR", "Cash contribution proxy"]]
                summary["Full-sample CAGR"] *= 100
                summary["Cash contribution proxy"] *= 100
                st.dataframe(summary, width="stretch", hide_index=True, column_config={
                    "Full-sample CAGR": st.column_config.NumberColumn("Full-sample CAGR %", format="%.2f"),
                    "Cash contribution proxy": st.column_config.NumberColumn(
                        "Cash contribution proxy %/yr", format="%.2f",
                        help="A historical planning proxy that splits total return into income and price for tax. It "
                             "is not an ETF tax statement or an extra return.")})
            except ValueError as exc:
                st.warning(str(exc))
    left, right = st.columns(2, gap="medium")
    with left:
        with card("outside"):
            st.subheader("Outside super")
            a, b = st.columns(2)
            with a:
                plan["outside"]["investment_balance"] = money("Investments today", plan["outside"]["investment_balance"],
                                                              "outside_value")
                plan["outside"]["cash"] = money("Cash today", plan["outside"]["cash"], "cash")
            with b:
                plan["outside"]["cash_buffer"] = money("Cash buffer kept uninvested", plan["outside"]["cash_buffer"], "buffer")
                plan["outside"]["cash_interest"] = percent(
                    "Interest on cash %/yr", plan["outside"]["cash_interest"], "cash_interest", low=-5, high=20, step=0.25,
                    help="Assumed nominal rate on all outside cash, credited daily and taxed as income.")
            saving = st.radio("Yearly additions from your pay until retirement", ["surplus", "fixed"],
                              index=["surplus", "fixed"].index(plan["outside"]["saving"]), horizontal=True, key=key("saving"),
                              format_func={"surplus": "Everything left after tax and spending", "fixed": "A fixed amount"}.get,
                              help="Contributions come out of your pay each fortnight and stop at your retirement date. "
                                   "After retirement all cash above the buffer is reinvested in this portfolio, such as "
                                   "pension payments, distributions and interest you do not spend.")
            plan["outside"]["saving"] = saving
            if saving == "fixed":
                plan["outside"]["contribution_per_year"] = money(
                    "Yearly addition to outside investments", plan["outside"]["contribution_per_year"], "outside_contribution",
                    help="Invested in equal amounts each fortnightly payday. Leftover pay stays in cash.")
                plan["outside"]["contribution_indexed"] = st.checkbox(
                    f"Increase it with inflation each 1 July ({plan['assumptions']['cpi_annual']:.1%} CPI)",
                    plan["outside"]["contribution_indexed"], key=key("contribution_indexed"))
            st.markdown("**Portfolio mix**")
            plan["outside"]["weights"] = weights_editor(plan["outside"]["weights"], names, "outw")
            plan["outside"]["rebalance"] = rebalance_choice(
                plan["outside"]["rebalance"], "outside_rebalance",
                "Outside super each rebalance sells overweight holdings, which realises capital gains tax.")
            with st.expander("Opening tax position"):
                st.caption("One aggregate cost base and acquisition date are allocated across the portfolio. This is an "
                           "approximation if you bought at different times or prices.")
                plan["outside"]["opening_cost_base"] = money("Total cost base", plan["outside"]["opening_cost_base"], "outside_basis")
                plan["outside"]["opening_acquired"] = date_fields(
                    "Acquisition date used for the opening portfolio", date.fromisoformat(plan["outside"]["opening_acquired"]),
                    "acquired", 1950, date.fromisoformat(plan["plan"]["start_date"]).year)
    with right:
        with card("super"):
            st.subheader("Inside super")
            a, b = st.columns(2)
            with a:
                plan["super"]["balance"] = money("Super balance today", plan["super"]["balance"], "super")
            with b:
                st.markdown("&nbsp;")
                same = st.checkbox("Same balance at last 30 June", plan["super"]["total_super_balance_prior_30_june"]
                                   == plan["super"]["balance"], key=key("tsb_same"),
                                   help="The total super balance on the previous 30 June sets this year's contribution caps "
                                        "(carry-forward and non-concessional). Untick only if it differed from today's balance.")
            if same:
                plan["super"]["total_super_balance_prior_30_june"] = plan["super"]["balance"]
            else:
                plan["super"]["total_super_balance_prior_30_june"] = money(
                    "Total super balance at last 30 June", plan["super"]["total_super_balance_prior_30_june"], "tsb")
            st.markdown("**Portfolio mix**")
            plan["super"]["weights"] = weights_editor(plan["super"]["weights"], names, "supw")
            plan["super"]["rebalance"] = rebalance_choice(
                plan["super"]["rebalance"], "super_rebalance",
                "Inside super the switch itself is untaxed; the fund's own trading is covered by the realised-gains "
                "assumption below.")
            plan["super"]["realised_gains"] = percent(
                "Share of the fund's unrealised gains realised each year %", plan["super"]["realised_gains"], "super_realised",
                low=0, high=100, step=5.0,
                help="Super funds trade, so part of the growth in your balance is realised as capital gains each year. In "
                     "accumulation these are taxed at 15% after the one-third discount (10% effective); in the pension they "
                     "are tax-free. Both count towards Division 296 above a 3 million dollar balance. There is no published "
                     "turnover figure for funds: 20% is an assumption (gains held about five years on average). 0% realises "
                     "nothing and gives the lowest tax; 100% realises every year's gain.")


def strategy_notes(spending, compare):
    """What each ticked strategy does, and its own settings."""
    if "fixed" in compare:
        how = {"same": "the amount you spend now", "amount": "the amount you set",
               "percent": "that percentage of your wealth on your retirement date"}[spending["retirement"]]
        st.info(f"**Fixed spending.** You spend {how} in your first retired year, and after that the same buying power "
                "every year, whatever the markets do. If markets fall, spending stays the same and takes a bigger share "
                "of what is left, which is how plans run out of money.")
    if "guyton_klinger" in compare:
        st.info("**Guyton–Klinger guardrails** (Guyton and Klinger, 2006). Spending starts at the starting rate. Each "
                "1 July after that, the *withdrawal rate* is that year's spending divided by total wealth:\n"
                "1. After a year in which your investments lost money, skip that year's inflation increase if the rate "
                "is above the start.\n"
                f"2. If the rate is more than {spending['guardrail_band']:.0%} above the start, **cut spending "
                f"{spending['guardrail_step']:.0%}**.\n"
                f"3. If it is more than {spending['guardrail_band']:.0%} below the start, **raise spending "
                f"{spending['guardrail_step']:.0%}**.\n\n"
                "In this planner's simulations it rarely runs out of money, but about one in five paths has a year more "
                "than 20% below the starting amount.")
        a, b = st.columns(2)
        with a:
            spending["guardrail_band"] = percent("Guardrail width %", spending["guardrail_band"], "gk_band", low=1, high=90,
                                                 step=1.0, help="How far the withdrawal rate can move from its start "
                                                                "before spending changes.")
        with b:
            spending["guardrail_step"] = percent("Change when a guardrail is hit %", spending["guardrail_step"], "gk_step",
                                                 low=1, high=90, step=1.0)
    if "vanguard" in compare:
        st.info("**Vanguard ceiling and floor** (Jaconetti and colleagues, Vanguard, 2013). Spending starts at the "
                "starting rate. Each 1 July after that, spending aims for that rate times your current wealth, but the "
                f"change from last year (after inflation) is limited to **+{spending['ceiling']:.1%}** and "
                f"**−{spending['floor']:.1%}**, so cuts are small and gradual. In this planner's simulations cuts were "
                "gentler than Guyton–Klinger, but at a 5% start it ran out about as often as fixed spending.")
        a, b = st.columns(2)
        with a:
            spending["ceiling"] = percent("Largest yearly rise %", spending["ceiling"], "vg_ceiling", low=0, high=90, step=0.5)
        with b:
            spending["floor"] = percent("Largest yearly cut %", spending["floor"], "vg_floor", low=0, high=90, step=0.5)
    if "percent" in compare:
        st.info("**A percentage of wealth each year.** On your retirement date and each 1 July after that, spending is "
                "the starting rate times your total wealth that day, so spending moves fully with the markets: a 30% fall "
                "cuts next year's spending by 30%. It can still run short: spending is reset only each 1 July, so a fall "
                "during the year is not followed until the next review; super may not yet be accessible to pay it; and "
                "the minimum below can force spending above the rate. It is a useful reference for how much "
                "variability the other rules remove.")


def spending_rule_inputs(plan):
    """Which spending strategies to compare, how retirement spending starts, and each strategy's settings."""
    spending = plan["spending"]
    st.subheader("Spending strategies")
    st.caption("Tick one or more. Every ticked strategy runs on the same simulated market paths, with every other "
               "input unchanged, so the differences come from the strategy alone.")
    spending["compare"] = [rule for rule in RULE_LABELS
                           if st.checkbox(RULE_LABELS[rule], rule in spending["compare"], key=key(f"compare_{rule}"))]
    compare = spending["compare"]
    if not compare:
        st.error("Tick at least one strategy.")
        return
    if len(compare) > 1:
        st.caption(f"Each of the {len(compare)} ticked strategies runs on every daily ledger path, so a run takes "
                   f"about {len(compare)} times as long as one strategy.")
    only_fixed = compare == ["fixed"]
    if only_fixed:
        spending["retirement"] = st.radio("Retirement spending starts at", list(START_LABELS),
                                          index=list(START_LABELS).index(spending["retirement"]), format_func=START_LABELS.get,
                                          horizontal=True, key=key("spend_start"))
    else:
        spending["retirement"] = "percent"
    if spending["retirement"] == "amount":
        spending["retirement_annual"] = money("Spending once retired (today's dollars a year)", spending["retirement_annual"],
                                              "spend_retired", help="Rises with inflation like spending now.")
    elif spending["retirement"] == "percent":
        spending["retirement_percent"] = percent(
            "Starting withdrawal rate: % of total wealth on your retirement date", spending["retirement_percent"],
            "spend_rate", low=0.1, high=50, step=0.1,
            help="Total wealth is cash, outside investments and super. Each simulated path reaches retirement with "
                 "different wealth, so each gets its own dollar amount; the results show the range in today's dollars. "
                 "For reference, Guyton and Klinger tested starting rates of about 5–5.5% with their guardrails; 4% is "
                 "a common rule of thumb for fixed spending over 30 years."
                 + (" Every compared strategy starts from this same rate, so they begin with the same spending on "
                    "each path." if len(compare) > 1 else ""))
    strategy_notes(spending, compare)
    if not only_fixed:
        a, b = st.columns(2)
        with a:
            spending["minimum"] = money("Essential minimum (today's dollars a year; 0 = none)", spending["minimum"],
                                        "spend_minimum",
                                        help="Never cut below this. Rises with inflation. A higher minimum makes cuts "
                                             "shallower but raises the chance of running out. Applies to every "
                                             "market-responsive strategy; fixed spending ignores it.")
        with b:
            spending["maximum"] = money("Maximum (today's dollars a year; 0 = none)", spending["maximum"], "spend_maximum",
                                        help="Never spend more than this. Rises with inflation. Stops spending racing up "
                                             "on paths where markets do very well. Applies to every market-responsive "
                                             "strategy; fixed spending ignores it.")
        st.caption("Market-responsive strategies review spending once a year on 1 July after your retirement date, using "
                   "total wealth (cash, outside investments and super). Each review and its reason are in a path's "
                   "event log.")


def inputs_retirement(plan):
    spending, cpi = plan["spending"], plan["assumptions"]["cpi_annual"]
    left, right = st.columns([1.25, 1], gap="medium")
    with left:
        with card("spending"):
            st.subheader("Spending")
            spending["annual"] = money("Spending now (today's dollars a year)", spending["annual"], "spend",
                                       help="Everything you spend in a year, paid monthly from cash. All spending amounts "
                                            f"are in today's dollars: each 1 July they rise with inflation ({cpi:.1%} CPI, "
                                            "Assumptions tab), so they buy the same every year.")
            with st.expander("Spend more or less over time", expanded=spending["real_change"] != 0):
                spending["real_change"] = percent(
                    "Real change in spending, % a year on top of inflation", spending["real_change"], "spend_real", low=-10,
                    high=10,
                    help="0 keeps buying power constant. Studies of retirees' actual spending find it tends to fall slowly "
                         "with age in real terms, by roughly 1% a year (the 'retirement spending smile'); −1% models that.")
                st.caption("This applies before and after retirement, and to the starting amount set by a percentage. The "
                           "essential minimum and maximum always rise with inflation only.")
        with card("strategies"):
            spending_rule_inputs(plan)
    with right:
        with card("abp"):
            st.subheader("Account-based pension")
            pension = plan["pension"]
            pension["start_age"] = int(st.number_input("Start pension at age (0 = never)", 0, 80, int(pension["start_age"]), 1,
                                                       key=key("pension_age"),
                                                       help="Needs retirement and age 60 or over, or age 65. An earlier age "
                                                            "starts the pension when super becomes accessible."))
            pension["transfer_all"] = st.checkbox("Move the whole super balance into the pension",
                                                  pension["transfer_all"], key=key("all"),
                                                  help="Up to the transfer balance cap.")
            if not pension["transfer_all"]:
                pension["amount"] = money("Amount to move into the pension", pension["amount"], "pension_amount")
            st.caption("Before super is accessible, spending is paid from cash and outside investments; any gap is a "
                       "shortfall.")
        with card("agepension"):
            st.subheader("Age Pension")
            person = plan["person"]
            st.caption(("You own the home you live in" if person["homeowner"] else "You do not own the home you live in")
                       + " (set on the You tab), so the "
                       + ("homeowner" if person["homeowner"] else "non-homeowner") + " assets limits apply.")
            person["other_assets"] = money("Other assessable assets (AUD)", person["other_assets"], "other_assets",
                                           help="Cars, caravans, home contents and other personal assets at what they would "
                                                "sell for. They count in the assets test but are not invested.")
            explain("From a fortnight after you turn 67 the planner works out the single Age Pension every fortnight: the "
                    "lower of the assets test (everything you hold except your home) and the income test (deemed income "
                    "on your investments and super, plus any wages after the Work Bonus). It is paid into cash and is "
                    "partly taxable, and the seniors and pensioners tax offset applies. It assumes you have lived in "
                    "Australia for at least 10 years and claim on time.", "How the Age Pension is modelled")


def year_to_date_inputs(plan):
    """This financial year before the start date: required for a start after 1 July (ADR 0036)."""
    ytd = plan["year_to_date"]
    start = date.fromisoformat(plan["plan"]["start_date"])
    midyear = (start.month, start.day) != (7, 1)
    with st.expander("This financial year before the start date", expanded=midyear and not ytd["entered"]):
        st.caption("Tax is assessed on the whole financial year. A start after 1 July needs what already happened since "
                   "1 July, or the part year would be taxed as if it were the whole year and could show a false refund. "
                   "Last year's tax still to settle and employer super not yet received apply to any start.")
        a, b = st.columns(2)
        fields = (("labour_income", "Salary received (after sacrifice)"), ("salary_sacrifice", "Salary sacrificed"),
                  ("payg_withheld", "Tax withheld from pay"), ("concessional_contributions", "Concessional super contributions received"),
                  ("non_concessional_contributions", "Non-concessional contributions"),
                  ("other_taxable_income", "Other taxable income (interest, unfranked dividends, net capital gains)"),
                  ("franked_dividends", "Franked dividends (cash)"), ("franking_credits", "Franking credits"),
                  ("age_pension", "Age Pension received"),
                  ("pending_employer_contributions", "Employer super earned but not yet received"))
        for i, (name, label) in enumerate(fields):
            with (a if i % 2 == 0 else b):
                ytd[name] = money(label, ytd[name], f"ytd_{name}")
        ytd["prior_year_tax"] = float(st.number_input(
            "Last year's tax still to settle (negative for a refund)", -1e8, 1e8, float(ytd["prior_year_tax"]), 100.0,
            key=key("ytd_prior_year_tax"), format="%.0f", help="Due 31 October, or at the start date if that is later."))
        ytd["entered"] = st.checkbox("These are my amounts for this financial year so far (zeros where none)", ytd["entered"],
                                     key=key("ytd_entered"), disabled=not midyear and not ytd["entered"])
        if midyear and not ytd["entered"]:
            st.warning("The start date is after 1 July: confirm these amounts before running.")


def inputs_assumptions(plan):
    left, right = st.columns(2, gap="medium")
    with left:
        with card("horizon"):
            st.subheader("Horizon")
            a, b = st.columns(2)
            with a:
                plan["plan"]["start_date"] = st.date_input("Start date", date.fromisoformat(plan["plan"]["start_date"]),
                                                           date(2026, 7, 1), date(2040, 6, 30), key=key("start"),
                                                           format="YYYY-MM-DD").isoformat()
            with b:
                plan["plan"]["years"] = int(st.number_input(
                    "Years to simulate", 1, 60, int(plan["plan"]["years"]), 1, key=key("years"),
                    help="Runs can go past Age Pension age. Results only cover the years simulated, so run to an advanced "
                         "age (90 or more) to see the whole retirement, the Age Pension and the risk of ruin."))
            year_to_date_inputs(plan)
        with card("economy"):
            st.subheader("Economic assumptions")
            a, b = st.columns(2)
            with a:
                plan["assumptions"]["cpi_annual"] = percent(
                    "CPI %/yr", plan["assumptions"]["cpi_annual"], "cpi", low=-10, high=20,
                    help="Indexes spending, CGT cost bases from 1 July 2027 and CPI-linked thresholds, and converts "
                         "results to today's dollars.")
            with b:
                plan["assumptions"]["wage_growth_annual"] = percent(
                    "Wage growth %/yr", plan["assumptions"]["wage_growth_annual"], "wages", low=-10, high=20,
                    help="Raises salary each year (if ticked on the You tab) and indexes contribution caps, MLS "
                         "thresholds and the Age Pension's basic rate.")
            st.caption("Tax and super rules are sourced for 2026-27; later years apply enacted changes and project indexed "
                       "thresholds with these assumptions (see docs/rules/au-projection.md).")
    with right:
        with card("market"):
            st.subheader("Market simulation")
            a, b = st.columns(2)
            with a:
                plan["market"]["retirement_paths"] = int(st.number_input(
                    "Daily retirement-ledger paths", 1, 2000, int(plan["market"]["retirement_paths"]), 1,
                    key=key("retirement_paths"),
                    help="The first shared market draws are run through the full daily tax, spending and super ledger. "
                         "Each takes about a quarter of a second per ten years on one core, and the paths are shared "
                         "across the calculation cores. 100 or more is recommended for shortfall rates; 500 gives five "
                         "paths in the worst 1%."))
                plan["market"]["block_length"] = int(st.number_input(
                    "Average block length (trading days)", 1, 1260, int(plan["market"]["block_length"]), 1,
                    key=key("block_length"), help="How long, on average, each copied run of history is."))
            with b:
                plan["market"]["paths"] = int(st.number_input(
                    "Portfolio paths", 16, 5000, int(plan["market"]["paths"]), 100, key=key("paths"),
                    help="Market paths for the portfolio statistics on the Markets page. 1,000 gives stable medians and "
                         "usable 5th/95th percentiles."))
                plan["market"]["seed"] = int(st.number_input("Random seed", 0, 2147483647, int(plan["market"]["seed"]), 1,
                                                              key=key("seed")))
            # Labels must not change between reruns: Streamlit matches the stored choice by its label, and the
            # automatic count moves with free memory, so it is shown in the help instead.
            st.selectbox("Calculation cores", [0, *range(1, (os.cpu_count() or 1) + 1)], key="calculation_cores",
                         format_func=lambda n: "Automatic" if n == 0 else str(n),
                         help="Worker processes for the daily ledgers. They run at below-normal priority, so other programs "
                              f"stay responsive. Automatic leaves {CPU_HEADROOM} hardware threads free and keeps 4 GB of "
                              "memory available; choose fewer for a quieter computer. This is a setting for this computer, "
                              "not part of the plan file.")
            if not calculation_cores():
                st.caption(f"Automatic uses {automatic_workers()} worker processes on this computer right now.")
            block = plan["market"]["block_length"]
            explain(f"""
Each simulated future is stitched together from **runs of real history**. The simulator picks a random trading day in
the shared history and copies the following days in order (every ticker on the same day, so they move together as
they really did). After each day it either carries on with the next historical day or, with probability
1/{block}, jumps to a new random day and starts another run. Runs therefore last **{block} trading days on average**
(about {block / 21:.0f} months; there are roughly 252 trading days a year), some much shorter and some much longer.

**Why it matters.** Within a run, real patterns survive: a crash that unfolds over weeks, a volatile spell, a
recovery. Between runs, eras are mixed, so one path might go from 1987 to 2008 to 1975.
- **Longer blocks** (e.g. 252, one year) keep longer patterns such as multi-month bear markets and the way rates
  and stocks moved together for a while, but each path repeats larger chunks of the same history, so paths look
  more alike.
- **Shorter blocks** (e.g. 5–21) mix history more freely and give more variety, but break up longer crises and
  trends into pieces, which can understate how long bad stretches last.
- **1** draws every day independently, losing all short-term patterns; usually too optimistic about smooth paths.

63 days (about three months) is a common middle ground. If results change a lot between, say, 21 and 252, treat the
difference as part of the uncertainty. Longer generated horizons repeat patterns; they do not create longer
observed history.
""", "What is the average block length?")


def page(plan):
    """The Plan page. Every tab is drawn (inputs are cheap), so switching tabs needs no rerun of the inputs."""
    # A keyed, tracked tab set keeps the open tab when a widget on it reruns the app.
    tabs = st.tabs(["You", "Investments", "Retirement", "Assumptions"], key="plan_tabs", on_change="rerun")
    for tab, draw_tab in zip(tabs, (inputs_you, inputs_investments, inputs_retirement, inputs_assumptions)):
        with tab:
            draw_tab(plan)
