"""Cached, filtered, checkpointed source-cohort batching with explicit variants."""
import copy
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
import time

from .calibration import require_calibration
from .dataset import case_group, fingerprint, make_pair, write_pairs, verify_export
from .io_utils import atomic_json, job_lock, file_sha256
from .llm import apply_scenario
from .optimizer import solve
from .pmc import PMCIndex, convert
from .scenarios import variants
from .layout import zone_slots

RUN_VERSION = 2


def implementation_digest():
    root = Path(__file__).parent
    return fingerprint({name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in
                        ('batch.py','scenarios.py','pmc.py','engine.py','physics.py','optimizer.py','dataset.py')})


def checkpoint_records(directory, identity):
    for path in sorted((directory/'records').glob('*.json')):
        record = json.loads(path.read_text())
        if record['run_fingerprint'] != identity or fingerprint(record['pair']) != record['pair_sha256']:
            raise ValueError(f'Checkpoint identity/integrity mismatch: {path}')
        solution = directory/record['solution_file']
        if file_sha256(solution) != record['solution_sha256']:
            raise ValueError(f'Checkpoint solution checksum mismatch: {solution}')
        yield record


def batch_plan(index, template, selected, waves_per_case, pallets_per_zone, variant_count, budget):
    zone_of = {slot:z for z,slots in zone_slots(index.locations,template['zones']).items() for slot in slots}
    product_of = {p['zone']:p['sku'] for p in template['products']}
    counts, over_budget = Counter(), []
    evaluations = 0
    for ordinal,start in enumerate(range(0,len(selected),waves_per_case)):
        cohort = selected[start:start+waves_per_case]
        if (max(index.dates[w] for w in cohort)-min(index.dates[w] for w in cohort)).total_seconds()/60 >= template['duration_minutes']:
            raise ValueError(f'Source cohort {ordinal} arrivals exceed the simulation horizon')
        touched = {r['locations'] for w in cohort for r in index.rows_by_wave[w] if r['locations'] in index.locations}
        by_zone = Counter(zone_of[s] for s in touched)
        by_sku = Counter()
        for zone,n in by_zone.items():
            by_sku[product_of[zone]] += min(n,pallets_per_zone) if pallets_per_zone is not None else n
        domain = math.prod(math.factorial(n) for n in by_sku.values())*math.prod(
            len(set(z.get('setpoint_options_c',[z['setpoint_c']]))) for z in template['zones'])
        if domain > budget:
            over_budget.append({'cohort':ordinal,'evaluations_per_variant':domain})
        evaluations += domain*variant_count
        group = case_group({'pmc_provenance':{'source_sha256':index.sha256,'selected_source_waves':cohort}})
        bucket = int(hashlib.sha256(group.encode()).hexdigest()[:8],16)%100
        counts['train' if bucket<80 else 'validation' if bucket<90 else 'test'] += variant_count
    return dict(planned_records=len(selected)//waves_per_case*variant_count,
                planned_splits={name:counts[name] for name in ('train','validation','test')},
                exact_candidate_evaluations=evaluations,over_budget_cohorts=over_budget)


def build_batch(source, template, scenario, grid, directory, cases=30,
                wave_offset=0, waves_per_case=1, pallets_per_zone=2,
                allow_estimated=False, max_evaluations=2000, *, resume=False,
                cache_dir='runs/cache', variant_suite='single',
                near_expiry=(0.0001,0.008), progress_callback=None, dry_run=False):
    if cases < 1 or waves_per_case < 1 or wave_offset < 0:
        raise ValueError('Batch size/waves per case must be positive and offset nonnegative')
    if len(near_expiry) != 2 or not 0 < near_expiry[0] <= near_expiry[1] <= 1:
        raise ValueError('Near-expiry fractions must lie within (0,1]')
    require_calibration(template.get('kinetic_provenance'),allow_estimated)
    pool = [] if scenario is None else scenario if isinstance(scenario,list) else [scenario]
    # Validate the recipe before creating any job outputs.
    variant_count = len(variants(template,pool,0,variant_suite,near_expiry))
    started = time.perf_counter()
    index = PMCIndex(source,cache_dir)
    end = wave_offset+cases*waves_per_case
    selected = index.eligible_waves[wave_offset:end]
    if len(selected) != cases*waves_per_case:
        raise ValueError(f'Requested batch exceeds {len(index.eligible_waves)} eligible storage-pick waves')
    plan = batch_plan(index,template,selected,waves_per_case,pallets_per_zone,variant_count,max_evaluations)
    if plan['over_budget_cohorts']:
        raise ValueError(f"{len(plan['over_budget_cohorts'])} cohorts exceed the exact-solver budget; lower pallets per zone or increase the budget")
    if dry_run:
        return dict(status='planned',**plan,eligible_waves=len(index.eligible_waves),
                    ineligible_waves=len(index.ineligible_waves),cache_status=index.cache_status)
    directory = Path(directory)
    specification = dict(version=RUN_VERSION,source_sha256=index.sha256,template=template,pool=pool,grid=grid,
                         wave_offset=wave_offset,waves_per_case=waves_per_case,pallets_per_zone=pallets_per_zone,
                         allow_estimated=allow_estimated,max_evaluations=max_evaluations,
                         variant_suite=variant_suite,near_expiry=list(near_expiry),implementation=implementation_digest())
    identity = fingerprint(specification)
    with job_lock(directory):
        run_path = directory/'run.json'
        if run_path.exists():
            if not resume:
                raise ValueError('Output already contains a batch; use --resume or a new directory')
            run = json.loads(run_path.read_text())
            if run['run_fingerprint'] != identity:
                raise ValueError('Resume inputs/settings/code differ from the checkpoint; use a new directory')
            if cases < run['target_cases']:
                raise ValueError('Resume cannot shrink the existing batch target')
        else:
            existing = [p.name for p in directory.iterdir() if p.name != 'run.lock']
            if existing:
                raise ValueError('Output directory is not an empty checkpointed run; choose a new directory')
            run = dict(run_fingerprint=identity,specification=specification,total_active_seconds=0)
        records = list(checkpoint_records(directory,identity))
        completed = {r['key']:r for r in records}
        run.update(target_cases=cases,expected_records=cases*variant_count,status='running')
        atomic_json(run_path,run)
        resumed = len(completed)
        solved_now, errors = 0, []
        (directory/'records').mkdir(exist_ok=True)
        # This journal is a live preview; atomic per-record checkpoints are the
        # authority. Rebuilding it repairs an interruption between commit/append.
        journal_path = directory/'completed.jsonl'
        with journal_path.open('w') as journal:
            for record in records:
                journal.write(json.dumps(record['pair'],allow_nan=False)+'\n')
        def progress(status='running'):
            value = dict(status=status,target_cases=cases,expected_records=cases*variant_count,
                         completed_records=len(completed),resumed_records=resumed,solved_this_run=solved_now,
                         failures_this_run=len(errors),elapsed_seconds=time.perf_counter()-started)
            atomic_json(directory/'progress.json',value)
            return value
        progress()
        try:
            with journal_path.open('a') as journal:
                for cohort_index in range(cases):
                    cohort = selected[cohort_index*waves_per_case:(cohort_index+1)*waves_per_case]
                    base = copy.deepcopy(template)
                    base['seed'] += cohort_index
                    base,report = convert(source,base,max_waves=waves_per_case,max_pallets_per_zone=pallets_per_zone,
                                          index=index,wave_ids=cohort)
                    base['grid_intensity'] = grid
                    base['workload_replay'] = dict(grid_start_utc=grid['start_utc'],
                        semantics='Source workloads replayed against this cached grid interval, not source wall-clock alignment.',
                        scenario_provenance='Recorded pool rotation and/or explicitly procedural variants; not independent LLM generations.')
                    group = case_group(base)
                    for ordinal,(name,event,life_range) in enumerate(variants(base,pool,cohort_index,variant_suite,near_expiry)):
                        key = f'{cohort_index:06d}-{ordinal:02d}'
                        if key in completed:
                            continue
                        config = copy.deepcopy(base)
                        if life_range is not None:
                            aged_template = copy.deepcopy(template)
                            aged_template.update(seed=base['seed'],initial_life_fraction=life_range)
                            config,_ = convert(source,aged_template,max_waves=waves_per_case,max_pallets_per_zone=pallets_per_zone,
                                               index=index,wave_ids=cohort)
                            config['grid_intensity'] = grid
                            config['workload_replay'] = base['workload_replay']
                        config['augmentation_variant'] = name
                        apply_scenario(config,event)
                        try:
                            solution = solve(index.locations,config,max_evaluations=max_evaluations)
                            pair = make_pair(index.locations,config,solution,group)
                            pair['metadata']['augmentation_variant'] = name
                            metrics = dict(index=cohort_index,variant=name,source_waves=cohort,
                                selected_pick_rows=report['selected_pick_rows'],outside_window_rows=report['excluded_outside_decision_window_rows'],
                                nonstorage_rows=report['excluded_nonstorage_rows'],pallets=report['synthetic_pallets'],
                                evaluations=solution['evaluations'],kg_food_saved_vs_fifo=solution['kg_food_saved_vs_fifo'],
                                has_disruption_impact=solution['disruption_effect'].get('has_physical_or_dispatch_impact',False),
                                disruption_kinds=sorted({d['kind'] for d in config['disruptions']}),
                                scenario_provider=event.get('generation',{}).get('provider','unspecified'))
                            solution_file = f'solution-{key}.json'
                            atomic_json(directory/solution_file,solution)
                            record = dict(run_fingerprint=identity,key=key,pair=pair,cohort=metrics,
                                          pair_sha256=fingerprint(pair),solution_file=solution_file,
                                          solution_sha256=file_sha256(directory/solution_file))
                            atomic_json(directory/'records'/f'{key}.json',record)
                            completed[key] = record
                            solved_now += 1
                            journal.write(json.dumps(pair,allow_nan=False)+'\n')
                            journal.flush()
                            failure = directory/'failures'/f'{key}.json'
                            if failure.exists():
                                failure.unlink()
                        except (ValueError,KeyError,TypeError) as exc:
                            failure = dict(key=key,source_waves=cohort,variant=name,error_type=type(exc).__name__,error=str(exc))
                            atomic_json(directory/'failures'/f'{key}.json',failure)
                            errors.append(failure)
                        state = progress()
                        if progress_callback:
                            progress_callback(state)
        except BaseException:
            run.update(status='interrupted',total_active_seconds=run['total_active_seconds']+time.perf_counter()-started)
            atomic_json(run_path,run)
            progress('interrupted')
            raise
        manifest = write_pairs((r['pair'] for r in sorted(completed.values(),key=lambda r:r['key'])),directory)
        verification = verify_export(index.locations,directory)
        cohorts = [r['cohort'] for r in sorted(completed.values(),key=lambda r:r['key'])]
        elapsed = time.perf_counter()-started
        status = 'complete' if len(completed)==cases*variant_count else 'incomplete'
        manifest.update(status=status,expected_records=cases*variant_count,run_fingerprint=identity)
        atomic_json(directory/'manifest.json',manifest)
        summary = dict(status=status,records=manifest['records'],expected_records=cases*variant_count,
            splits=manifest['splits'],independent_source_workload_cohorts=cases,
            source_rows_considered=sum(len(index.rows_by_wave[w]) for w in selected),
            source_index=dict(total_waves=len(index.ordered_waves),eligible_waves=len(index.eligible_waves),
                              ineligible_waves=len(index.ineligible_waves),cache_status=index.cache_status,
                              skipped_before_last_selected=sum(index.raw_offsets[w]<=index.raw_offsets[selected[-1]] for w in index.ineligible_waves)),
            total_solver_evaluations=sum(c['evaluations'] for c in cohorts),resumed_records=resumed,solved_this_run=solved_now,
            positive_food_saved_cases=sum(c['kg_food_saved_vs_fifo']>0 for c in cohorts),
            no_disruption_control_cases=sum(not c['disruption_kinds'] for c in cohorts),
            neutral_disruption_cases=sum(bool(c['disruption_kinds']) and not c['has_disruption_impact'] for c in cohorts),
            impactful_disruption_cases=sum(bool(c['disruption_kinds']) and c['has_disruption_impact'] for c in cohorts),
            variant_counts=dict(Counter(c['variant'] for c in cohorts)),
            disruption_kind_counts=dict(Counter(k for c in cohorts for k in c['disruption_kinds'])),
            scenario_provider_counts=dict(Counter(c['scenario_provider'] for c in cohorts)),
            calibration_kind=template['kinetic_provenance']['target_kind'],
            initial_life_fraction=template.get('initial_life_fraction',[0.5,1]),
            near_expiry_fraction=list(near_expiry),elapsed_seconds=elapsed,
            active_seconds_total=run['total_active_seconds']+elapsed,
            seconds_per_new_record=elapsed/solved_now if solved_now else None,
            cohorts=cohorts,failures=errors,verification=verification,
            limitations='Simulation labels. Normal/near-expiry controls and procedural faults are attributed separately from replayed LLM responses. Grid profile is replayed; no field or trained-policy performance claim.')
        atomic_json(directory/'batch-summary.json',summary)
        run.update(status=status,total_active_seconds=summary['active_seconds_total'])
        atomic_json(run_path,run)
        progress(status)
        return summary
