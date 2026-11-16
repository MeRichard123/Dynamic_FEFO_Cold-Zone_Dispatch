# Kinetic calibration source audit

**Update:** the user supplied the original Word supplement. The previously
missing literature-parameter evidence has been reviewed and imported. The
primary workflow now uses S5/S8 observed shelf-life endpoints and the S17 orange
shelf-life/Q10 prior. See [paper-parameters.md](paper-parameters.md) for source
hash, units, superscript handling, normalization and model limitations.

The earlier Kaggle estimated-freshness fit remains unsuitable as evidence of
measured species-specific spoilage. Its three fits underperform their held-out
constant-mean baselines. It is retained only as an explicitly estimated-target
experiment and no longer supplies the primary paper-backed corpus.

The supplement does not resolve independent field validation or supply banana/
tomato kinetics. It provides sufficient provenance for the three-fruit
literature-conditioned Stage 1 prototype; generated labels remain simulation
outputs, not demonstrated food-safety decisions or measured warehouse savings.

## Historical source check

## Linked paper

[Zou et al. (2025)](https://doi.org/10.1016/j.jfoodeng.2025.112577),
Section 2.2.3 and Figure 2, separates temperature prediction from prior kinetic
parameters and initial quality. Equation (1) supplies the implemented linear
temperature dependence; it does not itself supply the current three products'
measured rates or rejection thresholds. The paper refers to supplementary
Annex II for further kinetic detail. Publisher retrieval was initially denied; the subsequent local supplement
has now been inspected and its applicable tables verified.

The accessible manuscript's cited strawberry/litchi/apple parameter sources
include theses; their experimental tables have not been verified. Reported
shelf-life prediction performance is not a substitute for product parameters.

## Independent primary source checked

[The kinetics of strawberry quality changes during shelf-life, Table 2](https://archive.conscientiabeam.com/index.php/68/article/download/3304/7485)
reports zero-order strawberry weight-loss coefficients of 0.93 at 4 C and 1.66
at 10 C, in an eight-day experiment at approximately 90% RH. These refer to a
specific quality trait. A normalized spoilage-life model additionally needs
its initial trait value, rejection threshold and validated applicability range.
Those weight-loss coefficients do not establish banana/tomato rates or a
microbiological spoilage endpoint. They have not replaced the current seed fit.

## Resolution of the earlier gap

The supplied supplemental tables close the literature-parameter gap through
explicit normalization and endpoint-based quality rates. Details are recorded
in `runs/stage1/paper-template.literature.json` and the linked parameter guide.
New measured quality trajectories can still be fitted through `calibrate`, but
are no longer required to reproduce the source-backed prototype.
