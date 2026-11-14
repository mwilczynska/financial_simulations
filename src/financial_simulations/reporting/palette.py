"""One colour system for the browser app and the PNG review plots (ADRs 0047 and 0059).

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

# The bold set (ADR 0059) colours the things a plan is made of: accounts, portfolios, tickers and money flows. The
# strategies, the outcome tiers and the app's theme keep the reference hues above.
B_BLUE, B_PURPLE, B_GREEN, B_CYAN = "#3b82f6", "#6d28d9", "#22c55e", "#06b6d4"
B_PINK, B_ORANGE, B_RED, B_AMBER = "#ec4899", "#f97316", "#e11d48", "#f59e0b"
B_NAVY, B_BROWN, B_LIME, B_ROSE, TAUPE = "#1e3a8a", "#8f5a14", "#84cc16", "#f472b6", "#b7a99a"

# Outside super is blue and super is purple wherever accounts or portfolios appear; the two combined are navy.
PORTFOLIO_COLOURS = {"Outside super": B_BLUE, "Inside super": B_PURPLE, "Combined": B_NAVY}
# Tickers, in the plan's order. They avoid the three portfolio colours, which share a chart with them.
TICKER_COLOURS = (B_GREEN, B_PINK, B_ORANGE, B_CYAN, B_AMBER, B_RED, B_BROWN, B_LIME)
# Bars that are not one of the named flows below (transfers between accounts), in drawing order.
BOLD_SERIES = (B_BLUE, B_PURPLE, B_GREEN, B_CYAN, B_PINK, B_ORANGE, B_RED, B_AMBER)
ACCOUNT_COLOURS = {"cash": ("Cash", B_AMBER), "outside_investments": ("Outside investments", B_BLUE),
                   "accumulation": ("Super (accumulation)", B_PURPLE), "pension": ("Account-based pension", B_GREEN)}
# A home loan is drawn below zero under the accounts, only on paths that have one.
MORTGAGE_COLOUR = ("Mortgage owed", B_RED)
# An investment property's value is drawn above the accounts and its loan below zero, only on paths that have one.
PROPERTY_COLOUR, PROPERTY_LOAN_COLOUR = ("Investment property", B_CYAN), ("Investment loan owed", B_ROSE)
# A former investment property you moved into stays in total wealth as your home: the property's brown flow hue.
MOVED_HOME_COLOUR = ("Home you moved into", B_BROWN)

# Money in and out, in stacking order. The four taxes are drawn as one "Tax" flow, and an investment property's rent,
# costs, loan interest and value growth as one "Investment property" flow, and mortgage interest and the home's running
# costs as one "Home" flow (``flows.fold_taxes``): sixteen hues cannot be told apart, and the yearly tables keep each
# flow. Green, cyan, orange and amber are below 3:1 contrast on white, so the charts carry a legend and a table.
FLOW_COLOURS = {"Take-home salary": B_BLUE, "Super contributions": B_PURPLE, "Investment returns": B_GREEN,
                "Interest on cash": B_CYAN, "Age Pension": B_PINK, "Spending": B_ORANGE, "Tax": B_RED,
                "Home": B_AMBER, "Investment property": B_BROWN,
                "Inflation": TAUPE}
NET_COLOUR, ADDED_COLOUR = INK, "#104281"


def portfolio_line_colours(count):
    """Line colours for a chart's portfolios, in drawing order: combined, outside, inside, or the last two alone."""
    return (B_NAVY, B_BLUE, B_PURPLE) if count > 2 else (B_BLUE, B_PURPLE)


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
