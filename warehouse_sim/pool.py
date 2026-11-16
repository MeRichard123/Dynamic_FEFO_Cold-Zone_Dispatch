"""Resumable local-LLM scenario pool; never substitutes scripted responses."""
import json
from pathlib import Path

from .dataset import fingerprint
from .disruptions import KINDS, validate_events
from .io_utils import atomic_json, file_sha256, job_lock
from .llm import generate
from .physics import pallet_factor


def model_support(config, scenario):
    """Reject obvious cold-side extrapolation before a long labeling run.

    This is conservative, not a substitute for the simulation's final checks.
    """
    zones = {z['id']:z for z in config['zones']}
    for event in scenario['disruptions']:
        if event['kind']=='sensor_bias' and event['value']>0:
            zone = zones[event['zone']]
            target = min(zone.get('setpoint_options_c',[zone['setpoint_c']]))-event['value']
            for product in config['products']:
                if product['zone']==event['zone']:
                    pallet_factor(product,target)


def generate_pool(config,model,directory,count=24,provider='ollama',url='http://localhost:11434',
                  seed=42,resume=False,attempts=3,progress_callback=None):
    if count < 1 or attempts < 1:
        raise ValueError('Pool size and attempt limit must be positive')
    directory = Path(directory)
    specification = dict(config=config,model=model,provider=provider,url=url,seed=seed,attempts=attempts,version=1)
    identity = fingerprint(specification)
    with job_lock(directory):
        path = directory/'pool-run.json'
        if path.exists():
            previous = json.loads(path.read_text())
            if not resume:
                raise ValueError('Scenario pool exists; use --resume or a new directory')
            if previous['run_fingerprint'] != identity or count < previous['count']:
                raise ValueError('Pool resume inputs differ or target shrank')
        elif any(p.name != 'run.lock' for p in directory.iterdir()):
            raise ValueError('Scenario pool directory must be empty')
        atomic_json(path,dict(run_fingerprint=identity,specification=specification,count=count,status='running'))
        items, seen = [], set()
        try:
            for i in range(count):
                output = directory/f'scenario-{i:04d}.json'
                kind = KINDS[i%len(KINDS)]
                if output.exists():
                    scenario = json.loads(output.read_text())
                    if scenario.get('pool_run_fingerprint') != identity:
                        raise ValueError('Scenario pool checkpoint identity mismatch')
                    validate_events(scenario['disruptions'],[z['id'] for z in config['zones']],config['duration_minutes'])
                    if not scenario['disruptions'] or any(e['kind']!=kind for e in scenario['disruptions']):
                        raise ValueError('Scenario pool checkpoint kind mismatch')
                    model_support(config,scenario)
                else:
                    for attempt in range(attempts):
                        try:
                            scenario = generate(config,model,provider,url,seed+i*attempts+attempt,kind=kind)
                            model_support(config,scenario)
                            if fingerprint(scenario['disruptions']) in seen:
                                raise ValueError('Duplicate numerical disruption scenario')
                            break
                        except ValueError as exc:
                            atomic_json(directory/'rejections'/f'{i:04d}-{attempt:02d}.json',
                                        dict(index=i,attempt=attempt,error=str(exc)))
                            if attempt+1==attempts:
                                raise
                    scenario['pool_run_fingerprint'] = identity
                    atomic_json(output,scenario)
                key = fingerprint(scenario['disruptions'])
                if key in seen:
                    raise ValueError('Duplicate numerical disruption scenario in pool')
                seen.add(key)
                items.append(dict(file=output.name,sha256=file_sha256(output),kind=kind))
                atomic_json(directory/'pool.json',dict(status='running',count=len(items),expected=count,scenarios=items))
                if progress_callback:
                    progress_callback({'completed_scenarios':len(items),'expected':count})
        except BaseException:
            atomic_json(path,dict(run_fingerprint=identity,specification=specification,count=count,status='interrupted'))
            raise
        result = dict(status='complete',count=len(items),expected=count,scenarios=items,
                      provider=provider,model=model,run_fingerprint=identity)
        atomic_json(directory/'pool.json',result)
        atomic_json(path,dict(run_fingerprint=identity,specification=specification,count=count,status='complete'))
        return result


def load_pool(directory):
    directory = Path(directory)
    manifest = json.loads((directory/'pool.json').read_text())
    if manifest['status'] != 'complete' or manifest['count'] != manifest['expected']:
        raise ValueError('Scenario pool is incomplete; resume generation before batching')
    result = []
    for item in manifest['scenarios']:
        path = directory/item['file']
        if file_sha256(path) != item['sha256']:
            raise ValueError('Scenario pool file checksum mismatch')
        result.append(json.loads(path.read_text()))
    return result
