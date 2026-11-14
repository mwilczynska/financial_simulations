# ADR 0059: bold colours for accounts, portfolios, tickers and money flows

Date: 2026-11-14.

Status: accepted; implemented and tested. Supersedes the account, portfolio, ticker and flow colours of
[ADR 0047](0047-app-layout-and-one-visual-system.md); its layout, chart configuration, strategy colours and outcome
tier colours stand.

## Context

**User requirements:**

- The money in and out bar charts should have different colours.
- The markets, wealth and money in and out panels of the Paths page should change with them.
- The dark green (`#008300`) should be replaced by a brighter green.
- The combined, outside and inside portfolio lines should not be greys.
- The colours of the Outcomes page's headline charts (outcome tiers, the median and its bands) are liked and stay.

The user was shown seven candidate schemes on sample data and chose the one called G, "Bold": saturated blue,
purple, green, cyan, pink, orange, red and amber.

## Decision

`reporting/palette.py` gains a second set of hues, the bold set, for the things a plan is made of. The reference
hues of ADR 0047 remain for the compared strategies, the outcome tiers and the app's theme.

| Thing | Colour |
| --- | --- |
| Outside super (account and portfolio), take-home salary | Blue `#3b82f6` |
| Super accumulation, inside-super portfolio, super contributions | Purple `#6d28d9` |
| Account-based pension, investment returns, first ticker | Green `#22c55e` |
| Cash, home costs | Amber `#f59e0b` |
| Mortgage owed, tax | Red `#e11d48` |
| Spending | Orange `#f97316` |
| Interest on cash, investment property value | Cyan `#06b6d4` |
| Age Pension | Pink `#ec4899` |
| Investment property flow, home you moved into | Brown `#8f5a14` |
| Investment loan owed | Rose `#f472b6` |
| Inflation | Taupe `#b7a99a` |
| Combined portfolio | Navy `#1e3a8a` |

Tickers take green, pink, orange, cyan, amber, red, brown and lime (`#84cc16`) in the plan's order, on the Markets
page and the Paths page alike. They avoid blue, purple and navy, which are the portfolios drawn beside them.
Transfers between accounts use the first eight bold hues.

**Outside super is blue and super is purple** wherever accounts or portfolios appear. This replaces "super is
orange" in ADR 0047.

### Two shades differ from the scheme as shown

The scheme the user chose had blue `#2563eb` and purple `#7c3aed`. The palette validator scored that pair at a
separation of 0.4 for deuteranopia (the target is 8) and 12.4 for normal vision (the floor is 15). The two are
neighbours in the wealth chart, the flow bars and the market lines, as outside super and super. Blue was lightened
to `#3b82f6` and purple deepened to `#6d28d9`, which score 10.9 and 18.7.

## Reasons and evidence

- **User requirement:** the scheme, the brighter green and coloured portfolio lines.
- **Engineering judgement:** the two adjusted shades; the colours of things the sample charts did not show
  (investment property, its loan, the home moved into, the fourth and later tickers); and applying the scheme
  wherever the same account, portfolio or flow is drawn, so that one thing has one colour on every page.
- **Checked with the palette validator** (14 November 2026, white surface, neighbours in drawing order): the ten
  flow colours, the account colours, mortgage beside investment loan, and the eight ticker colours pass the
  lightness band, the chroma floor, the colour-vision separation of neighbours and the normal-vision floor.
- **Known shortfalls.** Green, cyan, orange, amber, rose and lime are below 3:1 contrast on white, so every chart
  that uses them carries a legend and a table. Red beside brown among the tickers scores 7.1 for protanopia, and
  green against orange 6.2 for deuteranopia when all market lines are compared with each other; both are in the
  band that requires the legend and hover values the charts have. Navy is darker than the band for filled marks; it
  is used only for the combined portfolio's line.

## Consequences

- The Markets page changes too: its donuts and portfolio lines use the ticker and portfolio colours above.
- The Outcomes page's *Money in and out* tab changes with the flows. Its spending and Age Pension percentile bands
  keep the reference magenta and yellow, so spending is orange in the bars and magenta in its band.
- The PNG review plots of a plan follow the same constants.
- The app now has two sets of hues. A new chart of accounts, portfolios, tickers or flows takes the bold set; a
  chart of strategies or outcome tiers takes the reference set.

## Implementation and validation

- **Code:** `reporting/palette.py` (the bold set, `TICKER_COLOURS`, `BOLD_SERIES`, `portfolio_line_colours`),
  `ui/charts.py`, `ui/paths_page.py`, `reporting/plan.py`.
- **Tests:** the suite passes unchanged; `tests/test_outcomes.py` checks that every drawn flow has a colour.
- **Browser check:** a 60-year plan with a home loan and four strategies was run and the Paths, Markets and
  Outcomes pages were inspected. The README screenshots were retaken from that run.
