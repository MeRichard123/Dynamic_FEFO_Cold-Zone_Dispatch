# Stage 1 validation record

**Current result:** the supplied supplement resolved the literature-parameter
provenance gap. The primary paper-backed corpus contains 60 replay-verified
rows (48 train / 8 validation / 4 test); 40 tests pass. The updated source and
normalization are in [paper-parameters.md](paper-parameters.md). The earlier
estimated-target results below are historical and remain labelled as such.

## Earlier estimated-target run

The source-backed pipeline was run after the downloaded files appeared in the
workspace. No Stage 2 visual or robotics work is included.

## Inputs actually used

- PMC ZIP: 2,292 original slot coordinates, 215,192 source pick rows and 9,707
  source waves; archive SHA-256
  `0de6901d639cae782e661ee63d479360b6942b31072e53d07bbde8313cbe9880`.
- `Cold_Chain_Logistics_Dataset.csv`: 7,000 aggregate transport records;
  SHA-256 `a25b4c3d17ae3d838ddee7fc063174f5f08f86efb439feb4003be4909185de9a`.
- `runs/stage1/generated-42.json`: saved actual Ollama response from
  `qwen2.5:7b`, Q4_K_M. Validated cooling-failure event, cool zone, minute 60
  for 30 minutes, 70% available cooling capacity. The Unsloth provider has not
  been run; the existing Ollama runtime was used.
- `data/grid-2023-01-05.json`: saved official GB API response with 17 actual
  intensity intervals covering 07:42–15:42 UTC, including clipped first and
  last intervals. The source PMC timestamps have no timezone; their UTC
  interpretation remains an explicit demo assumption.

## Downloaded-data seed fit

The source contains initial and **estimated** final freshness, not longitudinal
measured spoilage. Aggregate fitting uses constant transit-temperature exposure
and an explicit synthetic sensitivity-class/SKU mapping. These are effective
seed parameters, not measured biological rate constants.

| Synthetic SKU mapping | Training / holdout rows | Q10 | Full-budget reference hours | Holdout quality RMSE | Constant-mean RMSE |
| --- | --- | --- | --- | --- | --- |
| High → strawberries | 1,568 / 393 | 2.9343 | 207.44 | 0.03391 | 0.03163 |
| Low → bananas | 1,667 / 440 | 1.7550 | 86.09 | 0.02495 | 0.02476 |
| Medium → tomatoes | 2,355 / 577 | 1.5572 | 69.67 | 0.02861 | 0.02686 |

All three fits are worse than the constant-mean comparator on this row holdout.
Banana/tomato temperature domains require extrapolation beyond the source's
-2 to 12 C range. The fitting command requires explicit flags for estimated
targets and extrapolation. The report records those limitations, 212 estimated
freshness increases, source hash, exclusions, fit errors and mapping.

A fit and a reproducible seed model have been produced. This evidence does not
establish accurate product-specific spoilage calibration. At that point, the model required suitable observed quality/time/temperature
data or verified literature parameters. The supplied supplement subsequently
provided the latter for the primary three-fruit profile.

## Source-backed dispatch run

The exact example uses source waves 33168–33170 and at most two touched pallet
slots per zone. The 71 selected source pick rows yield 7 included rows on four
slots, with 64 explicitly reported outside the decision window. The full
warehouse geometry remains mapped to 532 chilled, 852 cool and 908 temperate
slots. One source footwear unit becomes one synthetic kg by assumption.

All 32 within-SKU permutation/static-setpoint candidates were evaluated. The
result is exact within this declared finite domain, not a proof for unrestricted
warehouse scheduling. Outputs:

- 7 kg dispatched; no expiry or unfilled demand; zero mass-balance error.
- Selected plan: 7.88565 kWh and 1.12532 kg grid CO2.
- Matched FIFO: 9.11737 kWh and 1.30656 kg grid CO2.
- Matched FEFO: 9.22600 kWh and 1.32353 kg grid CO2.
- Food saved versus FIFO and FEFO: **0 kg** in this case.

The saved Ollama event has **no physical effect** here: even 70% chiller
capacity exceeds the heat load. The model-generated prose claiming a 3 C rise
is not accepted as a physics result. A paired with/without-disruption FEFO
audit records that neutrality explicitly.

`runs/stage1/seed-calibrated-training/` contains the solution, replay
configuration, provenance and one chat-format JSONL record. The source workload
group hashes into validation; train and test files are empty. This verifies
formatting and the end-to-end loop, not a training-ready corpus or an evaluated
LLM policy. Variants of the same PMC archive/wave cohort share one split even
when stock age, seed, calibration or disruptions change.

## Checks performed

The earlier expanded suite had 36 passing tests. They cover the shared paper equation, analytic thermal/energy
checks, layout import, inventory conservation, FEFO and concurrent picking,
incoming put-away, disruption restoration and adjacent-event ordering, grid
boundary integration, parameter recovery, surrogate-target/extrapolation guards,
solver comparison with independent brute force, approximate-result labelling,
source-cohort split isolation and JSONL action/metric replay.

The actual exported row passed independent replay verification of checksums,
layout identity, put-away, pick priorities, chiller targets, execution events,
physical metrics and matched FIFO food saved. The larger five-wave workload
also ran with 81 synthetic pallets and a 40-evaluation GA budget; it remains a
best-known result, not an exact label.

## Reproduce the source-backed run

```bash
.env/bin/python -m warehouse_sim.stage1 calibrate-cold-chain \
  --logs Cold_Chain_Logistics_Dataset.csv \
  --mapping examples/cold-chain-mapping.json \
  --allow-estimated-targets --allow-extrapolation \
  --output runs/stage1/seed-calibrated-template.json

.env/bin/python -m warehouse_sim.stage1 convert \
  --dataset 'Order Picking Dataset from a Warehouse of a Footwear Manufacturing Company.zip' \
  --template runs/stage1/seed-calibrated-template.json \
  --max-waves 3 --max-pallets-per-zone 2 \
  --output runs/stage1/seed-calibrated-window.json

.env/bin/python -m warehouse_sim.stage1 build \
  --dataset 'Order Picking Dataset from a Warehouse of a Footwear Manufacturing Company.zip' \
  --config runs/stage1/seed-calibrated-window.json \
  --scenario runs/stage1/generated-42.json \
  --grid data/grid-2023-01-05.json \
  --require-calibrated --allow-estimated-calibration --require-measured-grid \
  --output runs/stage1/seed-calibrated-training

.env/bin/python -m warehouse_sim.stage1 verify \
  --dataset 'Order Picking Dataset from a Warehouse of a Footwear Manufacturing Company.zip' \
  --export runs/stage1/seed-calibrated-training
```

Equation and method attribution is in [simulation-methods.md](simulation-methods.md).
These findings qualify the pipeline rather than establish food-safety clearance,
field savings, biological prediction accuracy or trained-policy performance.


## Expanded corpus verification

The later batch run produced 60 rows from 30 disjoint source-wave cohorts:
48 train, 8 validation and 4 test. Ordinary and aged-stock variants of each
cohort share their split. All 60 rows independently replayed actions, events,
metrics and FIFO counterfactual food saved. The batches evaluated 1,792 exact
candidates in total; each candidate belongs to the declared small-window domain.

The ordinary batch uses 50–100% of full reference life; the aged batch uses
0.1–8%, explicitly synthetic. Eleven aged cases have positive simulated food
saved; 44 of the 60 cases have neutral disruption effects. Both batches reuse
the recorded Ollama scenario and historic grid profile against different load
patterns. They are workload augmentation, not 60 independent model generations.

Artifacts are in `runs/stage1/combined-corpus/`; the README has reproduction
commands. The stricter `--require-calibrated` flag now rejects estimated targets
unless `--allow-estimated-calibration` is also explicitly supplied. The earlier evidence gap and its resolution are described in [kinetics-source-audit.md](kinetics-source-audit.md).


## Current paper-backed verification

The user-supplied supplement has SHA-256
`fd56de4d5ea43d55aabe331461e1d33d7b7864db8052e273919253b56387a43a`.
The primary model imports S5 observed strawberry lifetime endpoints, S8 observed
apple b* lifetime endpoints, and the S17/Annex II orange life/Q10 prior. It
normalizes quality budgets explicitly and records the ambiguity in printed
S17 rate units; those printed rates were not silently copied.

All 60 rows in `runs/stage1/paper-combined-corpus/` passed action, event, metric,
layout, checksum, split-isolation and matched-FIFO replay verification. There
are 30 distinct source-wave cohorts with ordinary/aged variants together:
48 train, 8 validation, 4 test. The batches performed 1,792 exact candidate
evaluations in their declared finite planning domains. Four aged cases have
positive simulated food saved versus FIFO. This is model output, not field
savings; source-backed and old surrogate corpora are separate artifacts.

The actual saved Q4_K_M response was parsed and compared with the scenario
consumed by the pipeline. The cached official grid raw response was reparsed
and matched all 17 consumed intensity intervals; all were actual rather than
forecast values. Scenario/grid replay across source workloads is explicit.

The five-wave, 81-pallet paper-backed workload ran a 40-evaluation genetic
search and remains labelled best-known, with no optimality claim. The latest
40-test suite also checks citation superscripts, reciprocal-rate interpolation,
endpoint rejection, dispatch/simulator agreement, curve inheritance and
replacement of a curve by a new scalar fit.

The machine-readable audit is `runs/stage1/paper-completion-audit.json`.
Independent batch/cultivar validation, thermal calibration, and trained-policy
benchmarks remain experimental follow-up, not claims made by this prototype.
