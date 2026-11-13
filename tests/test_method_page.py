"""The Method page's text: placeholders, the projected-rule tables and the figures they quote (ADR 0058)."""

from datetime import date
import re

import pytest

pytest.importorskip("streamlit")  # the app's packages are an optional install; without them this file is skipped
pytest.importorskip("altair")

from financial_simulations.retirement.plan import default_plan, normalize_plan
from financial_simulations.ui import method_page


TEXTS = (method_page.OVERVIEW, method_page.DOLLARS, method_page.MARKETS, method_page.LEDGER, method_page.SPENDING,
         method_page.TAX, method_page.AGE_PENSION, method_page.PROPERTY, method_page.RESULTS, method_page.ASSUMPTIONS)


def test_fill_replaces_every_placeholder_and_rejects_an_unknown_one():
    assert method_page.fill("over [[years]] years at $c$ = [[cpi]]", {"years": 40, "cpi": "2.5%"}) == "over 40 years at $c$ = 2.5%"
    with pytest.raises(KeyError):
        method_page.fill("[[missing]]", {})


def test_page_text_keeps_percent_signs_and_dollar_amounts_out_of_the_maths():
    for text in TEXTS:
        # A dollar amount is written with an escaped sign; the signs left over open and close formulas, so they pair.
        pieces = re.sub(r"\\\$", "", text).replace("$$", "$").split("$")
        assert len(pieces) % 2 == 1
        # Placeholders hold formatted figures (with % and escaped $), which would break inside a formula.
        for formula in pieces[1::2]:
            assert "[[" not in formula and "%" not in formula, formula


def test_projected_rule_tables_show_fixed_and_indexed_amounts():
    plan = normalize_plan(default_plan())
    rules = method_page.projected_rules(plan, "2035-36")
    assert list(rules)[0] == "2026-27" and list(rules)[-1] == "2035-36"
    table = method_page.projection_table(rules, date(2026, 7, 1), plan["assumptions"]["cpi_annual"], homeowner=True)
    rows = {line.split("|")[1].strip(): [cell.strip() for cell in line.split("|")[2:5]] for line in table.splitlines()[2:]}
    # Tax thresholds are not indexed, so they fall in today's dollars: 18,200 / 1.025 ** 9.
    assert rows["Top of the tax-free band"] == ["\\$18,200", "\\$18,200", "\\$14,573"]
    # The concessional cap grows with wages in $2,500 steps: 32,500 x 1.035 ** 9 = 44,294, rounded down.
    assert rows["Concessional contributions cap"][:2] == ["\\$32,500", "\\$42,500"]
    # The transfer balance cap grows with CPI in $100,000 steps: 2.1m x 1.025 ** 9 = 2.62m.
    assert rows["Transfer balance cap"][:2] == ["\\$2,100,000", "\\$2,600,000"]
    brackets = method_page.bracket_table(rules)
    assert "| \\$18,200 to \\$45,000 | 15% | 14% |" in brackets and "| Over \\$190,000 | 45% | 45% |" in brackets
    assumed = method_page.assumed_parameters(rules)
    basis = dict(zip(assumed["Parameter"], assumed["Basis"]))
    assert basis["concessional cap"] == "Projected" and basis["medicare low income lower"] == "Assumed"
    assert "resident tax thresholds" not in basis  # enacted and not indexed, so neither assumed nor projected
    assert "\\$2,500" in method_page.markdown_table(assumed)  # dollar signs in the notes are escaped for Markdown
