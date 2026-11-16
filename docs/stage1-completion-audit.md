# Stage 1 completion audit

Scope: the README's Python thermodynamic/discrete-event twin and text-only LLM
synthetic-data loop. Stage 2 visual spoilage, robotics and VLA work is excluded.
This audit concerns the reproducible prototype, not independent field validation.

| Required outcome | Authoritative evidence inspected | Result |
| --- | --- | --- |
| PMC converted to multiple temperature zones | Original archive, layout importer, source-backed conversion and all 2,292 source slot IDs | All slots uniquely mapped: 532 / 852 / 908; primary temperatures 0 / 2 / 4 C |
| Source workload/inventory augmentation | Picking_Wave.csv and Customer_Order.csv, hashes and conversion reports | Source IDs/times retained; kg conversion and bounded-window exclusions explicit; distinct cohort selection tested |
| Thermodynamic + SimPy engine | Engine implementation, analytic physics tests and executed workloads | Door ingress, cooling limits, inventory aging/expiry and picker resource implemented and exercised |
| Correctly sourced kinetic model | Supplied DOCX, Tables S5/S8/S17, import report and 40-test suite | Observed strawberry/apple lifetime endpoints and normative orange prior normalized to explicit quality units; source unit ambiguity documented |
| UK grid carbon accounting | Official GB API raw response and reparsed 17 intervals | g-to-kg conversion, time integration and actual-value provenance verified; GB geographical scope stated |
| Local 4-bit LLM edge-case generation | Saved qwen2.5:7b Q4_K_M request/response and consumed scenario | Raw response matches scenario; bounds/schema validated; realized impact audited |
| Multi-objective solver in simulation loop | Exact small-domain candidate runs, independent brute-force test, 81-pallet larger run | Exact labels only for fully enumerated domains; larger GA explicitly best-known |
| State text → plan + kg food saved JSONL | Final manifest, 60 decoded rows, source cohort groups and independent simulation replay | 48 train / 8 validation / 4 test; controls/events/metrics and matched FIFO savings verified |
| Reproducibility and references | README commands, parameter guide, source/manifest hashes and replay configurations | Artifacts and source/model assumptions traceable; all paper-derived choices linked |
| Exclude Stage 2 | Dependency list and implementation scope | No image ingestion, VLA, robot simulator or manipulation pipeline added |

The user's existing Ollama runtime was used for actual 4-bit generation.
The optional Unsloth provider is implemented but unexercised; no second model
runtime or GPU download was required. The recorded scenario is reused across
workloads, which is disclosed; these are not independent LLM generations.

Primary artifacts:

- `runs/stage1/paper-template.json` and `.literature.json`: source-backed models.
- `runs/stage1/paper-combined-corpus/{train,validation,test}.jsonl`: final pairs.
- `runs/stage1/paper-combined-corpus/manifest.json`: counts and SHA-256 checksums.
- `runs/stage1/paper-completion-audit.json`: final machine-readable verification.
- `runs/stage1/paper-full-genetic.json`: larger-workload best-known result.

The finite decision domain fixes wave queueing, trip mechanics, greedy put-away
and static setpoint options. Interpolated lifetime curves and the orange prior
are model assumptions supported by the stated sources; they do not reproduce
the paper's full LSTM/experimental system. Temperature geometry/physics constants
and stock ages remain explicit simulation inputs. Generated kg food saved is a
paired model counterfactual, not measured food saved in a real warehouse.

Independent biological/thermal validation, more independent model scenarios,
corpus scaling and LLM fine-tuning are future extensions. They are not represented
as completed experimental results. The requested Stage 1 implementation and
source-backed data-augmentation workflow are complete and reproducible.
