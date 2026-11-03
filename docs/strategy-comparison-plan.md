# Plan: comparing retirement spending strategies

Status: stages 0 and 1 implemented on 2 November 2026 (ADR 0040 and ADR 0041); stage 2 implemented (ADR 0042: a default
run about 2.6 times faster); stage 3 implemented (ADR 0043); stage 4 implemented (ADR 0044); stage 5 implemented (ADR 0045); stage 6 implemented (ADR 0046); stage 7 (documentation and validation) has
been done with each stage.
Written 2 November 2026.

## Requirements (from the user)

- Compare up to four spending strategies, each with its existing input options, and hold every other plan input
  constant:
  1. Fixed: the same buying power every year (the default)
  2. Guyton–Klinger guardrails
  3. Vanguard ceiling and floor
  4. A percentage of wealth each year
- The user ticks which strategies to compare.
- Every ticked strategy runs on **all** retirement-ledger paths. Speed must not come from using fewer paths.
- Remove these plots: "Below previous peak" (both of them), "Calendar-year return after inflation", and everything
  under "How much could each portfolio pay out each year?".
- A headline comparison section:
  - median wealth over time, with every strategy on one plot;
  - median withdrawals over time, with every strategy on one bar chart, and a dropdown to switch to the other
    variables in "Money in and out in a typical year".
- Below that, one tab per strategy, each showing the current single-strategy results.

## Stage 0 · Means versus medians (first)

### What the app does now

- Section 4 already uses medians and percentiles: fan charts, metric tiles, the "Money in and out in a typical year"
  bars. Shares such as "paths that ran out" are means of yes/no indicators, which is correct.
- Means appear in one place: section 5's path groups ("Worst 1%" to "Best 1%") in `averaged_paths`, for the tiles,
  the account balances chart, the money in/out bars and the year-by-year table.

### Recommendation

| Quantity | Use | Why |
| --- | --- | --- |
| Wealth or balances across all paths | Median, with percentile bands | The leveraged portfolios give a long right tail. A few very good paths pull the mean well above what a typical path experiences. With 1,000 paths the mean of a skewed quantity is also noisier than the median. |
| Quantities that are usually zero (spending shortfall, Age Pension received, Division 296, unpaid tax) | Share of paths above zero, plus the median **among those paths** | The median is often exactly $0, which hides the risk. **"Median spending shortfall" and "Median Age Pension received" are probably misleading now.** |
| Stacked money in/out bars | Keep medians, and keep the caption saying they don't add up | Means would add up but would be skewed. The current choice is defensible. |
| Path groups (section 5) | Medians for tiles, balances and the table. Keep means only for the stacked flow bars, labelled, because the bars there are meant to add up. | Narrow groups (45th–55th) barely change. Open-ended groups ("Best 10%", "Best 1%") can be dominated by one extreme path. |
| Strategy comparison (stage 4) | Median, plus an optional 10th-percentile line | Spending rules differ mostly in bad markets. The median alone can make them look alike. |

This stage is small and independent. It needs an update to `docs/methodology/plan-and-app.md` and a short ADR.

## Stage 1 · Remove the plots

- `section_historical`: the drawdown chart ("Below previous peak") and the calendar-year return bars (decided:
  remove both).
- `section_future`: the drawdown chart and the "Calendar-year return after inflation" band chart.
- `withdrawal_rates_section` ("How much could each portfolio pay out each year?").
- Remove the matching PNGs from `reporting/plan.py` so the interactive charts and the PNGs stay consistent.

**Decided: remove the withdrawal-rate calculation as well.** The sustainable and capital-preserving withdrawal
rates also feed the caption "Estimated chance of running out by age N" in section 4, so these go together:

- the calculation;
- the caption;
- `assumptions.planning_age`. Old plan files that contain it still load, and the value is ignored with a note.
- the stored statistics and CSVs that depend on them.

The full tax ledger is now the only answer to "does the money last". The app should say plainly when the ledger
horizon ends before an advanced age, so users extend *Years to simulate* instead of reading a short horizon as safe.
This needs an ADR. The existing withdrawal-rate ADR (0021) stays as history.

## Stage 2 · Make the ledger faster (before multiplying it by four)

### Measured on 2 November 2026 (default plan, one core, one path)

| Horizon | Ledger time per path |
| --- | --- |
| 10 years | about 0.15 s |
| 40 years | about 0.5 s |

Profiling three 40-year paths found:

- About 40% of the time is in `sell_parcels`. It sorts every parcel on every sale with a key that calls
  `taxable_per_dollar`, which calls `held_twelve_months` and `as_date` about 80,000 times. Parcels accumulate, so this
  grows faster than linearly with the horizon.
- About 10% is `_value`, a Python dictionary loop over units and prices on every day.
- About 10% is `as_date` conversions on dates that are already dates.
- About 25% is the main daily loop itself.

### Changes, each verified to give identical ledger results on fixed seeds

1. Pre-compute each parcel's 12-month date when it is acquired, and compare dates directly. Cache the parcel sort key
   per sale day instead of recomputing it inside `sorted`.
2. Store units and prices as aligned NumPy arrays so `_value` becomes a dot product, or value only on days that need
   it.
3. Skip `as_date` where the input is already a `date`.
A 2–3× speed-up looked realistic. **Outcome (ADR 0042):** the ledger itself gained only about 7% without changing
its arithmetic, but the per-path summary in each worker turned out to cost more than the ledger and became 3.4×
faster, so each path's whole worker step went from about 1.7 s to 1.0 s on one core, with identical results.

### More cores, without slowing the rest of the computer

Today `_workers` is capped at 12 worker processes. The development machine has 24 physical cores (8 performance and
16 efficiency) with 32 hardware threads, and 32 GB of RAM.

1. **Run workers at below-normal priority.** This is what actually protects the rest of the computer. Windows still
   gives the ledgers every idle cycle, but foreground programs (browser, editor, the app's own page) take precedence
   whenever they need the CPU. Each worker sets this on start-up: on Windows through `SetPriorityClass` with
   `BELOW_NORMAL_PRIORITY_CLASS` (standard-library `ctypes`, no new dependency); on other systems through `os.nice`.
   The parent Streamlit process keeps normal priority so the page stays responsive.
2. **Leave headroom in the core count.** Default to `os.cpu_count() − 4` workers (28 here), never more than the
   number of paths × strategies ÷ 4, and at least 1.
3. **Check memory before starting workers.** Measure one warmed worker's memory use and record it as a constant in
   the code with the date measured. Then limit the count to (available RAM − 4 GB) ÷ (per-worker use). Available RAM
   comes from `GlobalMemoryStatusEx` on Windows through `ctypes`. If the limit falls below the default, the progress
   message says the run is using fewer workers because of memory.
4. **Keep the overrides.** `FINANCIAL_SIMULATIONS_WORKERS` still overrides the count. The Assumptions tab gets a
   *Calculation cores* control ("Automatic" or a number) for users who want the machine quieter.
5. **Benchmark before fixing the default.** Run 12, 16, 22 and 28 workers on the 50-year plan. Efficiency cores and
   hyperthreads give diminishing returns, so the default should be the point where extra workers stop helping, not
   simply the largest number. Record the timings as validation evidence. This stage needs a regression test that compares summaries before and after on a
set of seeds. Bit-identical results are expected, because none of these changes alter the arithmetic.

## Stage 3 · Plan schema for the comparison

- `spending.rule` (one value) becomes `spending.compare`, a list of the ticked rules with at least one. The
  parameters for every rule are kept together: guardrail band and step, Vanguard ceiling and floor, minimum and
  maximum. Old plan files with a single `rule` still load as a one-item list. This needs a `schema_version` bump.
- The app's spending section has four tick boxes. Each ticked rule shows its own parameter inputs.

**Problem: the starting spending must be the same for every strategy, or the comparison is unfair.** Today the
market-responsive rules require `retirement = "percent"`, while Fixed can start from "same", "amount" or "percent".
If Fixed starts at $75,000 and Guyton–Klinger starts at 4% of wealth, the results mostly show the different starting
amounts, not the rules.

**Decided: every compared strategy starts from one shared percentage of wealth at retirement.** Fixed then holds
that starting amount's buying power. Once more than one strategy is ticked, the app sets the retirement start to
"percent" for all of them and explains why. The other start options ("same", "amount") stay available when only
one strategy is ticked.

With a single ticked strategy the app behaves as it does today.

## Stage 4 · Run every strategy on the same paths

- Each worker task takes a chunk of paths and runs **every** ticked strategy on each path. Market inputs are built
  once per path. Every strategy uses identical market draws, so the differences between strategies are paired and
  far less noisy than separate runs would be.
- The results become a dictionary keyed by strategy, each holding today's `PlanRun` fields (summaries, bands,
  annual rows, path series). The portfolio analysis (sections 1–3) runs once and is shared.
- **Expected run time:** about 0.6 s per path for a 50-year plan × 1,000 paths × 4 strategies ≈ 2,400 CPU-seconds.
  On 12 workers that is about 3–4 minutes before stage 2, against roughly 1 minute for one strategy now. After
  stage 2 (and possibly more workers) it should be about 1–1.5 minutes. These figures are extrapolated from one
  profile. I didn't time the summarising step or the worker overhead, and your observed run times are the real
  benchmark.
- **Memory:** `path_series` keeps every path's month-end balances. Four strategies × 1,000 paths × 600 months is
  about 2.4 million rows, held in the browser session and written to CSV. That is roughly 100–200 MB in pandas.
  Acceptable, but measure it. If needed, store it as float32 or Parquet.
- **Optional later step, branching at retirement:** run the accumulation years once per path and restart each
  strategy from a saved ledger state. The gain is the pre-retirement share of the horizon. **In the default plan
  retirement comes about one year after the start, so the gain is small.** It needs the ledger's internal state
  (closures over parcels, tax carry-forwards and pending liabilities) refactored into a copyable object, which is
  higher risk. Only do this if stage 2 is not enough.
- The progress bar reports paths × strategies.

## Stage 5 · Headline comparison section

Placed after section 3 (portfolio simulations), before the per-strategy tabs. It shows only the ticked strategies.

1. **Statistics table**, one column per strategy:
   - median and 10th-percentile total real spending over retirement
   - median and 10th-percentile lowest annual spending
   - share of paths with any shortfall
   - share of paths that ever spent below the start
   - median and 10th-percentile ending wealth after tax owed

   Wealth must be shown next to spending. A strategy that spends less always looks better on wealth alone.
2. **Wealth over time:** the median real total wealth for each strategy as one line, with a toggle to add the
   10th-percentile lines and milestone markers. These are pointwise statistics, so no single path follows them. The
   caption says so.
3. **Withdrawals over time:** grouped bars by financial year, one bar per strategy, showing median "Spending paid"
   by default. A dropdown switches to other flows from the money in/out data (pension payments, tax paid, Age
   Pension, take-home pay, and so on), using the same flow names and units.
   - **Readability issue:** a 50-year plan with 4 strategies has 200 bars. They fit at full width, but tooltips carry
     the detail. If it reads poorly, a step-line version is the fallback.
   - Before retirement the strategies are identical, so the chart could start at the retirement year. I suggest a
     toggle.
4. **PNG exports** of the same three items from `reporting/plan.py`, so the interactive and PNG outputs match.

## Stage 6 · One tab per strategy

- Today's section 4 (retirement outcomes) and section 5 (one path in full, with path groups) go inside
  `st.tabs([...ticked strategies])`, each fed that strategy's results. Sections 1–3 stay above, shared.
- Widget keys gain a strategy prefix so the tabs don't share selection state.
- The single-path ledger in section 5 re-runs on demand for the chosen strategy (`ledger_for_path` with that rule).
  That costs about 0.5 s per selection and needs no extra storage.
- Streamlit runs the code for every tab even when the tab is hidden. Each tab already uses fragments, so this is
  rendering cost only (about 4× today's section 4 and 5 charts). It is worth checking how responsive the page stays.

## Stage 7 · Documentation, validation and commits

- ADRs:
  - means and medians
  - removing withdrawal-rate plots (and the calculation, if chosen)
  - strategy comparison, including the shared starting basis
  - ledger performance
- Methodology: `plan-and-app.md` and `retirement-ledger.md`. Validation evidence: before/after regression, paired
  draws confirmed identical across strategies, and timings.
- Commit and push at each stage.

## Order and dependencies

Stages 0 and 1 are independent and small. Do stage 2 before stage 4. Stages 3 → 4 → 5 → 6 are sequential.

## Decisions (2 November 2026)

1. Remove both calendar-year return charts, historical and future.
2. Remove the withdrawal-rate calculation, its caption and `planning_age`.
3. Compared strategies share one starting percentage of wealth at retirement.
4. Use more cores, with protection for the rest of the computer (stage 2).

## How each known problem is handled

| Problem | Handling |
| --- | --- |
| Run time grows with four strategies on all paths | Stage 2 first: faster parcel sales and valuation (same results), more workers. Then stage 4 builds market inputs once per path for all strategies. Measure after each step, and only consider branching at retirement if a 50-year, four-strategy run is still over about 2 minutes. |
| Branching at retirement saves little for the default plan | Deferred. It is the riskiest change for the smallest gain on typical plans. |
| Strategies must start from the same spending | A shared starting percentage (decision 3). |
| Wealth alone flatters cautious strategies | The headline table puts total and lowest-year real spending first, with wealth beside them. The wealth chart caption says a strategy that spends less keeps more. |
| Usually-zero measures show a median of $0 | Stage 0: share of paths affected, plus the median among them. |
| Crowded withdrawal bar chart | Default the chart to retirement years only, with a toggle for the full horizon, which removes the identical pre-retirement bars. Check it at full width with four strategies. If it still reads poorly, switch to step lines and say why. |
| Memory for four strategies' monthly balances | Measure after stage 4. If above about 300 MB, store balances as float32 and keep only the series the charts use. |
| Four tabs rendered at once | Measure page responsiveness after stage 6. If slow, render a tab's heavy charts only after a "Show" control is used in that tab. |
| Losing "chance of running out by age N" when the horizon is short | The app warns when the ledger ends well before old age, so users extend the horizon instead of relying on a portfolio-only estimate. |
