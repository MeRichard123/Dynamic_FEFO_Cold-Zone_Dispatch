# Dynamic FEFO & Cold-Zone Dispatch

Text-based dispatch coordination for a multi-temperature warehouse: put-away
slots, shelf-life-aware picks, and chiller recommendations. The PMC footwear
layout supplies warehouse geometry and picking-workload lineage; produce
properties are a separate, explicit augmentation.

## Scope

**Phase 1 / Stage 1 — Python thermodynamic + discrete-event twin and LLM data loop.**
The Stage 1 simulation/data-augmentation workflow is implemented. The supplied
paper supplement now provides reviewed literature parameters for the primary
apple/orange/strawberry profile. PMC conversion, local 4-bit Ollama generation,
actual GB grid data, optimization and replay-verified chat JSONL have run
together. [Parameter normalization and limits](docs/paper-parameters.md) explain
the observed-lifetime models and the normative orange prior. Independent field
validation and LLM fine-tuning are not claimed.

**Phase 2 / Stage 2 — Visual spoilage and robotics twin.** Camera inspection,
image textures, ManiSkill/MuJoCo, OpenVLA/Octo and manipulation trajectories are
out of scope and have not been implemented.

## Stage 1 implementation and verification

| Requirement | Implementation | Current evidence |
| --- | --- | --- |
| Convert PMC layout to multiple temperature zones | `warehouse_sim/layout.py`, `pmc.py` | All 2,292 slots mapped exactly once: 532 chilled, 852 cool, 908 temperate |
| Seed inventory and demand from PMC picking data | `stage1 convert` | Read 215,192 pick rows / 9,707 waves; bounded window converted with source hashes and exclusion counts |
| Thermodynamic + discrete-event engine | `warehouse_sim/engine.py`, `physics.py` | Eight-hour run, door ingress, limited cooling, expiry, inventory conservation |
| Temperature-dependent quality loss | Shared scalar Eq. (1) and supplemental lifetime-curve model | Analytic/additivity tests plus S5/S8 endpoint normalization |
| Kinetic calibration from observations | `stage1 calibrate` | Reviewed supplemental S5/S8/S17 profile; earlier 7,000-row estimated-target fit retained and explicitly weak |
| UK grid carbon intensity | `stage1 fetch-grid`, `carbon.py` | 17 actual GB intervals fetched and replayed for 2023-01-05 07:42–15:42 UTC |
| Local 4-bit disruption generator | `stage1 generate --provider ollama` or `unsloth` | qwen2.5:7b Q4_K_M response generated in your terminal, saved and used in the verified pipeline; Unsloth remains unexercised |
| Multi-objective simulation-in-the-loop solver | `optimizer.py` | Exhaustive solver checked against independent brute force; larger GA results explicitly best-known |
| State text → dispatch plan + kg food saved JSONL | `stage1 build` | Source-backed PMC-window export independently replayed against matched FIFO, including control actions |

Install and test:

```bash
python3 -m venv .env
.env/bin/python -m pip install -r requirements.txt
.env/bin/python -m unittest discover -s tests -v
```

Python 3.10+ and SimPy 4.1.2 are required. Ollama is optional for fixture runs.
Unsloth/PyTorch/GPU packages are optional and not installed by this project.
No command automatically downloads model weights or image datasets.

## Scaling to 4,000 examples

The batch runner now filters eligible waves, caches the PMC index, checkpoints
individual records, resumes interrupted jobs and rotates scenario pools. A
four-variant suite produces 4,000 rows from 1,000 distinct eligible source waves.
The verified 100-row pilot passed, and the full 4,000-row dataset is now in
`runs/stage1/phase1-4000-replay/`: **3,192 train / 380 validation / 428 test**.
All rows passed replay verification, with zero failures. See
[the scaling guide](./scale-to-4000.md) for preflight, fresh Ollama pools,
launch/resume commands, timing and provenance. Forty-nine tests pass. The data
mixes attributed model-response replays, procedural faults and controls; it is
not 4,000 independent LLM generations.

## Primary paper-backed workflow

The supplied Word supplement is sufficient for reviewed literature-conditioned
parameters. It is **not** an independent validation on your warehouse stock.
The primary profile uses apples, oranges and strawberries; the earlier
banana/tomato examples retain their synthetic labels.

```bash
.env/bin/python -m warehouse_sim.stage1 paper-profile \
  --supplement 1-s2.0-S0260877425001128-mmc1.docx \
  --output runs/stage1/paper-template.json

.env/bin/python -m warehouse_sim.stage1 batch-build \
  --dataset 'Order Picking Dataset from a Warehouse of a Footwear Manufacturing Company.zip' \
  --template runs/stage1/paper-template.json \
  --scenario runs/stage1/generated-42.json --grid data/grid-2023-01-05.json \
  --cases 30 --output runs/stage1/paper-corpus

.env/bin/python -m warehouse_sim.stage1 batch-build \
  --dataset 'Order Picking Dataset from a Warehouse of a Footwear Manufacturing Company.zip' \
  --template runs/stage1/paper-template.json \
  --scenario runs/stage1/generated-42.json --grid data/grid-2023-01-05.json \
  --cases 30 --initial-life-fraction 0.0001 0.008 \
  --output runs/stage1/paper-aged-corpus

.env/bin/python -m warehouse_sim.stage1 merge \
  --dataset 'Order Picking Dataset from a Warehouse of a Footwear Manufacturing Company.zip' \
  --export runs/stage1/paper-corpus --export runs/stage1/paper-aged-corpus \
  --output runs/stage1/paper-combined-corpus
```

The source-backed corpus has 60 records with stable source-cohort splits:
48 train, 8 validation and 4 test. Ordinary and synthetic near-expiry variants
of a source wave stay together. All candidate simulations use the same initial
stock and exogenous conditions as their counterfactuals. Exact labels refer to
the declared finite permutation/static-setpoint domain. The final corpus can
be replayed using `stage1 verify --dataset '<PMC archive>' --export
runs/stage1/paper-combined-corpus`.

The saved Ollama scenario is replayed under the new profile and workload;
its generation request originally used the earlier demonstration products.
The dataset records this transfer rather than claiming fresh model generations.
S17 superscript citations and ambiguous printed k0 normalization are audited;
the importer uses S5/S8 observed lifetime endpoints and a stated orange prior.
It does not silently reinterpret percent-per-minute values or assign paper
parameters to bananas/tomatoes.

## Earlier synthetic fixture workflow

Use the archive already in the project. This exact demo selects the earliest
three source waves and at most two touched pallet slots per temperature zone.
The full warehouse geometry is retained, and demand outside the decision window
is explicitly excluded and counted. The 1 kg per footwear unit conversion is a
synthetic workload assumption, not a measured food quantity.

```bash
.env/bin/python -m warehouse_sim.stage1 convert \
  --dataset 'Order Picking Dataset from a Warehouse of a Footwear Manufacturing Company.zip' \
  --template examples/simulation.json \
  --max-waves 3 --max-pallets-per-zone 2 \
  --output runs/stage1/pmc-window.json

.env/bin/python -m warehouse_sim.stage1 build \
  --dataset 'Order Picking Dataset from a Warehouse of a Footwear Manufacturing Company.zip' \
  --config runs/stage1/pmc-window.json \
  --scenario examples/disruption.json \
  --output runs/stage1/training

.env/bin/python -m warehouse_sim.stage1 verify \
  --dataset 'Order Picking Dataset from a Warehouse of a Footwear Manufacturing Company.zip' \
  --export runs/stage1/training
```

`examples/disruption.json` is a **manual regression fixture**, not an LLM output.
This run uses synthetic kinetic parameters and a synthetic constant carbon
factor. It verifies software wiring; it does not establish empirical performance.
Omit `--max-pallets-per-zone` to retain all storage picks from selected waves.
`--kg-per-unit`, `--arrival-scale`, `--max-waves` and the scenario horizon are
explicit controls; no selected demand is silently clipped to the horizon.
Nonstorage pick locations (e.g. navigation points) are counted in the conversion
report rather than invented as rack slots.

Artifacts:

- Converted JSON: source lineage, original slots, synthetic inventory, wave arrivals.
- `solution-0000.json`: domain, objective weights, search status, controls, replay
  configuration, execution events and matched FIFO/FEFO metrics.
- `train.jsonl`, `validation.jsonl`, `test.jsonl`: chat messages with JSON plans,
  signed kg food saved, status, provenance and replay configuration.
- `manifest.json`: checksums, counts and group-based split policy.

A single warehouse case stays in a single split with all its disruption variants.
Small exports may have empty validation/test files. More independent cases are
needed before training and evaluating an LLM. Optional
`initial_life_fraction: [low, high]` in a conversion template controls synthetic
aged-stock augmentation (default `[0.5, 1.0]`); it is recorded in provenance
and must not be confused with observed initial quality.

## Generate edge cases using your local model

Run from a terminal that can access Ollama. Substitute an installed 4-bit model
name; the generator checks `/api/show` for Q4/IQ4 quantization and does not pull
weights. It only accepts bounded sensor bias, cooling-capacity loss, and stuck-door
events for existing zones.

```bash
.env/bin/python -m warehouse_sim.stage1 generate \
  --config runs/stage1/pmc-window.json \
  --provider ollama --model qwen2.5:7b --seed 42 \
  --output runs/stage1/generated-42.json
```

Then use `--scenario runs/stage1/generated-42.json` in `stage1 build`. Repeat
`--scenario` for multiple generated variants. Requests, raw responses, model
identity and quantization are retained. Invalid output fails explicitly; there
is no silent replacement with a handcrafted disruption.

For the README's Unsloth path, install its GPU dependencies separately, supply
an already-downloaded local model directory, and use:

```bash
.env/bin/python -m warehouse_sim.stage1 generate \
  --config runs/stage1/pmc-window.json \
  --provider unsloth --model /absolute/path/to/local/model --seed 42 \
  --output runs/stage1/generated-unsloth-42.json
```

This calls `FastLanguageModel` with `load_in_4bit=True` and local-files-only loading.
The Unsloth integration has not been exercised on this machine's GPU.

## Calibrate the kinetic model

The normalized observation CSV schema is:

```csv
sku,batch,timestamp,temperature_c,quality
strawberries,batch-a,2023-01-01T00:00:00Z,2,1.0
strawberries,batch-a,2023-01-01T01:00:00Z,2,0.9
```

`quality` must be a quantitative, normalized quality budget above the rejection
threshold (1 = full budget, 0 = rejection). The two example rows illustrate
format only; fitting both rate and Q10 requires at least three uncensored
intervals and independent temperature exposures per SKU. Binary Good/Bad labels,
images, or temperature alone do not identify the quality-loss rate. Quality=0
endpoints are treated as censored and excluded from regression. Timestamps must
include a UTC offset.

```bash
.env/bin/python -m warehouse_sim.stage1 inspect-data \
  --data data/cold-chain.zip --output runs/stage1/source-inspection.json

.env/bin/python -m warehouse_sim.stage1 calibrate \
  --logs data/quality-observations.csv --config examples/simulation.json \
  --output runs/stage1/calibrated-template.json
```

Use the calibrated template in `stage1 convert`, **before** initial pallet life
is generated. Applying new kinetics to existing inventory requires observed
initial quality and is not inferred automatically. Fit reports preserve source
hashes and residual error. They are not independent experimental validation.

See [data-source assessment](docs/data-sources.md) for the links supplied in this
conversation and the scientific limits of each source. The supplied paper
supplement now supplies the primary literature-conditioned kinetic profile.

## Optional estimated-target seed-fit experiment

`Cold_Chain_Logistics_Dataset.csv` contains 7,000 aggregate transport records,
including temperature, transit hours, initial freshness and **estimated** final
freshness. It has sensitivity classes rather than species IDs. The explicit
mapping in `examples/cold-chain-mapping.json` transfers High/Low/Medium classes
to strawberries/bananas/tomatoes for synthetic augmentation; it does not infer
biological product identity.

```bash
.env/bin/python -m warehouse_sim.stage1 calibrate-cold-chain \
  --logs Cold_Chain_Logistics_Dataset.csv \
  --mapping examples/cold-chain-mapping.json \
  --allow-estimated-targets --allow-extrapolation \
  --output runs/stage1/seed-calibrated-template.json
```

This assumes each row's Temperature_C is constant over Actual_Transit_Time_hr.
It fits the initial-to-estimated-final quality difference without inventing
sample timestamps. The two explicit flags acknowledge estimated targets and
product temperatures outside the source range of -2 to 12 C. The deterministic
80/20 row split keeps identical rows together; it is not a batch-level field
validation. Zero-quality endpoints are censored, and freshness increases are
counted as noise rather than silently clipped.

All three fitted models currently perform slightly worse than a constant-mean
predictor on held-out rows. Treat these rates as a reproducible seed model,
not validated spoilage predictions. The longitudinal `calibrate` command above
remains available for measured quality trajectories.

Use `runs/stage1/seed-calibrated-template.json` as the conversion template, then
build with the saved Ollama scenario and grid file. The verified outputs are in
`runs/stage1/seed-calibrated-training/`; the example record is in the validation
split under the stable grouping rule. No source file was modified.

## Use real GB grid intensity

The official GB API (rather than an all-UK including Northern Ireland claim)
provides half-hour intervals in gCO2/kWh; the adapter converts them to kgCO2/kWh.
Actual values are preferred, with forecast fallback explicitly recorded when
actual data are absent. Gaps and missing values fail validation.

```bash
.env/bin/python -m warehouse_sim.stage1 fetch-grid \
  --date 2023-01-05 --start 2023-01-05T07:42:00Z --minutes 480 \
  --output data/grid-2023-01-05.json
```

The start above is an **explicit UTC interpretation for the demo**. PMC order
strings have no timezone; verify the source timezone before research alignment.
Pass the cached file with `stage1 build --grid data/grid-2023-01-05.json`.
`--require-calibrated` accepts quantitative observed-quality fits or the reviewed
supplemental literature profile, and rejects estimated-freshness fits by default. Add `--allow-estimated-calibration`
to explicitly run a surrogate seed model. `--require-measured-grid` requires
official grid provenance. These checks do not establish independent experimental
validation or the scientific suitability of supplied observations.

## Earlier surrogate corpus

`runs/stage1/combined-corpus/` now contains 60 replay-verified surrogate pairs
from 30 disjoint source-wave cohorts: 48 train, 8 validation and 4 test.
Ordinary-stock and aged-stock variants of a cohort stay in the same split.
There were 1,792 exact candidate evaluations in total. Eleven aged-stock cases
show positive simulated food saved against FIFO; none of these are field claims.

Reproduce the two batches and verified merge:

```bash
.env/bin/python -m warehouse_sim.stage1 batch-build \
  --dataset 'Order Picking Dataset from a Warehouse of a Footwear Manufacturing Company.zip' \
  --template runs/stage1/seed-calibrated-template.json \
  --scenario runs/stage1/generated-42.json --grid data/grid-2023-01-05.json \
  --allow-estimated-calibration --cases 30 --output runs/stage1/corpus

.env/bin/python -m warehouse_sim.stage1 batch-build \
  --dataset 'Order Picking Dataset from a Warehouse of a Footwear Manufacturing Company.zip' \
  --template runs/stage1/seed-calibrated-template.json \
  --scenario runs/stage1/generated-42.json --grid data/grid-2023-01-05.json \
  --allow-estimated-calibration --cases 30 --initial-life-fraction 0.001 0.08 \
  --output runs/stage1/aged-corpus

.env/bin/python -m warehouse_sim.stage1 merge \
  --dataset 'Order Picking Dataset from a Warehouse of a Footwear Manufacturing Company.zip' \
  --export runs/stage1/corpus --export runs/stage1/aged-corpus \
  --output runs/stage1/combined-corpus
```

Each batch uses one distinct source wave per case by default; `--wave-offset`
and `--waves-per-case` select other disjoint cohorts. `stage1 convert` also
accepts `--wave-offset`. Partial final cohorts fail rather than silently changing
batch size. The same cached grid interval and recorded Ollama scenario are
replayed against each workload; source wall-clock dates are not presented as
actual grid alignment, and these are not independent LLM generations.

Aged-stock life fractions are explicit synthetic augmentation. The fitter's
weak validation remains visible in every row's provenance. The merge verifies
all source exports, preserves cohort grouping and rejects overlapping source
wave windows assigned to different case groups. Sixty pairs demonstrate the
pipeline and varied labels; they are not an evaluated trained policy.

## Optimization semantics

The objective minimizes a configured weighted combination of expired kg,
unfilled kg, compressor kWh and grid kgCO2, and rewards dispatched kg-hours of
remaining life. Weights are recorded in every solution and training input;
use `--weights path/to/weights.json` to change them.

Exhaustive mode evaluates every within-SKU pallet permutation and combination
of configured static zone setpoints. It proves optimality **only within that
finite decision domain**, under the simulation assumptions. Wave arrivals and
queue order, greedy put-away, and trip timing are fixed. Idling, relocations,
dynamic setpoint trajectories and arbitrary physical schedules are not searched.
An optimized shelf-life-aware ranking can differ from strict FEFO; FIFO and
strict dynamic FEFO are separately replayed comparison policies.

Large domains fail before exact search exceeds its evaluation budget. Use
`--method genetic --max-evaluations 200 --generations 10 --population 20` for
an approximate permutation/setpoint search. Exporting those results requires
`--allow-best-known`; their labels never claim proven optimality. This is an
independent GA implementation motivated by the IEEE paper, not a reproduction
of its adaptive operators or a claim of global optimality.

`kg_food_saved = FIFO expired_kg - selected-plan expired_kg` on the **same**
initial stock, known disruptions, demand, grid profile and horizon. The signed
quantity is retained, including zero or negative values. A small fixture in
`examples/optimization-window.json` prevents 1 kg expiry versus FIFO and matches
FEFO; it is synthetic and does not demonstrate field savings. Its coordinate
scale is a test assumption. Both comparisons are recorded in solution files. A separate paired FEFO run
with and without disruptions records realized physical/dispatch impact. The
currently saved Ollama cooling-failure event is neutral because available
chiller capacity still exceeds the heat load; its prose does not override physics.

## Original text-dispatch CLI

```bash
python3 dispatch.py --state examples/state.json
python3 dispatch.py --text examples/scenario.txt --model qwen2.5:7b
```

Ollama extracts structured state from free text; deterministic rules assign slots,
pick FEFO stock, and recommend chiller actions. Both this CLI and the simulator
now share the linear temperature factor from Zou Equation (1). In the original
example, estimated strawberry lives are **14.4** and **48.0 hours** at 3.5 C.
`examples/plan.json` is regenerated accordingly. Neither CLI controls equipment.
The standalone dispatcher does not incorporate the simulation optimizer; the
`stage1` commands produce solver-labelled training data for that later policy.

## Methods and references

- [Zou et al. (2025), dynamic fruit quality loss](https://doi.org/10.1016/j.jfoodeng.2025.112577):
  Equation (1) is used for normalized quality-loss accumulation.
- [Hu et al. (2023), cold-chain warehouse digital twin](https://ieeexplore.ieee.org/document/10184421):
  architectural and multi-objective scheduling context; no claimed replication.
- [Official GB Carbon Intensity API](https://carbon-intensity.github.io/api-definitions/).
- [Detailed methods and limitations](docs/simulation-methods.md).

Thermal constants, COP, food parameters, airflow, coordinate scale and travel
models require validation. A zone-air lumped model substitutes for product
thermal lag; travel is approximate Manhattan distance, not rack-aware routing.
Current labels expose disruption schedules as known forecasts. They are
model-conditioned planning targets, not a demonstrated sensor-only causal
policy or food-safety clearance. No model fine-tuning is claimed.
