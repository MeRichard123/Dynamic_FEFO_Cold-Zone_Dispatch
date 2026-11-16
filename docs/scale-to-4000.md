# Expand Phase 1 to 4,000 examples

**Cleanup update:** final files are now in `dataset/`. Generated run folders,
checkpoints and logs referenced as historical results below have been removed.
Use `examples/paper-template.json` and `data/generated-42.json` as the preserved
inputs for new runs; the root README has the current regeneration command.

The upgraded runner uses **1,000 eligible PMC wave cohorts × four variants**.
The full build is complete in **`runs/stage1/phase1-4000-replay/`**:

- **4,000 records:** 3,192 train / 380 validation / 428 test.
- All 4,000 passed independent replay verification; no failed records.
- 105,696 candidate evaluations; about 19 minutes 34 seconds for generation,
  export and final replay verification on this machine.
- 49 tests pass, including interruption, resume, cache integrity, filtering,
  scenario rotation, checkpoint corruption, concurrency locks and pool recovery.

The records use one saved real Ollama response, procedural faults and controls
with separate provenance. They are not 4,000 independent LLM generations. The
commands below also support generating and rotating a fresh local-model pool.


## What changed

- **Wave filtering and caching:** one indexed read of the source archive, with
  rows grouped by wave and storage-pick eligibility. The source has 9,707 waves;
  9,143 are eligible and 564 contain no storage-location picks. Content-addressed
  JSON caches preserve the archive hash and check their own integrity. Later
  cases use the in-memory index; later processes can reuse the disk cache.
- **Checkpoint/resume:** each successful solution and pair is atomically saved
  before moving on. `--resume` skips completed records and retries failures.
  Source data, template, scenarios, grid, solver/variant settings and labeling
  code are checked before reuse. A live OS lock prevents two jobs writing the
  same directory. Targets can increase, but cannot shrink on resume.
- **Scenario rotation:** repeat `--scenario`, use `--scenario-dir`, or generate
  a resumable local-model pool. Standard batching also includes independently
  attributed controls and seeded procedural faults.
- **Scalable export:** split files are streamed through staged files; the manifest
  is published last. Replay verification reads one JSONL row at a time. Source
  wave variants stay in the same split, including when merged with other exports.

`--cases` now counts **eligible workload cohorts**, and `--wave-offset` in
`batch-build` is an offset in the eligible-wave index. `stage1 convert` retains
its raw source-wave offset semantics. Reports retain actual wave IDs/raw offsets
so filtering does not invent or silently replace source inventory.

## The four standard variants

| Variant | Stock and events | Provenance |
| --- | --- | --- |
| normal | Ordinary stock, no disruption | Normal control |
| near_expiry | Same source workload with explicitly synthetic aged stock | Control, not a new LLM response |
| sensor_drift | Seeded negative sensor bias with varying zone, timing and magnitude | Procedural augmentation |
| disruption | Rotating recorded model scenarios, interleaved with seeded cooling failures/stuck doors | Original provider retained for replay; procedural events labelled separately |

Ordinary and sensor/fault stock use the template's age fractions (normally
50–100% of reference life). Near-expiry defaults to 0.01–0.8%; configure with
`--near-expiry-fraction LOW HIGH`. These are synthetic stress cases, not measured
quality at source receiving. Faults receive bounded, reproducible numerical
parameters. Model outputs are never silently replaced and called LLM responses.

## Optional: generate fresh Ollama scenarios

Run this from your terminal, where Ollama is accessible:

```bash
.env/bin/python -m warehouse_sim.stage1 generate-pool \
  --config runs/stage1/paper-template.json \
  --model qwen2.5:7b --count 24 --seed 42 --resume \
  --output runs/stage1/phase1-scenarios
```

The pool cycles sensor bias, cooling failure and stuck door requests. It checks
4-bit quantization, schema, requested kind, numeric duplicates and obvious
cold-side extrapolation beyond empirical lifetime curves. Invalid responses
have bounded retries and rejection records. Each successful raw response is
saved; rerunning with `--resume` preserves it. The simulator remains the final
check for model-supported scenarios.

This workspace still receives `Operation not permitted` when opening the local
Ollama endpoint. Consequently, fresh pool generation was tested with fixtures;
the real pilot used your previously saved Q4_K_M response and explicit
procedural augmentation. No additional weights or Python packages are required.

## Preflight and launch 4,000 records

With the fresh pool above:

```bash
.env/bin/python -m warehouse_sim.stage1 batch-build \
  --dataset 'Order Picking Dataset from a Warehouse of a Footwear Manufacturing Company.zip' \
  --template runs/stage1/paper-template.json \
  --scenario-dir runs/stage1/phase1-scenarios \
  --grid data/grid-2023-01-05.json \
  --variant-suite standard --cases 1000 --dry-run \
  --output runs/stage1/phase1-4000
```

Dry-run checks workload eligibility, exact-solver budgets and planned split
counts without solving or creating a job directory. For this source/template,
the planned counts are **3,192 train, 380 validation, 428 test** and **105,696
candidate evaluations**. Four variants of a source workload stay together, so
counts are approximate 80/10/10 rather than forced row-level quotas. This does
not pre-validate every possible model response's physical trajectory.

Start or resume the real run by removing `--dry-run` and adding `--resume`:

```bash
.env/bin/python -m warehouse_sim.stage1 batch-build \
  --dataset 'Order Picking Dataset from a Warehouse of a Footwear Manufacturing Company.zip' \
  --template runs/stage1/paper-template.json \
  --scenario-dir runs/stage1/phase1-scenarios \
  --grid data/grid-2023-01-05.json \
  --variant-suite standard --cases 1000 --resume \
  --output runs/stage1/phase1-4000
```

To run entirely with the already available inputs, replace `--scenario-dir ...`
with `--scenario runs/stage1/generated-42.json` and use a fresh output directory
such as `runs/stage1/phase1-4000-replay`. This reuses one actual model response;
it does not create independent LLM scenarios. The pilot used this mode.

Use the same command and inputs after interruption. Increasing `--cases` is
allowed; changing scenario pools, template, source, solver settings or labeling
code requires a new directory. Earlier exports without `run.json` cannot be
resumed as new checkpointed jobs. They remain valid standalone exports.

## Progress, failures and verification

- `progress.json`: current committed/expected counts and elapsed time.
- `records/`: authoritative per-record checkpoints with pair/solution checksums.
- `completed.jsonl`: live preview, rebuilt from committed checkpoints on resume.
- `failures/`: explicit failed simulation/labeling items. Successful retries remove
  their failure records. Unsupported scenarios are not quietly exported as valid.
- `run.json`: input identity, target and job status.
- `batch-summary.json`: variants, providers, outcomes, timing and verification.
- `train.jsonl`, `validation.jsonl`, `test.jsonl`, `manifest.json`: final split export.

Simulation/model failures produce an **incomplete** export with its actual
count and a nonzero CLI exit code; they do not count toward the 4,000 target.
A crash or Ctrl+C preserves prior committed records. Resume repairs the live
journal if interruption occurred between checkpoint commit and journal append.
Final export can be rebuilt from checkpoints after an export/verification failure.

```bash
.env/bin/python -m warehouse_sim.stage1 verify \
  --dataset 'Order Picking Dataset from a Warehouse of a Footwear Manufacturing Company.zip' \
  --export runs/stage1/phase1-4000
```

## Pilot evidence

The current pilot is `runs/stage1/expansion-pilot-v2/`:

- 100 records across 25 source workloads: 25 of each standard variant.
- 84 train / 16 validation / 0 test under the fixed source-group hash. This
  smoke-test cohort happens to contain no test groups; the 4,000-record preflight
  above includes 428 test records.
- 2,944 candidate evaluations and independent replay verification of all 100 rows.
- 25 sensor-bias, 19 cooling-failure and 6 stuck-door cases.
- 50 controls, 37 procedural cases and 13 replays of the saved Ollama response.
- Four positive simulated food-saved labels; these are not field savings.
- Roughly 34 seconds on this machine; resumption is also checked with zero
  completed examples relabelled. This is not a guaranteed bulk runtime.

The full plan has about 36 times the pilot's candidate evaluations. A rough
simulation/export estimate is **20–30 minutes on this machine**, plus any fresh
LLM generation; workload composition and solver verification can change runtime.
The predictor's source assumptions and finite decision domains still apply.
See [paper-parameters.md](paper-parameters.md) for model limits.

For training, use the `messages` field. Other fields contain audit data, solver
controls and replay configurations; they are not additional student inputs.


## Completed 4,000-record data-quality report

`runs/stage1/phase1-4000-replay/quality-report.json` records the final evidence.
There are 1,000 examples of each variant. Among the 2,000 fault scenarios, kinds
are 1,000 sensor bias, 750 cooling failures and 250 stuck doors. Providers are
2,000 controls, 1,500 procedural cases and 500 replays of **one** actual Ollama
response. The eligible-wave index skipped 95 navigation-only source waves
before reaching the final selected cohort.

Food-saved labels are sparse: 192 positive and 3,808 zero, with no negative
labels in this run. Four different static-setpoint combinations appear. Thus,
quantity alone does not establish a balanced food-saving benchmark or policy
generalization. Metadata retains the calibrated-model assumptions and finite
planning domain; the source-cohort split prevents variants crossing splits.

Use `messages` for training and preserve the other fields for audit. Fresh-model
scenario generation remains available from your terminal; it was not executed
by this workspace because socket access to Ollama is denied here.
