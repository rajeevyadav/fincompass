# FinCompass Patch and Manuscript Technical Review

**Review date:** 2026-08-23  
**Reviewed inputs:** the FinCompass application and the arXiv manuscript source (`paper/`)  
**Reviewed application version:** `1.0.0`  
**Realtime adaptive engine:** `1.0.0-adaptive1`  
**Final automated regression suite:** **72/72 passed**

## Executive assessment

The submitted patch made a correct and important methodological restoration: the Evidence-plane Cycle pillar is explicitly constrained to current, observable, causal/regime evidence and excludes fixed-calendar or deterministic cycle theories. The code already respected that principle, but the constraint had only been documentary. The reviewed build now makes the guardrail executable through regression testing.

The patch also exposed several adjacent issues that were more consequential than the original change. These have been corrected in the reviewed package. The most important was delayed-label target resolution: an online learning job could previously use the latest available close when the job happened to run, silently lengthening a nominal 252-session target when processing was late. The reviewed build now resolves the label at the exact H-th common stock/benchmark trading session after the original observation date and leaves the label pending until that endpoint is available.

The draft paper had a strong validation/governance thesis but materially under-described the implemented mathematics. It contained essentially no displayed mathematical model, conflated several Bayesian concepts at a high level, used an “open-source” characterization that was stronger than the current licensing state, and did not formalize the exact target, calibration/stacking separation, dependence-aware bootstrap, adaptive state update, date-balanced calibration gate, or fail-closed live rule. The revised manuscript addresses these gaps.

## Patch review and dispositions

| ID | Severity | Finding | Disposition |
|---|---|---|---|
| P-01 | Accepted design correction | Cycle pillar needed an explicit prohibition against fixed-calendar/non-causal market-cycle theories. | **Accepted and strengthened.** Documentation retained; a regression test now checks the executable Cycle signature/source for prohibited calendar dependencies. |
| P-02 | Major | Matured labels were resolved using the latest available price when the background job ran, allowing scheduler delay to extend the intended forward horizon. | **Fixed.** Target endpoint is now the exact H-th common stock/benchmark trading session after the observation date, constrained by processing as-of date. |
| P-03 | Major | Online Brier/log-loss metrics were date-balanced, but ECE remained row-weighted. A large same-day cross section could therefore dominate the calibration gate. | **Fixed.** Online ECE now assigns equal total mass to each observation date and divides that mass among rows from the date. |
| P-04 | Moderate | SEC realtime event time used a filing-date proxy even when EDGAR acceptance time was available. | **Fixed.** `acceptanceDateTime` is preferred; filing-date fallback remains for missing values. |
| P-05 | Moderate | `/api/v1/settings/schema` reported stale realtime engine version `1.0.0-adaptive1`. | **Fixed.** Schema now derives the value from the executable `REALTIME_ENGINE_VERSION`; API regression assertion added. |
| P-06 | Moderate | Patch/review tree accumulated cache/runtime packaging residue during execution. | **Fixed for distribution.** Caches, bytecode and runtime DB/audit sidecars are excluded/removed before final manifest generation. |
| P-07 | Moderate | Application/realtime version text and adaptive artifact identifiers could drift across documents after semantic changes. | **Fixed.** Release verifier checks application version, realtime engine, artifact ID/hash/settings fingerprint and frozen fixture metrics against generated artifacts. |
| P-08 | Governance | The original paper called the implementation “open-source,” while the project does not yet define a specific open-source redistribution license. | **Fixed in paper.** Described as a source-available/reference implementation rather than asserting an unselected license. |

## Statistical contract after review

### 1. Evidence plane

Each raw metric is mapped continuously to a bounded 0–10 score, optionally blended with a robust peer-relative score using median/IQR context. Pillar evidence is aggregated through a fractional Beta model:

\[
\alpha_p=\alpha_0+c\sum_j w_jq_j,\qquad
\beta_p=\beta_0+c\sum_j w_j(1-q_j),\qquad
S_p=10\frac{\alpha_p}{\alpha_p+\beta_p}.
\]

The posterior represents uncertainty in the **FinCompass evidence score**, not a probability of future market outperformance. Sparse evidence shrinks toward the neutral prior instead of producing falsely precise extreme scores.

### 2. Frozen forward-probability anchor

The empirical target remains:

\[
Y_{i,t}^{(H,\tau)}=\mathbf 1\left\{R_{i,t}^{(H)}-R_{b,t}^{(H)}>\tau\right\},
\]

with a strict reference profile of 252 trading sessions, SPY benchmark and zero excess-return hurdle. The anchor combines:

- Bayesian logistic regression with Gaussian priors and Laplace posterior covariance;
- histogram gradient boosting;
- random forest;
- chronologically separated component calibration;
- constrained Brier-optimal stacking;
- a later final calibration stage;
- a locked test set not used for fitting.

Every temporal boundary is purged and embargoed.

### 3. Dependence-aware validation

The locked test is evaluated with moving blocks of complete observation dates while retaining all same-date securities together. The automatic block length is

\[
L=\left\lceil H/\Delta\right\rceil,
\]

which is 12 observation dates for a 252-session horizon sampled every 21 trading days. This preserves the principal serial dependence induced by overlapping targets and same-date cross-sectional dependence better than an iid row bootstrap.

### 4. Adaptive realtime residual

The live candidate is a bounded log-odds correction to the validated anchor:

\[
\delta_t=\operatorname{clip}(z_t^\top m_t,-\kappa,\kappa),
\]

\[
p_t^C=\operatorname{clip}\left[\sigma\left(\operatorname{logit}(p_t^A)+\delta_t\right),\epsilon,1-\epsilon\right].
\]

With default \(\kappa=0.75\), adaptive odds can move by at most approximately 0.47× to 2.12× relative to anchor odds before probability clipping.

Fresh information can change the **candidate** immediately. Parameter learning occurs only after the original forward target matures.

### 5. Sequential Gaussian update

The adaptive posterior uses a local dynamic logistic/Laplace-style approximation. With forgetting factor \(\lambda\), process noise \(q\), \(v_t=P_t^-z_t\), \(w_t=p_t^C(1-p_t^C)\), and \(D_t=1+w_tz_t^\top v_t\):

\[
P_t^-=P_{t-1}/\lambda+qI,
\]

\[
P_t=P_t^- - \frac{w_t}{D_t}v_tv_t^\top,
\qquad
m_t=m_{t-1}+\frac{v_t}{D_t}(y_t-p_t^C).
\]

This is an approximate sequential Gaussian update using the rank-one Woodbury/Sherman–Morrison form; it is **not** represented as exact conjugate Bayesian logistic inference.

### 6. Exact delayed-label invariant added in this review

Let \(\mathcal T_{i,b}(t)=\{u_1<u_2<\dots\}\) be the common stock/benchmark trading sessions strictly after observation date \(t\). The label endpoint is now fixed as:

\[
\tau_H(t)=u_H.
\]

If \(u_H\) is not available by the job’s as-of date, the label remains pending. A late worker therefore cannot transform a 252-session target into 253, 260 or more sessions.

### 7. Date-balanced online calibration added in this review

For observation date set \(\mathcal D\) and rows \(\mathcal I_d\) on date \(d\), each row receives weight

\[
a_i=\frac{1}{|\mathcal D|\,|\mathcal I_{d(i)}|}.
\]

Online ECE now uses these weights, so one date cannot dominate calibration simply because more tickers were observed that day.

## Final regression evidence

### Frozen anchor synthetic locked test

| Metric | Value |
|---|---:|
| Samples | 2,304 |
| Brier score | 0.217727 |
| Brier skill | +11.7815% |
| Log loss | 0.623959 |
| Log-loss skill | +9.1430% |
| ROC AUC | 0.699801 |
| Average precision | 0.623286 |
| ECE | 0.035934 |
| Calibration slope | 0.800691 |

The 90% dependence-aware bootstrap retains positive lower bounds for both Brier skill (0.108977) and log-loss skill (0.083429). All four purged walk-forward folds show positive Brier skill; median fold Brier skill is 0.130271.

### Adaptive synthetic locked stream

| Metric | Frozen anchor | Adaptive | Improvement |
|---|---:|---:|---:|
| Brier score | 0.235658 | 0.204069 | +0.031588 |
| Log loss | 0.664106 | 0.596988 | +0.067118 |

The final 250-date gate spans 498 days, reports Brier improvement 0.037821, log-loss improvement 0.079019, date-balanced ECE 0.061924 and no drift alert.

**These artifacts remain `fixture_only`.** They validate code paths and statistical mechanics, not market alpha. The release contains no live-eligible market anchor and no live-eligible adaptive state.

## Manuscript review and upgrade

The revised paper is materially different from the submitted draft:

- expanded from 8 to 19 pages;
- replaced qualitative descriptions with the implemented mathematical model;
- added a formal information-filtration/target contract;
- separated Evidence-plane Bayesian uncertainty from empirical return-event probability;
- derived the fractional-Beta evidence aggregation and sparse-evidence shrinkage behavior;
- formalized peer-relative IQR scoring and dependence-sensitivity envelope;
- fully specified Bayesian logistic MAP/Laplace inference;
- formalized constrained Brier-optimal ensemble stacking and calibration staging;
- formalized purge/embargo conditions and locked-test governance;
- formalized moving-date-block/cross-sectional cluster bootstrap;
- listed the exact 13-feature adaptive vector;
- formalized freshness decay and source-verification semantics;
- derived the bounded log-odds/odds-ratio adaptive correction;
- formalized the sequential rank-one covariance/mean update;
- added exact-horizon matured-label semantics from the reviewed fix;
- added date-balanced online Brier/log loss and ECE;
- formalized the adaptive activation gate and fail-closed live rule;
- correctly framed the drift statistic as an engineering deterioration guardrail rather than a calibrated hypothesis test;
- added reproducibility/governance tiers and artifact-lineage discussion;
- added synthetic locked-test tables with explicit claims boundaries;
- expanded limitations to cover point-in-time universe reconstruction, delistings, corporate actions, macro vintages, data snooping and test-set renewal.

## Remaining external validation work

The mathematics and software are now substantially more defensible, but the transition from `fixture_only` to a real market validation tier still requires a genuinely point-in-time historical dataset with documented evidence for:

1. feature availability timestamps;
2. historical universe/survivorship reconstruction;
3. delisted securities and delisting outcomes;
4. corporate-action-adjusted prices;
5. benchmark consistency;
6. historical macro vintages rather than present-day revised history;
7. pre-registered/frozen target and analysis protocol before opening the confirmatory locked test.

Until those controls exist and the real model passes the existing gates, the correct system behavior is to remain fail-closed for live probabilistic forecasting.
