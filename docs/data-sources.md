# Stage 1 source assessment

**Update:** the supplied original paper supplement is now reviewed and used
for the primary apple/orange/strawberry profile. See
[paper-parameters.md](paper-parameters.md). The older aggregate seed fit remains
an explicitly weak optional experiment. No additional data download is needed
to reproduce the completed Stage 1 simulation/data-augmentation pipeline.

The PMC archive, `Cold_Chain_Logistics_Dataset.csv`, saved Ollama response and
official GB grid response are now present and integrated. Other links remain
candidate inputs. The aggregate freshness fit is explicitly an estimated-target
surrogate, not a measured biological calibration.

| Source | Inspection evidence | Stage 1 use / outstanding check |
| --- | --- | --- |
| [Datcolabssnet Cold Chain Logistics](https://www.kaggle.com/datasets/datcolabssnet/cold-chain-logistics-dataset) | Downloaded CSV inspected: 7,000 aggregate rows, initial/estimated freshness, transit time, temperature and sensitivity class | Explicit aggregate seed fit implemented; lacks species/batch IDs and measured final quality, so it does not validate intrinsic kinetics |
| [Kaggle discussion 328821](https://www.kaggle.com/discussions/general/328821) | Discussion requesting cold-chain data, not a dataset release | Background only; no observations can be calibrated from it |
| [Fruit and vegetable dataset for shelf life](https://www.kaggle.com/datasets/soorajkavumpadi/fruit-and-vegetable-dataset-for-shelf-life) | Kaggle file listing unavailable from this environment | Inspect archive before use; images alone remain outside Stage 1 and do not establish time-temperature kinetics |
| [Mendeley czz68d9fwj v1](https://data.mendeley.com/datasets/czz68d9fwj/1) | Publisher description lists Fruit, Temp, Humid, Light, CO2, Class | Environmental/spoilage-risk seed data; the documented fields lack elapsed-time trajectories, so they cannot alone fit kinetic rates |

The Mendeley source identifies 10,996 entries and Good/Bad environment labels.
That supports a risk-classification task, not an identifiable shelf-life model
without additional longitudinal quality observations. Its page states CC BY 4.0;
retain attribution if its data are imported. Its measurements should not be
silently treated as timestamps, temperatures over time, or normalized quality.

The PMC conversion preserves original slot IDs, source wave numbers, source
references and a SHA-256 of the archive. Each chosen row is either included or
reported as nonstorage/outside-window; the produce SKU mapping and kg per source
unit are explicit synthetic assumptions. Receiving dates are unavailable; FIFO
uses assumed `arrival_minute` (default 0) and pallet ID for ties.

## Remaining scientific validation

The downloaded aggregate CSV is SHA-256
`a25b4c3d17ae3d838ddee7fc063174f5f08f86efb439feb4003be4909185de9a`.
Its `Estimated_Freshness_Percent` targets and categorical `Product_Sensitivity`
require explicit transfer assumptions. All three seed fits fail to outperform
a constant-mean predictor on held-out rows. Their quality errors, extrapolation
flags, mapping, source hash and assumptions are recorded in
`runs/stage1/seed-calibrated-template.calibration.json`.

For empirically validated product kinetics, obtain species-specific measured
quality or time-to-expiry alongside elapsed time and temperature exposure.
Temperature alone, estimated quality, or untimed class labels are insufficient
to claim such validation. No further download is needed to run the current
surrogate pipeline. The local-model generation and actual GB grid fetch have
both been completed and consumed in the source-backed export.

No images, VLA training assets, robot simulator or large model weights are needed
for the Stage 1 fixture pipeline. Unsloth is optional if using your existing
4-bit Ollama model instead; the Unsloth provider remains available for the
original proposed workflow.
