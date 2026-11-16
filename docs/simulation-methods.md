# Simulation methods and provenance

## Paper-to-code mapping

1. Zou, Y., Wu, J., Meng, X., Wang, X., and Manzardo, A. (2025).
   *Digital twin integration for dynamic quality loss control in fruit supply chains*.
   Journal of Food Engineering 397, 112577.
   [Publisher/DOI](https://doi.org/10.1016/j.jfoodeng.2025.112577),
   [university full text](https://research.unipd.it/retrieve/43513ce9-2827-4b57-b5b5-7d4661757349/1-s2.0-S0260877425001128-main.pdf),
   [author-uploaded text](https://www.researchgate.net/publication/389977635_Digital_twin_integration_for_dynamic_quality_loss_control_in_fruit_supply_chains).

   **Used:** Equation (1), additive zero-order quality loss, implemented in
   `warehouse_sim/physics.py::decay_factor` and `life_consumed`:

   ```text
   f(T) = 1 + (Q10 - 1) * (T - T0) / 10
   Qloss = k0 * sum(f(T) * delta_t)
   ```

   **Adaptation:** dividing the remaining quality budget by k0 gives remaining
   reference-temperature life hours. Each integration interval consumes
   `average(f(T_start), f(T_end)) * delta_hours`. This endpoint approximation
   should be checked by reducing the tick size. FEFO estimates current-temperature
   life as `reference_hours / f(T)`. Nonpositive factors fail explicitly rather
   than creating negative decay. This linear factor is shared by the simulator and text-dispatch CLI.

   **Not reproduced:** trained in-box temperature prediction, calibrated kinetic
   parameters, experimental accuracy, or reported waste reductions. Zone air
   temperature is substituted for produce temperature; product thermal lag is
   absent. Initial life and Q10 values are synthetic, including those for bananas
   and tomatoes; they are not taken from the paper's experiments.

2. Hu, B., Guo, H., Tao, X., and Zhang, Y. (2023).
   *Construction of Digital Twin System for Cold Chain Logistics Stereo Warehouse*.
   IEEE Access 11, 73850–73862.
   [Publisher](https://ieeexplore.ieee.org/document/10184421),
   [DOI](https://doi.org/10.1109/ACCESS.2023.3295819),
   [available manuscript](https://www.researchgate.net/publication/372433524_Construction_of_digital_twin_system_for_cold_chain_logistics_stereo_warehouse).

   **Used as architectural context:** linking warehouse operational state with
   temperature monitoring and freshness-aware scheduling (Sections III–IV).
   **Not reproduced:** its adaptive genetic algorithm (Section III.C), data-fusion
   system, or freshness-investment equations (5)–(6). The independent permutation/setpoint GA and exact finite-domain solver are
   documented in the README; they do not inherit the paper's reported improvements.

Publisher access was restricted during review. Equation (1) was checked using
university-indexed full-text extraction and author-uploaded text. The IEEE
method was inspected in the available manuscript; equation numbering here
refers to that manuscript. This is a simulation foundation, not a replication
or validation of either complete study.

## Independent engineering assumptions

The following are our explicit simplifications, not equations attributed to
either linked paper.

The lumped zone thermal balance is:

```text
C * dT/dt = UA * (ambient - T) - cooling
```

C is effective thermal capacity in kWh/K, UA conductance in kW/K, cooling
thermal kW, and time hours. `thermal_step` solves this balance analytically
for a constant input per interval. The controller chooses enough cooling to
reach its setpoint at interval end, capped by maximum cooling power. It never
heats. This is an idealized controller, not compressor cycling or a validated
refrigeration plant. Door opening adds a configured conductance while at least
one picker is handling stock in that zone. Multiple simultaneous openings are
represented by a single open-zone conductance. Walls between zones, humidity,
respiration heat, defrosting and temperature-dependent COP are absent.

Electricity = thermal cooling kW × hours / COP. Carbon = electricity kWh ×
configured kg CO2/kWh. The example 0.2 carbon factor is an illustrative constant,
not a retrieved grid measurement. An optional cached official GB time series
is integrated at each half-hour boundary by `carbon.py`; the source-backed run uses 17 actual intervals from the cached
2023-01-05 API response. See the README for the fetch command.

## Dataset and event semantics

The baseline imports `Storage_Location.csv` from the original archive.
`stage1 convert` additionally imports selected `Picking_Wave.csv` records and
`Customer_Order.csv` timestamps, preserving IDs and reporting excluded rows. All 2,292
slot IDs and x/y/z coordinates are preserved. Explicit aisle groups in the
configuration form three synthetic cold zones. Footwear picking units are converted to synthetic produce kilograms only
under an explicit kg-per-unit assumption; produce SKU is determined by slot
zone, not inferred from a shoe reference. Raw references remain lineage.
The original standalone baseline uses wholly synthetic stock and demand.

The dataset README describes x/y/z in metres. We preserve its raw coordinates
and use `coordinate_scale_m=1` initially; verify the physical scale against the
CAD drawing before using route durations for research. The support-point
navigation graph and rack elevation are not used yet. Travel is a two-dimensional
Manhattan distance from dispatch to a slot and back. It can cross racks and
is only a travel-time approximation, not a collision-free warehouse route.

The SimPy clock is in minutes. A periodic tick advances temperature and quality,
while picking transitions also advance the physics to their exact event time.
Waves queue for a shared picker resource. Available, unreserved pallets meeting
current temperature and minimum-life constraints are selected by estimated
current-temperature life, with pallet ID as a deterministic tie-breaker.
Each trip serves one pallet with partial picks allowed. Door opening occurs
only during handling at the slot. For now, stock follows its zone temperature
through the return trip and is removed only on arrival at dispatch; transport
exposure and load-dependent travel are absent. Eligibility is checked again
at dispatch. No pick is credited for an expired or temperature-ineligible load.

Remaining reference life decreases monotonically. Stock reaching zero is counted
as expired at the next integration event. The expiry timestamp therefore has
at most an integration-step delay. No expired mass is allocated again. This
is quality-budget expiry, not microbiological safety clearance.

Shortage means no eligible unreserved stock at selection time, or a rejected
trip; it is terminal for that wave. There is no automatic retry after cooling
or after another picker releases a reservation. Requests still queued/active
at the horizon remain explicitly incomplete. Events exactly at the horizon are
processed. Initial mass equals dispatched + expired + remaining mass, including
reserved/in-transit stock in remaining mass.

The random seed controls only initial pallet life (uniformly 50–100% of the
configured life_hours). The standalone baseline has no LLM or live hardware. The Stage 1 pipeline
adds validated sensor bias, cooling-capacity loss and stuck-door events,
static-setpoint/pallet-order optimization and chat JSONL export. Sensor bias
changes the measured temperature and controller target, not the physical
temperature directly. Stored product eligibility uses physical model state;
this teacher is an oracle, not a demonstrated sensor-only controller.

Optional `incoming_pallets` are put away greedily at time zero using the shared
dispatcher. Unplaceable arrivals fail explicitly. Resolved stock and placement
are frozen identically across all optimization candidates and baselines.

Optimization uses the full simulation for every candidate. Exact status refers
only to all enumerated within-SKU permutations and discrete static targets.
The GA is approximate; no unconstrained scheduling optimality is claimed.
Counterfactuals share the same initial inventory and exogenous scenario.
`kg_food_saved` is the signed difference in expired stock against FIFO; a
separate FEFO comparison is also retained.

## Verification

Tests check the analytic passive thermal solution, cooling energy at setpoint,
door heat ingress, Equation (1) factors and additivity, FEFO selection,
repeatability, concurrent reservations, expiry and mass balance, shortages,
temperature rejection, horizon handling, layout imports, and invalid mappings.
These establish implementation consistency, not experimental validation.

SimPy process and resource usage follows its
[official documentation](https://simpy.readthedocs.io/en/stable/simpy_intro/shared_resources.html).

The expanded Stage 1 suite currently has 40 passing tests.
On the bundled eight-hour scenario with the supplied PMC archive, Reducing the tick from 1 minute to 0.5 minutes preserved dispatched
mass (800 kg) and expired mass (50 kg). Electricity changed from
12.9867132 to 12.9867419 kWh; maximum final reference-life difference was
0.00002465 hours. This is a local timestep check for this scenario only.

Adjacent same-kind disruptions are applied on a shared event timeline with
ends before starts, preventing an ending event from clearing its successor.
Regression checks cover sensor bias, cooling loss and stuck-door boundaries.
The export verifier independently replays placement, pick priorities, chiller
targets and execution events as well as quantities, energy and FIFO food saved.


## Downloaded-data seed fit

`calibrate-cold-chain` uses aggregate initial/estimated-final freshness and
reported transit time from the downloaded Kaggle CSV. Constant transit
Temperature_C is an explicit approximation; no time series is invented. An
operator-supplied sensitivity-to-SKU map performs synthetic transfer. This
extends the earlier normalized-observation fitter, not the paper's experiments.

An 80/20 deterministic row holdout and constant-mean comparator are recorded.
The current fits are slightly worse than the comparator for all three classes.
Banana/tomato operating domains extend beyond source temperatures and are
explicitly flagged as extrapolation. This is a reproducible surrogate seed,
not established empirical product calibration.

Disruption effect is independently audited by comparing FEFO with/without the
same exogenous events. The saved Q4_K_M Ollama scenario leaves 70% cooling
capacity available, which exceeds the cool zone's heat load in this case.
The physical simulation correctly shows no disruption effect; generated prose
claiming a 3 C rise is not used as a numerical input or accepted as a result.


## Primary supplemental endpoint model

The supplied DOCX now provides reviewed S5/S8/S17 data. The primary apple and
strawberry models linearly interpolate reciprocal observed shelf life to obtain
a temperature-dependent zero-order rate. This explicitly extends scalar Eq. (1)
with piecewise rate segments; scalar Q10 is retained for the normative orange
prior. No curve extrapolation is permitted. The normalized endpoint is the
published observed shelf life, rather than an invented absolute trait cutoff.

See [paper-parameters.md](paper-parameters.md) for units, mathematical
normalization, the printed S17 rate audit, model envelopes and zone choices.
The poor estimated-freshness model remains an optional earlier experiment and
is not used by the primary paper-backed export. The current completion evidence
is recorded in [stage1-completion-audit.md](stage1-completion-audit.md).
