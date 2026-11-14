# Downloaded tickers and the return currency

Date: 2026-11-14. Status: implemented and tested;
[ADR 0061](../decisions/0061-downloaded-tickers-and-return-currency.md).
Code: `data/ticker_store.py`, `data/plan_markets.py`, `retirement/plan.py`, `ui/inputs.py`.

## Purpose

The planner's listed tickers are 36 US-dollar histories built in the sibling `financial_datasets` project. The user
asked to add any ticker from the ASX or a US exchange, to switch the currency in which returns are measured between
Australian and US dollars, and to use the full history a downloaded ticker has. This document covers how a ticker is
named, downloaded, checked and stored, how histories are converted between currencies, and what remains approximate.

## Ticker names

| Written as | Meaning | Currency | Vendor symbol |
| --- | --- | --- | --- |
| `USLCAP3x`, `VT`, ... (no suffix) | A listed ticker from `financial_datasets` | USD | not downloaded |
| `VAS.AX` | Downloaded, ASX | AUD | `VAS.AX` |
| `SPY.US` | Downloaded, a US exchange (NYSE, NYSE Arca, Nasdaq and others) | USD | `SPY` |

A downloaded name is 1 to 10 letters, digits or hyphens, then `.AX` or `.US`, in upper case. The suffix is required.
It decides the currency the vendor must report, and it keeps a US share apart from a listed dataset of the same
letters: `STT`, `ITT`, `LTT` and `COMM` are datasets, while `STT.US` is State Street's share. `ticker_name` resolves a
listed name first and otherwise requires the suffix. `.US` does not distinguish between US exchanges, because the
vendor does not; the exchange the vendor reports is stored with the history.

## Download, checks and storage

**Requirement (user).** Reuse the yfinance approach from the user's tracker script and take each ticker's full
history, starting at the first date the vendor has.

**Algorithm.** `download(symbol)`:

1. Requests `Ticker(vendor).history(period="max", interval="1d", auto_adjust=False, actions=True)` and the history
   metadata, with a 60-second timeout and up to three attempts. `period="max"` returns the longest daily history the
   vendor holds; its first priced row becomes the ticker's start date. A vendor answer that the ticker does not exist
   is not retried.
2. Checks the metadata: the returned symbol equals the requested one, and the currency is AUD for `.AX` or USD for
   `.US`. Anything else is refused.
3. Drops rows with no close or adjusted close (none are filled) and counts them. Requires unique increasing dates,
   positive prices, nonnegative dividends and at least 253 priced days.
4. Computes, for each day `t` after the first:

   ```text
   total[t]        = adj_close[t] / adj_close[t-1] - 1
   cash[t]         = dividend[t] / close[t-1]
   residual[t]     = total[t] - (close[t] / close[t-1] - 1) - cash[t]
   ```

   The vendor restates close, adjusted close and dividends for later splits, so the three are in the same share
   units. `total` is the daily total return the simulation samples; `cash` is the daily cash contribution used for
   the income share, the same definition as the listed funds' `Distribution Return`.
5. Labels each row: `observed`; `observed_cash_event` (a dividend, residual within 0.002);
   `cash_event_disagrees_with_adjustment` (a dividend, larger residual); `adjustment_without_cash_event` (no
   dividend, residual above 0.0001); `opening_price` (first row). The tolerance on dividend days allows for the
   second-order difference between the vendor's adjustment and price change plus yield. Flagged rows are kept and
   counted; they are not treated as verified.
6. Writes `<SYMBOL>.csv` and `<SYMBOL>.json` to the ticker store. The JSON records the vendor symbol, exchange, name,
   instrument kind, currency, first and last date, row counts, status counts, the largest daily move, the source and
   library version, the fetch time and the CSV's SHA-256.

**Storage.** The store is `data/local/tickers/` (ignored by git), or the folder in `FINANCIAL_SIMULATIONS_TICKERS`.
Downloads happen only from the Investments tab's Download button or
`python -m financial_simulations.data.ticker_store VAS.AX SPY.US`. A simulation never downloads: the loader reads
the stored CSV, refuses it if its hash differs from the JSON, and records the hash in the run's manifest.
Downloading a stored ticker again replaces it with the vendor's current history. A saved run keeps the return
matrix it used, so it stays reproducible after a later download.

**Dependency.** `yfinance` is the optional `download` extra. Running plans, tests and CI do not need it.

**Checked on real data (2026-11-14, yfinance 1.8.0).** `VAS.AX`: AUD, ASX, 2009-05-01 to 2026-11-13, 4,437 days, 56
cash events, none flagged. `VGS.AX`: 2014-11-18 onward, 3,034 days. `SPY.US`: USD, NYSE Arca, 1993-01-29 onward,
8,507 days, 136 cash events. `BRK-B.US`: NYSE, 1996-05-09 onward. `VAS.US` and an invented ASX code were refused. The
library's default 10-second timeout cut off the long US histories on the build machine, which is why the timeout is
60 seconds.

## Return currency

**Requirement (user).** A toggle between AUD and USD, with the conversions calculated.

`market.currency` in the plan is `"AUD"` or `"USD"`. `load_plan_markets(tickers, currency=...)` returns every
ticker's returns in that currency. With `S[d]` the AUDUSD spot rate on date `d` (US dollars per Australian dollar,
`fx_aud_usd.csv` in `financial_datasets`) and `L[d]` a ticker's total-return level:

```text
USD history, AUD chosen:  L_aud[d] = L_usd[d] / S[d]
AUD history, USD chosen:  L_usd[d] = L_aud[d] * S[d]
return[d] = L[d] / L[previous shared date] - 1
```

so, for the same pair of dates, `(1 + r_aud) * S[d] / S[previous] = 1 + r_usd`. A ticker already quoted in the chosen
currency is not touched, and when every selected ticker is, the exchange-rate file is not read.

**Dates.** Conversion uses the dates the ticker and the rate both have. No rate is carried forward to a day without
one; a step across such a day compounds the levels, the existing rule for a missing trading day. The rate file
follows BIS observation days before 1999 and ECB business days afterwards, so a few US and ASX trading days a year
have no rate. The plan's sample is then the intersection of the converted tickers' dates, as before.

**Income share.** The cash contribution proxy is the mean yearly sum of `cash[t]` over complete calendar years of
the ticker's own history, in its own currency. It is a ratio of cash to the previous price, so conversion does not
change it, and it is the same in both currency settings.

**What each setting means in the ledger.** The retirement ledger is always in Australian dollars.

- `AUD`: sampled returns are Australian-dollar returns. US-dollar histories carry the exchange rate's movements, as
  an unhedged holding does. No hedged alternative is modelled.
- `USD`: sampled returns are US-dollar returns applied to Australian-dollar balances as they stand. This is the
  convention every plan used before version 4, and it leaves exchange-rate movements out. An ASX ticker in this
  setting is converted to US dollars, so it carries the exchange rate in the opposite direction.

**Defaults.** A plan file of schema version 4 without the field, and the example plan, use `AUD`. Files of version 2
or 3 load as `USD`, so they reproduce their earlier results. `run_plan` refuses a supplied market whose currency
differs from the plan's.

**Example (real data, 2026-11-14).** Full-sample figures for three tickers:

| Ticker | Quoted in | CAGR in AUD | CAGR in USD | Daily volatility in AUD | in USD |
| --- | --- | --- | --- | --- | --- |
| `USLCAP` | USD | 11.9% | 10.9% | 19.4% | 17.1% |
| `SPY.US` | USD | 10.7% | 10.7% | 20.4% | 18.5% |
| `VAS.AX` | AUD | 8.2% | 7.8% | 14.9% | 21.3% |

`USLCAP` gains about one percentage point a year in Australian dollars because the Australian dollar fell from about
USD 1.12 in 1970 to USD 0.68. `SPY.US` starts in 1993, when the rate was close to today's.

## Franking

`franking` in the plan maps a selected ticker to the franked share of its distributions (0 to 1). `build_inputs`
passes it to the ledger's `AssetIncome.franked_fraction`, which already grosses up franked income and credits tax at
the 30% company rate ([retirement ledger](retirement-ledger.md)). The app offers the field for tickers quoted in
AUD. The default is zero, as before: the vendor data do not identify franking, so the share is the user's entry from
the fund's distribution statements, not a derived figure.

## Validation

`tests/test_ticker_store.py` uses synthetic vendor histories and a synthetic moving exchange rate; no test uses the
network. It covers name parsing and the listed-name precedence; a stored download's dates, returns, cash
contributions, status counts and hash; refusal of a wrong currency, wrong symbol or short history; dropped unpriced
rows and a flagged adjustment; refusal of a stored file that no longer matches its hash; the conversion identity
`(1 + r_aud) * S[d] / S[previous] = 1 + r_usd` for every ticker and day; absence of the days without a rate; an
unconverted ticker's returns compounding across those days; the same income share in both settings; no exchange-rate
read when none is needed; the currency default by file version; and franking reaching the ledger inputs. The shared
fixture's exchange rate is constant, which leaves every existing test's returns as they were. The full suite (299
tests) passes. A small real plan holding `VAS.AX` ran to completion in both settings.

## Limitations

- **Rate timing.** From 1999 the rate is the ECB reference rate set around 14:15 CET, several hours before the US
  close and after the ASX close. A converted single-day return therefore mixes times. It makes converted daily
  returns noisier: in the table above `SPY.US` has higher daily volatility in Australian dollars than in US dollars,
  although an unhedged Australian holder of US shares has usually seen the reverse. The offsetting move arrives in
  the next day's rate, and the block bootstrap keeps consecutive days together (mean block 63 days), so multi-day
  outcomes are affected much less than the daily statistic. This was not quantified.
- **Different closes.** ASX and US closes on the same date are 14 to 16 hours apart, so a US move appears in ASX
  prices on the next date. Same-row sampling understates the same-day link between the two markets.
- **Fewer shared days.** ASX, US and rate calendars differ. `VAS.AX` with the default tickers shares 4,306 days over
  17.5 years, about 246 a year.
- **Short histories.** The sample is the shared window. A ticker that starts in 2009 or 2014 limits the whole plan to
  those years, which contain few distinct market conditions. The app shows the window and warns below 15 years.
- **Vendor data.** Downloaded histories are not reconciled with issuer records. The first date can be later than the
  listing. A missing early distribution lowers the income share and not the total return, provided the adjusted
  close reflects it; where it does not, the total return is understated too.
- **Spot only.** The rate carries no interest. Conversion is correct for an asset's value; it does not model a
  currency-hedged fund, whose return also depends on the interest differential.
- **1970 rate.** The 1970 AUD rate is modelled from the sterling peg (upstream `methodology_fx.md`).
- **USD setting.** It is a convention kept for comparison and for older plans, not a description of an Australian
  investor's returns.

## References

- `financial_datasets/docs/methodology_fx.md`: AUDUSD construction, sources (BIS `WS_XRU`, ECB reference rates),
  quote direction and timing.
- yfinance documentation, `Ticker.history`: <https://ranaroussi.github.io/yfinance/>. Yahoo Finance data are for
  personal use under Yahoo's terms; the stored files stay on the user's machine and are not tracked.
