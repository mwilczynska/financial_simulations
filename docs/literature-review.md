# Simulation methods for portfolio futures and Australian retirement

Reviewed: 28 October 2026. Scope: a targeted literature review to choose methods for this project, covering market-path generation, long-horizon uncertainty, retirement spending and Australian institutional modelling. This is not an exhaustive systematic review or an empirical comparison of implementations.

The initial application is one Australian tax-resident individual, followed by couples. The task combines a long early-retirement bridge funded outside super with subsequent use of super, potentially alongside continuing outside investments.

Project requirement, confirmed 28 October 2026: use daily returns throughout calibration, resampling, generated paths and portfolio/retirement accounting. Monthly and annual results are summaries of the daily paths. This requirement changes the implementation frequency; it does not imply that every cited study used daily data or that lower-frequency economic inputs become observed daily data.

## Main recommendation

Build an explicit deterministic baseline, contiguous historical replay, a joint block bootstrap and a simple correlated parametric model. Add transparent return/inflation sensitivity and long-run parameter uncertainty early. Use the resulting market paths with a separate account, tax and spending engine.

Treat the stationary bootstrap as the initial stochastic workhorse to investigate, not an established best predictor. Keep historical replay as an interpretable reference and the parametric model as a contrasting assumption set. Complex regime, macroeconomic and volatility models should earn inclusion through a specific planning question and validation.

These build priorities are a synthesis for this project's data and objectives. The papers below do not establish one universally superior retirement simulator.

## What the model families mean

Monte Carlo describes repeated sampling and evaluation. It does not identify the financial model being sampled. Drawing independent returns, drawing historical blocks and drawing from a regime-switching model can all be Monte Carlo simulations.

The proposed piecewise historical chunks correspond to block bootstrapping. In this project, blocks consist of consecutive daily return observations. The important choices are how long the chunks are, how boundaries are treated and whether all assets and economic factors use the same historical dates. Any daily representation of lower-frequency economic factors needs its own documented alignment and resampling convention.

| Family | Main value here | Main limitation | Proposed role |
| --- | --- | --- | --- |
| Deterministic compounding and cash flows | Makes assumptions and accounting inspectable; gives exact validation cases | Hides sequence and market uncertainty | Build first as a reference |
| Contiguous historical replay | Preserves actual joint sequences, inflation episodes and crises in the available sample | Few complete long windows; overlapping windows; sample/country dependence | Build first |
| Independent joint-row bootstrap | Preserves contemporaneous empirical cross-asset relationships and observed one-period distributions | Breaks serial patterns and persistent inflation/volatility | Diagnostic comparator |
| Moving-block bootstrap | Preserves sequences inside fixed consecutive blocks | Artificial boundaries; block length and stationarity assumptions matter | Build as transparent block comparator |
| Stationary bootstrap | Uses randomly sized consecutive blocks; avoids one fixed chunk size | Still assumes historical dependence is informative; truncates dependence and inherits limited shock support | Initial stochastic workhorse to test |
| Correlated daily log-return / lognormal benchmark | Simple, fast, allows explicit expected-return scenarios | Independent periods and thin-tail assumptions can miss persistent stress | Early benchmark, not sole result |
| Long-run parameter uncertainty | Represents uncertainty about the assumptions underlying every simulated year | Requires defensible scenario ranges or priors | Early scenario layer; probabilistic version later |
| Regime-switching process | Can represent persistent states with different returns, volatility and correlations | Few independent regime episodes; unstable state estimation and extrapolation | Later candidate |
| GARCH / stochastic volatility / filtered residual bootstrap | Represents volatility changing after shocks; relevant to daily leverage and near-term stress | More estimation and validation; does not by itself resolve long-run expected returns or inflation | Later if daily risk is central |
| Joint macroeconomic generator, such as a Wilkie-type model or small VAR | Links inflation, wages, yields/cash and investment outcomes | More data and parameters; potential sensitivity to economic-era changes | Natural later Australian extension |
| Historical and hypothetical stress overlays | Explores explicitly bad combinations and novel shocks | An imposed scenario has no automatic probability | Include early as separately labelled scenarios |
| Dynamic spending / lifecycle optimisation | Evaluates responses to outcomes and trade-offs in consumption and bequests | Needs a validated account engine and a clear objective | Simple policies in Stage 2; optimisation later |

For bootstrap models, preserving an observed bad day does not establish that all relevant tails have been captured. Repeated blocks can produce cumulative outcomes worse than a historical window, but cannot invent a new daily shock outside their sampled support without an additional model. Block methods are not automatically more conservative than independent draws.

## Primary literature and implications

Access notes distinguish accessible original text from abstracts/records. This review has not independently reproduced proofs, numerical experiments or a complete Australian tax specification.

### 1. Historical sequences and fixed real withdrawals

William P. Bengen (1994), *Determining Withdrawal Rates Using Historical Data*, Journal of Financial Planning. The [publisher's 2004 reprint](https://www.financialplanningassociation.org/sites/default/files/2021-04/MAR04%20Determining%20Withdrawal%20Rates%20Using%20Historical%20Data.pdf) reproduces the original work and was available as searchable text.

The paper tests retirement withdrawals against historical stock, bond and inflation sequences rather than relying on average growth. It motivates retaining complete sequences and testing retirement start dates. Its US history and specified allocation/spending assumptions do not establish a withdrawal rate for an Australian early retiree with separate accessible and preserved accounts.

**Project implication:** historical replay and constant real spending are essential reference cases; their success frequencies remain conditional on the sample and policy.

### 2. Resampling dependent time series

Dimitris N. Politis and Joseph P. Romano (1994), *The Stationary Bootstrap*, Journal of the American Statistical Association 89(428), 1303-1313. [Publisher abstract and bibliographic record](https://doi.org/10.1080/01621459.1994.10476870); [Stanford technical-report record](https://statistics.stanford.edu/technical-reports/stationary-bootstrap). The accessible abstract describes the method; full proofs were not assessed here.

The method constructs resampled series from consecutive blocks with geometrically distributed lengths, for inference with weakly dependent stationary observations. That supplies a principled alternative to independent observations when temporal dependence matters. Its inference results are not a guarantee that future financial markets follow the historical process.

**Project implication:** use common block indices across the full asset/factor vector; vary expected block length and record the stationarity assumption.

### 3. Block length is a modelling decision

Politis and Halbert White (2004), *Automatic Block-Length Selection for the Dependent Bootstrap*, Econometric Reviews 23(1), 53-70, [publisher record](https://doi.org/10.1081/ETC-120028836), and Andrew Patton, Politis and White (2009), [published correction](https://public.econ.duke.edu/~ap172/Patton_Politis_White_2009.pdf), Econometric Reviews 28(4), 372-375. The records/abstracts and correction introduction were checked; no selection algorithm was implemented or audited.

These papers address data-dependent block-size selection, with the later paper correcting the earlier calculations and algorithm. The criterion concerns statistical estimation under assumptions; a computed block size is not automatically optimal for a long-horizon retirement spending-shortfall functional.

**Project implication:** include block-length diagnostics and sensitivity first. If automatic selection is added, use the corrected method and check several relevant statistics, including persistence in squared returns and inflation.

### 4. Time-varying volatility

Tim Bollerslev (1986), *Generalized Autoregressive Conditional Heteroskedasticity*, Journal of Econometrics 31, 307-327. [Author-hosted published paper](https://public.econ.duke.edu/~boller/Published_Papers/joe_86.pdf), with model definition and stationarity discussion accessible.

GARCH lets conditional variance depend on prior shocks and conditional variances. It supplies a parsimonious way to represent changing volatility rather than assuming the same variance every period.

**Project implication:** consider GARCH or filtered residual resampling for daily leveraged strategies or near-term risk. The choice should depend on demonstrated planning value; it does not settle long-run drift, structural change or tax modelling.

### 5. Market regimes and correlations

Andrew Ang and Geert Bekaert (2002), *International Asset Allocation With Regime Shifts*, Review of Financial Studies 15(4), 1137-1187. [Publisher abstract](https://academic.oup.com/rfs/article-abstract/15/4/1137/1568247) and [original NBER working-paper abstract](https://www.nber.org/papers/w7056) were reviewed.

Their international-equity model permits states with different expected returns, volatility and correlations, including adverse high-volatility conditions. It demonstrates the relevance of changing joint distributions to asset allocation within its setting.

**Project implication:** regime models are relevant later, especially for persistent stress. Their equity findings should not be assumed to identify the correct regime model for this project's stock/bond/gold/commodity/FX system. Compare state stability and outcomes with the simpler generators before adopting one.

### 6. Long-horizon expected-return uncertainty

Lubos Pastor and Robert F. Stambaugh (2012), *Are Stocks Really Less Volatile in the Long Run?*, Journal of Finance 67(2), 431-478. [Publisher text](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.2012.01722.x) and [NBER record](https://www.nber.org/papers/w14757) were accessible.

Their analysis shows that uncertainty about expected returns and imperfect predictors can outweigh the risk-reducing effect of mean reversion in long-horizon predictive variance. This is a model-based result, not a universal statement that every asset's annualized risk must increase with horizon.

**Project implication:** distinguish uncertain long-run assumptions from ordinary return shocks. Begin with scenario ranges and sensitivity. Avoid presenting a large simulation count around one precisely estimated mean as strong evidence about a 40-60-year future.

### 7. Australian retirement and joint economic scenarios

Brendan Price and Albert Suryadi (2011), *New Treasury Stochastic Modelling of Australian Retirement Incomes*, prepared for the Institute of Actuaries of Australia Biennial Convention. [Original Treasury report](https://treasury.gov.au/sites/default/files/2019-03/Stochastic_modelling_of_Aus_retirement_incomes.pdf), with methods and model-linking discussion accessible.

The report links RIMHYPO's individual/couple tax, super and social-security calculations to a Wilkie-type model of inflation, wages and investment outcomes. It also examines outcomes beyond a simple terminal-wealth measure, including years of financial difficulty in the presence of the Age Pension.

**Project implication:** separating economic paths from Australian personal-account rules has a directly relevant precedent. The 2011 legislation, calibration adjustments and tax approximations are historical choices, not current parameters to copy. A joint Australian economic generator is a useful later extension.

### 8. Spending and bequests have different values

Jason S. Scott, William F. Sharpe and John G. Watson (2009), *The 4% Rule — At What Price?*, Journal of Investment Management 7(3), 31-48. [Publication record](https://www.gsb.stanford.edu/faculty-research/publications/4-percent-rule-what-price) and [author manuscript, dated April 2008](https://web.stanford.edu/~wfsharpe/retecon/4percent.pdf), including the argument and assumptions, were accessible.

The authors examine the economic trade-offs of funding fixed real spending with risky investments and the different implications of shortfalls and unspent surpluses. Their efficiency analysis depends on a specified economic framework.

**Project implication:** assess actual consumption, shortfall severity and remaining wealth separately. A strategy that maximizes survival of a positive account balance need not best meet a person's spending and bequest preferences.

### 9. Adaptive spending policies

Jonathan T. Guyton and William J. Klinger (2006), *Decision Rules and Maximum Initial Withdrawal Rates*, Journal of Financial Planning, March. [Publisher article](https://www.financialplanningassociation.org/article/journal/MAR06-decision-rules-and-maximum-initial-withdrawal-rates) and [original article PDF](https://www.financialplanningassociation.org/sites/default/files/2021-11/2006%20-%20Guyton%20and%20Klinger%20-%20Decision%20Rules%20and%20SWR%20%281%29.PDF), including decision-rule definitions, were accessible.

The paper evaluates rules that alter spending after favourable or adverse portfolio outcomes, including preservation and prosperity guardrails. It explicitly considers purchasing-power maintenance alongside the chance of sustaining withdrawals.

**Project implication:** implement the mechanism as one candidate policy, with configurable parameters. Compare cut sizes and duration against an essential-spending floor. Published withdrawal-rate improvements depend on their data and assumptions and should not be imported as Australian planning targets.

### 10. International evidence and sample dependence

Aizhan Anarkulova, Scott Cederburg, Michael S. O'Doherty and Richard Sias (2025), *The safe withdrawal rate: evidence from a broad sample of developed markets*, Journal of Pension Economics and Finance 24(3), 464-500. [Published article record](https://doi.org/10.1017/S1474747225000010) and [authors' institutional abstract](https://experts.arizona.edu/en/publications/the-safe-withdrawal-rate-evidence-from-a-broad-sample-of-develope/) were checked. The complete published methods were not assessed; the published version is distinguished from earlier working papers.

Using a sample covering 38 developed countries, this work challenges conclusions drawn from a narrow successful-market history. It reinforces that market/sample selection can change retirement risk conclusions materially.

**Project implication:** treat international and historical-sample sensitivity as a substantive issue, not just simulation noise. The current long-history proxies are useful, but resampling them many times cannot remove source reconstruction or market-selection effects. Do not adopt a headline withdrawal percentage without matching the study's full assumptions and the Australian account problem.

## Synthesis: choices for this project

The first build should expose important assumptions with few moving parts. Historical replay, block resampling and a simple parametric generator make different assumptions about sequences and distributions. Their disagreement is useful; no one method should be labelled the true future.

All initial generators will operate on daily returns. Block lengths are counted in trading observations; annual assumptions need an explicit translation to the daily model; calendar-day cost accrual remains separate from the count of trading observations. Daily resolution is a project requirement and supports inspecting path-dependent costs and dated events. It is not, by itself, evidence of better long-horizon predictive accuracy. Each implemented method will have a detailed methodology document and linked decision records with references where available.

More sophisticated generators should be selected through an explicit question. A regime model might help assess a prolonged inflation/equity-bond stress environment. A daily volatility model might matter for resetting leverage. A joint macroeconomic model might better connect wages, super contributions, cash yields and inflation. These are separate needs rather than a requirement to build the most complex generator first.

Forward-return assumptions deserve attention before adding a large number of fitted states. Long-run mean estimation is difficult, especially when history includes reconstructed data and major changes in policy or fund structure. A transparent low-return scenario may be easier to interpret than a finely estimated model whose uncertainty is omitted.

The retirement simulation has two linked problems: funding the accessible bridge and funding later life. An account-level engine is necessary because strong total wealth does not imply that money can legally be used when required. Withdrawal-source rules, contributions and pension commencement also change taxes and future flexibility.

Spending policies belong outside the market generator. Compare fixed real spending, a percentage of current wealth and guardrails on the same economic paths. A rule should only use information available at its decision date, without foreknowledge of later simulated returns.

## Model selection and validation protocol

1. Verify accounting with hand-calculated deterministic cases before evaluating statistical models.
2. Compare historical and simulated marginal returns, dependence, volatility clustering, drawdowns, inflation persistence and joint adverse conditions. A good fit to mean and standard deviation is insufficient.
3. Fit with rolling training windows and assess subsequent observed periods where feasible. Keep portfolio selection and model evaluation separate enough to expose selection bias.
4. Test sensitivity to source segment, historical window, block length, assumed future returns, inflation and model family. Avoid turning these choices into a search for the highest reported success rate.
5. Use common economic draws for paired strategy comparisons within each generator. Use multiple seeds to assess numerical stability.
6. Label conditional simulation frequencies, finite-simulation error, parameter uncertainty and model disagreement separately. They answer different questions.
7. Evaluate realistic long horizons and actual spending needs. Report the distribution of shortfalls, not just account depletion.
8. Preserve each model's source, parameters, seed and input hashes so that a surprising result can be inspected and reproduced.

## Australian sources required alongside the literature

These sources inform data and institutional assumptions, not a claim that a full legal implementation is complete:

- [ASIC Moneysmart: what happens to super at retirement](https://moneysmart.gov.au/plan-for-your-retirement/what-happens-to-your-super-when-you-retire) explains access conditions and the available combinations of super use. Its page was updated 30 September 2026.
- [ASIC Moneysmart: account-based pensions](https://moneysmart.gov.au/retirement-income-sources/account-based-pensions) describes minimum annual payments, transfer restrictions and the distinction between payments, investments and Age Pension assessment. A sourced legal rule register should precede implementation.
- [Services Australia: Age Pension](https://www.servicesaustralia.gov.au/age-pension) identifies age, means-test and residence eligibility. Eligibility must be separately represented rather than inferred from Australian tax residency.
- [ABS: CPI transition, October 2025](https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/consumer-price-index-australia/oct-2025) documents the transition to complete monthly CPI. Older quarterly data must not be mistaken for independently observed monthly inflation.
- [RBA historical data](https://www.rba.gov.au/statistics/historical-data.html) provides daily and monthly FX histories with different coverage. Currency conversion must respect quote direction and joint sampling.
- [ABS life expectancy methodology, 2022-2024](https://www.abs.gov.au/methodologies/life-expectancy-methodology/2022-2024) identifies the tables as period tables without assumed future mortality improvements. Mortality and longevity-improvement scenarios should therefore be explicit.
- [ASIC account-based pension calculator](https://moneysmart.gov.au/retirement-income-sources/account-based-pension-calculator) can be a reasonableness check only after aligning its assumptions with ours; matching an external calculator is not independent proof of every rule.

## Open research decisions

- Which asset/segment pairs support a defensible income-versus-price decomposition, and which need additional data or assumptions?
- Which Australian inflation and FX histories give an adequate common calibration sample without hiding frequency changes?
- How stable are the portfolio conclusions across block lengths, historical windows and generator choices?
- Which forward-return assumption ranges are defensible for the actual assets held?
- Does a regime, volatility or macroeconomic model change a retirement decision enough to justify its complexity?
- What essential-spending floor and tolerable discretionary-spending cuts should define personal success?

These questions should be resolved incrementally through the milestones in [the project plan](../PLAN.md), with the simplest validated model supplying a working comparison at each stage.
