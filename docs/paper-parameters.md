# Supplement-backed Stage 1 kinetic profile

Source: [Zou et al. (2025), DOI 10.1016/j.jfoodeng.2025.112577](https://doi.org/10.1016/j.jfoodeng.2025.112577),
user-supplied `1-s2.0-S0260877425001128-mmc1.docx`.
SHA-256: `fd56de4d5ea43d55aabe331461e1d33d7b7864db8052e273919253b56387a43a`.
The importer reads the Word XML tables and omits numeric superscript citation
markers before interpreting parameter values. No extra Python package is needed.

## Imported evidence and explicit model choices

| Product | Supplement evidence | Implemented model |
| --- | --- | --- |
| Strawberries | S5 observed shelf life: 18, 11.1, 7, 4.2, 2.8 days at 4, 10, 15, 20, 25 C | Piecewise-linear quality rate through reciprocal observed lives |
| Apples | S8 b* observed shelf life: 240, 171, 78, 36 days at 0, 5, 15, 25 C | Piecewise-linear quality rate through reciprocal observed lives |
| Oranges | Annex II citrus paragraph: 56 days at 4 C; S17 Q10 = 2 | Normative full-budget 1,344 reference hours at 4 C with the main paper's linear Q10 factor |

The first two models are calibrated to published constant-temperature lifetime
endpoints. They are not fitted to the weak Kaggle estimated-freshness targets.
Orange kinetics are a stated literature prior, not a newly measured batch fit.
The supplied material does not provide banana or tomato parameters: those
products remain in the earlier explicitly synthetic/surrogate examples.

For published life L_i in hours at temperature T_i, define a unit remaining
quality budget q and the constant-temperature loss rate r_i = 1/L_i per hour.
Interpolate r(T) linearly between the published points. With reference
T_ref = 4 C, reference-life hours H = q/r(T_ref). Over a simulation interval,
subtract average(r(T_start), r(T_end))/r(T_ref) × interval_hours from H.
Estimated remaining life at the current temperature is H × r(T_ref)/r(T).
Reject stock when the normalized budget reaches zero.

This is an explicit extension of the additive zero-order/3T method in the main
paper, using its supplemental endpoint data. It does not claim to reproduce
the paper's exact fitted decay-index or b* trajectory, or its LSTM temperature
predictor. Absolute trait rejection thresholds are not invented: the normalized
endpoint is tied to the reported observed shelf life. Dynamic-temperature
additivity and between-temperature interpolation remain modeling assumptions.

Curve extrapolation is rejected. A 1e-9 C tolerance handles integration
roundoff at an endpoint only. Apples and strawberries carry their curves into
both dispatch and simulation; their retained scalar Q10 values are provenance
and do not override the curve. Scalar Q10 remains active for oranges.

## Why the printed k0 values were not copied

S17 labels k0 as %/minute. Applied for its recommended shelf-life duration, the
printed rate × minutes equals approximately 2.000 for strawberry, 0.500 for
lychee, 1.000 for orange and 1.002 for apple. If those rates are instead read
literally as percent per minute, the fractions of a full 100% budget are about
0.020, 0.005, 0.010 and 0.010. Neither interpretation reconciles all four rows
to a common unit budget. Unreported trait-specific initial quality could matter;
this check does not establish that a particular entry is a typo.

The importer preserves these numbers and diagnostics in the literature report,
but derives dimensionally explicit rates from lifetime endpoints instead.
It also correctly reads strawberry's second Q10 as **2.13**, not 12.13, and
apple's as **2.59**, not 42.59: the extra digits are superscript citations.

## Warehouse profile and scope

`paper-profile` retains all PMC aisle-to-zone mappings and uses three explicit
scenario temperatures: apples at 0 C, oranges at 2 C, strawberries at 4 C.
Static target choices are [0,1], [2,3] and [4,5] C. Thermal capacities, heat
conductances, COP, picker speed and these zone assignments remain scenario
parameters, not calibrated facility measurements.

The strawberry 4–5 C handling zone is deliberately within the empirical curve
and is warmer than S17's stated optimal 0–3 C storage range. It is an experimental
planning case, not a new storage recommendation. Strawberry handling bounds
are 4–10 C; apple/orange bounds are 0–4 C. Reported reference-temperature
lifetimes are approximately 4,354.38 h for apple, 1,344 h for orange and 432 h
for strawberry. Apple reference life is obtained by reciprocal-rate interpolation
at 4 C, not by linearly interpolating days.

This resolves the missing literature-parameter provenance for the Stage 1
simulation/data-augmentation workflow. Independent validation on new cultivars,
warehouse batches and real product temperatures remains future experimental
work. Neither these priors nor generated kg-food-saved labels establish food
safety, measured field savings, or a trained LLM's performance.
