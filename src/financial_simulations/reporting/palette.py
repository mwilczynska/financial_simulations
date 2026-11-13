"""One colour system for the browser app and the PNG review plots (ADR 0047).

Pure constants, so the command line, the reports and the app can all import them. The eight series hues and the
ink and surface greys are the reference categorical palette already used for the compared strategies
(``strategy_results.STRATEGY_COLOURS``). Every set below was run through the palette validator on a white surface in
its drawing order: lightness band, chroma floor, colour-vision separation of neighbours and the normal-vision floor.
Yellow, aqua and magenta are below 3:1 contrast on white, so every chart that uses them carries a legend and a table.
"""

BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
MAGENTA, GREEN, VIOLET, RED = "#e87ba4", "#008300", "#6250d6", "#e34948"
SERIES = (BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED)

INK, INK_SECONDARY, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS, NEUTRAL = "#e1e0d9", "#c3c2b7", "#a8a69d"
PAGE, SURFACE = "#f9f9f7", "#ffffff"
ACCENT = "#1c5cab"  # buttons, links and the selected state: a darker step of the series blue

# Outside super is blue and super is orange wherever accounts or portfolios appear.
PORTFOLIO_COLOURS = {"Outside super": BLUE, "Inside super": ORANGE, "Combined": AQUA}
ACCOUNT_COLOURS = {"cash": ("Cash", YELLOW), "outside_investments": ("Outside investments", BLUE),
                   "accumulation": ("Super (accumulation)", ORANGE), "pension": ("Account-based pension", AQUA)}
# A home loan is drawn below zero under the accounts, only on paths that have one.
MORTGAGE_COLOUR = ("Mortgage owed", RED)
# An investment property's value is drawn above the accounts and its loan below zero, only on paths that have one.
PROPERTY_COLOUR, PROPERTY_LOAN_COLOUR = ("Investment property", GREEN), ("Investment loan owed", VIOLET)

# Money in and out, in stacking order. The four taxes are drawn as one "Tax" flow, and an investment property's rent,
# costs, loan interest and value growth as one "Investment property" flow (``flows.fold_taxes``): fifteen hues cannot be
# told apart, and the yearly tables keep each flow. The property's brown is outside the eight series hues (all in use
# here); like yellow it is drawn with a legend and a table.
FLOW_COLOURS = {"Take-home salary": BLUE, "Super contributions": ORANGE, "Investment returns": AQUA,
                "Interest on cash": GREEN, "Age Pension": YELLOW, "Spending": MAGENTA, "Tax": VIOLET,
                "Mortgage interest": RED, "Investment property": "#8a5a1c",
                "Inflation": NEUTRAL}
NET_COLOUR, ADDED_COLOUR = INK, "#104281"

# Path outcomes, from the best to the worst (``retirement.outcomes.TIERS``). Self-funded is a neutral grey so that
# colour marks only the paths that need attention; the other three darken with severity.
TIER_COLOURS = {"Self-funded": NEUTRAL, "Part Age Pension": YELLOW, "Full Age Pension": "#de4f1f", "Ran out": "#9b1c3c"}

# Streamlit theme options. ``.streamlit/config.toml`` repeats them for ``streamlit run``; a test keeps the two equal.
STREAMLIT_THEME = {
    "base": "light",
    "primaryColor": ACCENT,
    "backgroundColor": PAGE,
    "secondaryBackgroundColor": "#f0efec",
    "textColor": "#1a1a19",
    "linkColor": ACCENT,
    "borderColor": GRID,
    "showWidgetBorder": True,
    "baseRadius": "0.6rem",
    "baseFontSize": 15,
    "headingFontSizes": ["1.6rem", "1.25rem", "1.02rem"],
    "headingFontWeights": [650, 650, 600],
    "metricValueFontSize": "1.55rem",
    "metricValueFontWeight": 600,
    "dataframeHeaderBackgroundColor": "#f4f3ef",
    "chartCategoricalColors": list(SERIES),
}
