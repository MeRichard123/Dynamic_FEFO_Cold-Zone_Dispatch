"""Deterministic workload variants and explicitly attributed scenario rotation."""
import copy
import random

from .disruptions import validate_events

VARIANTS = ('normal', 'near_expiry', 'sensor_drift', 'disruption')


def procedural(config, seed, kind):
    rng = random.Random(seed)
    zone = rng.choice(config['zones'])['id']
    start = round(rng.uniform(0,min(30,config['duration_minutes']*0.2)),3)
    duration = round(min(rng.uniform(30,90),config['duration_minutes']-start),3)
    # A negative reading bias warms the true zone; it avoids cooling below
    # empirical curves whose first point is the initial zone temperature.
    value = round(rng.uniform(-2,-0.4),3) if kind == 'sensor_bias' else (
        round(rng.uniform(0,0.15),3) if kind == 'cooling_failure' else 1)
    event = dict(kind=kind,zone=zone,at_minute=start,duration_minutes=duration,value=value)
    validate_events([event],[z['id'] for z in config['zones']],config['duration_minutes'])
    return dict(description=f'Procedural {kind} in {zone}; seeded physical parameters, not an independent LLM response.',
                disruptions=[event], generation={'provider':'procedural_augmentation','seed':seed,'kind':kind})


def variants(config, pool, cohort_index, suite='single', near_expiry=(0.0001,0.008)):
    if suite == 'single':
        if not pool:
            raise ValueError('Single-scenario batching requires at least one scenario')
        return [('scenario',copy.deepcopy(pool[cohort_index%len(pool)]),None)]
    if suite != 'standard':
        raise ValueError('Unknown variant suite')
    seed = config['seed']*1009 + cohort_index
    normal = dict(description='Normal operation control.',disruptions=[],generation={'provider':'normal_control'})
    if pool and cohort_index%2 == 0:
        disruption = copy.deepcopy(pool[(cohort_index//2)%len(pool)])
    else:
        kind = 'cooling_failure' if (cohort_index//2)%2 == 0 else 'door_stuck'
        disruption = procedural(config,seed+2,kind)
    return [('normal',normal,None),('near_expiry',copy.deepcopy(normal),list(near_expiry)),
            ('sensor_drift',procedural(config,seed+1,'sensor_bias'),None),
            ('disruption',disruption,None)]
