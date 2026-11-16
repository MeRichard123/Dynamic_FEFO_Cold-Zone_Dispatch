"""Auditable chat JSONL labels from paired, replayable simulation runs."""
import hashlib
import json
import math
import os
import tempfile
from contextlib import ExitStack
from pathlib import Path

from dispatch import plan as dispatch_plan

from .engine import Simulation
from .layout import zone_slots
from .io_utils import atomic_json, file_sha256

SCHEMA_VERSION = 'stage1-v1'


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def case_group(config):
    provenance = config.get('pmc_provenance')
    if provenance:
        # Stock-age, calibration and scenario variants of the same source
        # workload must not migrate between training and evaluation splits.
        return fingerprint({'pmc_archive_sha256': provenance['source_sha256'],
                            'source_waves': sorted(provenance['selected_source_waves'])})
    return fingerprint(config)


def state_for_dispatch(locations, config):
    simulation = Simulation(locations, config)
    return {'zones': [dict(id=z['id'], temperature_c=z['temperature_c'], setpoint_c=z['setpoint_c'],
                            min_setpoint_c=z.get('min_setpoint_c', min(z.get('setpoint_options_c', [z['setpoint_c']]))),
                            max_setpoint_c=z.get('max_setpoint_c', max(z.get('setpoint_options_c', [z['setpoint_c']]))),
                            slots=simulation.slots[z['id']]) for z in config['zones']],
            'pallets': [{key: p[key] for key in ('id', 'sku', 'slot', 'quantity_kg', 'remaining_life_hours',
                                                'reference_temp_c', 'min_temp_c', 'max_temp_c', 'q10','shelf_life_curve','kinetic_model') if key in p} for p in simulation.initial_pallets],
            'orders': [dict(sku=w['sku'], quantity_kg=w['quantity_kg'], min_remaining_hours=w.get('min_remaining_hours', 0)) for w in config['waves']]}


def make_pair(locations, config, solution, base_case_id, allow_best_known=False):
    if solution['status'] != 'optimal_in_declared_domain' and not allow_best_known:
        raise ValueError('Refusing to export an unproven result as an optimal label; explicitly allow best-known labels or use exact search')
    state = state_for_dispatch(locations, config)
    initial = dispatch_plan(state)
    # Full context (including published forecasts) is available to both teacher and student.
    # Final metrics and solution actions are intentionally absent from the input text.
    compact = dict(config)
    compact.pop('scenario_provenance', None)
    compact.pop('pmc_provenance', None)
    compact.pop('kinetic_provenance', None)
    compact.pop('pallet_priority', None)
    incoming_ids = {p['id'] for p in config.get('incoming_pallets', [])}
    compact['initial_pallets'] = [p for p in Simulation(locations, config).initial_pallets if p['id'] not in incoming_ids]
    used_slots = {p['slot'] for p in compact['initial_pallets']}
    if incoming_ids:
        compact['free_slot_candidates_by_zone'] = {z: [s for s in values if s not in used_slots][:len(incoming_ids)]
                                                    for z,values in zone_slots(locations, config['zones']).items()}
        used_slots.update(slot for slots in compact['free_slot_candidates_by_zone'].values() for slot in slots)
    compact['slot_coordinates'] = {slot: [locations[slot].x, locations[slot].y, locations[slot].z] for slot in sorted(used_slots)}
    prompt = ('Coordinate cold-zone dispatch for this warehouse. Temperatures are Celsius, time minutes, '
              'mass kg, energy kWh. Remaining life is reference-temperature hours under the declared zero-order rate model: '
              'Zou Eq. (1) or piecewise-linear rate interpolation of supplemental shelf-life endpoints. '
              'Disruption schedules and grid profiles below are known scenario forecasts, not hidden future observations. '
              'Select put-away assignments (empty when all pallets are stored), pallet pick priorities, '
              'and zone setpoints. Report predicted kg food saved against the matched FIFO baseline. '
              'Respect the declared decision domain and distinguish exact labels from best-known labels.\n'
              'Warehouse state and known scenario:\n'+json.dumps(compact, sort_keys=True, allow_nan=False)
              +'\nDecision domain:\n'+json.dumps(solution['decision_domain'], sort_keys=True)
              +'\nObjective weights:\n'+json.dumps(solution['weights'], sort_keys=True))
    controls = [dict(zone=z['id'], recommended_setpoint_c=solution['plan']['zone_setpoints_c'][z['id']],
                     previous_setpoint_c=z['setpoint_c'], action='adjust_setpoint' if z['setpoint_c'] != solution['plan']['zone_setpoints_c'][z['id']] else 'maintain_setpoint') for z in config['zones']]
    completion = dict(dispatch_plan={'put_away': solution['plan']['put_away'],
                                    'pick_priorities': [dict(priority=i, pallet_id=pid) for i,pid in enumerate(solution['plan']['pallet_priority'], 1)],
                                    'chiller_adjustments': controls, 'alerts': initial['alerts'],
                                    'execution': [e for e in solution['events'] if e['event'] in ('pick_completed', 'pick_rejected', 'shortage')]},
                      optimization_status=solution['status'],
                      kg_food_saved=solution['kg_food_saved_vs_fifo'],
                      food_saved_baseline='matched FIFO, same initial stock, demand, disruption and horizon',
                      metrics=solution['metrics'])
    scenario_id = fingerprint({'input': prompt, 'schema': SCHEMA_VERSION})
    return dict(id=scenario_id, schema_version=SCHEMA_VERSION,
                messages=[{'role':'system', 'content':'You are a cold-chain dispatch coordinator. Return a JSON dispatch plan with simulation-derived metrics; never claim unproven optimality or food-safety clearance.'},
                          {'role':'user', 'content':prompt},
                          {'role':'assistant', 'content':json.dumps(completion, sort_keys=True, allow_nan=False)}],
                metadata=dict(base_case_id=base_case_id, solution_status=solution['status'],
                              solver_method=solution['method'], evaluations=solution['evaluations'],
                              kinetic_provenance=config.get('kinetic_provenance', {'status':'synthetic_uncalibrated'}),
                              pmc_provenance=config.get('pmc_provenance', {}),
                              grid_provenance=config.get('grid_intensity', {}).get('source', 'synthetic_constant'),
                              scenario_provenance=config.get('scenario_provenance', {'provider':'manual_fixture'}),
                              disruption_effect=solution.get('disruption_effect', {}),
                              replay_config=solution['replay_config'], baseline_config=config, baselines=solution['baselines'],
                              layout_sha256=fingerprint({k:[v.x,v.y,v.z] for k,v in sorted(locations.items())}),
                              limitations='Model-conditioned forecast labels; no experimental waste-saving claim.'))


def write_pairs(pairs, directory):
    """Stream pairs to staged split files; publish the manifest last."""
    directory = Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    seen, source_groups = set(), {}
    counts = {'train':0,'validation':0,'test':0}
    with tempfile.TemporaryDirectory(prefix='.export-',dir=directory) as staged:
        stage = Path(staged)
        with ExitStack() as stack:
            handles = {name:stack.enter_context((stage/f'{name}.jsonl').open('w')) for name in counts}
            for pair in pairs:
                if pair['id'] in seen:
                    raise ValueError('Duplicate training pair')
                seen.add(pair['id'])
                provenance = pair['metadata'].get('pmc_provenance', {})
                group = pair['metadata']['base_case_id']
                for wave in provenance.get('selected_source_waves', []):
                    key = (provenance['source_sha256'],wave)
                    if key in source_groups and source_groups[key] != group:
                        raise ValueError('Overlapping PMC wave cohorts must share one base_case_id before export')
                    source_groups[key] = group
                bucket = int(hashlib.sha256(group.encode()).hexdigest()[:8],16)%100
                split = 'train' if bucket < 80 else 'validation' if bucket < 90 else 'test'
                handles[split].write(json.dumps(pair,sort_keys=True,allow_nan=False)+'\n')
                counts[split] += 1
            for handle in handles.values():
                handle.flush()
                os.fsync(handle.fileno())
        manifest = dict(schema_version=SCHEMA_VERSION,records=sum(counts.values()),splits=counts,
                        split_unit='base_case_id; variants never cross splits',
                        note='A small export may have empty splits; this is not sufficient for training/evaluation.',
                        files={f'{name}.jsonl':file_sha256(stage/f'{name}.jsonl') for name in counts})
        for name in counts:
            os.replace(stage/f'{name}.jsonl',directory/f'{name}.jsonl')
        atomic_json(directory/'manifest.json',manifest)
    return manifest


def merge_exports(locations, sources, directory):
    destination = Path(directory).resolve()
    if any(Path(source).resolve() == destination for source in sources):
        raise ValueError('Merge destination must differ from each source export')
    pairs = []
    for source in sources:
        verify_export(locations, source)
        for split in ('train', 'validation', 'test'):
            pairs.extend(json.loads(line) for line in (Path(source)/f'{split}.jsonl').read_text().splitlines())
    manifest = write_pairs(pairs, directory)
    return {'manifest':manifest, 'verification':verify_export(locations, directory)}


def verify_export(locations, directory):
    directory = Path(directory)
    manifest = json.loads((directory/'manifest.json').read_text())
    count, seen, group_split, source_split = 0, set(), {}, {}
    digest = fingerprint({k:[v.x,v.y,v.z] for k,v in sorted(locations.items())})
    for split in ('train', 'validation', 'test'):
        path = directory/f'{split}.jsonl'
        if file_sha256(path) != manifest['files'][path.name]:
            raise ValueError('JSONL checksum mismatch')
        split_count = 0
        with path.open() as file:
            for line in file:
                row = json.loads(line)
                split_count += 1
                if row['id'] in seen:
                    raise ValueError('Duplicate pair ID')
                seen.add(row['id'])
                group = row['metadata']['base_case_id']
                if group in group_split and group_split[group] != split:
                    raise ValueError('Base case leaks across splits')
                group_split[group] = split
                provenance = row['metadata'].get('pmc_provenance', {})
                for wave in provenance.get('selected_source_waves', []):
                    key = (provenance['source_sha256'], wave)
                    if key in source_split and source_split[key] != split:
                        raise ValueError('PMC source wave leaks across splits')
                    source_split[key] = split
                if row['metadata']['layout_sha256'] != digest:
                    raise ValueError('Verification layout differs from labeling layout')
                completion = json.loads(row['messages'][-1]['content'])
                replay_config = row['metadata']['replay_config']
                replay_sim = Simulation(locations, replay_config)
                replay = replay_sim.run()
                for key, value in completion['metrics'].items():
                    if not math.isclose(value, replay[key], abs_tol=1e-7, rel_tol=1e-9):
                        raise ValueError(f'Replay metric mismatch: {key}')
                baseline_config = dict(row['metadata']['baseline_config'], policy='fifo')
                baseline_config.pop('pallet_priority', None)
                baseline_sim = Simulation(locations, baseline_config)
                expected_placements = baseline_sim.put_away
                baseline = baseline_sim.run()
                actions = completion['dispatch_plan']
                expected_priorities = [dict(priority=i, pallet_id=pid)
                                       for i, pid in enumerate(replay_config['pallet_priority'], 1)]
                if actions['pick_priorities'] != expected_priorities:
                    raise ValueError('Pick-priority label differs from replay controls')
                if actions['put_away'] != expected_placements:
                    raise ValueError('Put-away label differs from replay placement')
                expected_targets = {z['id']: z['setpoint_c'] for z in replay_config['zones']}
                controls = actions['chiller_adjustments']
                actual_targets = {z['zone']: z['recommended_setpoint_c'] for z in controls}
                if len(controls) != len(expected_targets) or actual_targets != expected_targets:
                    raise ValueError('Chiller label differs from replay controls')
                expected_execution = [e for e in replay_sim.events
                                      if e['event'] in ('pick_completed', 'pick_rejected', 'shortage')]
                if actions['execution'] != expected_execution:
                    raise ValueError('Execution label differs from replay events')
                saved = baseline['expired_kg']-replay['expired_kg']
                if not math.isclose(saved, completion['kg_food_saved'], abs_tol=1e-7):
                    raise ValueError('Counterfactual food-saved label does not replay')
                if completion['optimization_status'] != row['metadata']['solution_status']:
                    raise ValueError('Optimization status mismatch')
                count += 1
        if split_count != manifest['splits'][split]:
            raise ValueError('Split row count mismatch')
    if count != manifest['records']:
        raise ValueError('Manifest total mismatch')
    return {'verified_records':count, 'base_cases':len(group_split), 'checks':'checksums, layout, dispatch actions, execution events, simulation metrics, matched FIFO food saved, split isolation'}
