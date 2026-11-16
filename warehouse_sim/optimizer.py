"""Simulation-in-the-loop multi-objective search.

Hu et al. motivates GA scheduling: https://doi.org/10.1109/ACCESS.2023.3295819
Our permutation/target encoding and operators are independent, not its adaptive GA.
Exhaustive mode provides an exact result only over the declared finite domain.
"""
import copy
import itertools
import math
import random

from .engine import Simulation

DEFAULT_WEIGHTS = {'expired_kg': 1.0, 'unfilled_kg': 2.0, 'compressor_kwh': 0.1,
                   'grid_kg_co2': 0.1, 'dispatched_life_kg_hours': -0.001}


def score(summary, weights):
    return sum(weights[key]*summary[key] for key in weights)


def metrics(summary):
    return {key: summary[key] for key in (*DEFAULT_WEIGHTS, 'dispatched_kg', 'remaining_kg', 'mass_balance_error_kg')}


def solve(locations, config, method='exhaustive', max_evaluations=2000, generations=8, population=16, weights=None):
    if method not in ('exhaustive', 'genetic'):
        raise ValueError('Solver method must be exhaustive or genetic')
    if max_evaluations < 1 or generations < 1 or population < 2:
        raise ValueError('Invalid solver budget')
    weights = dict(DEFAULT_WEIGHTS if weights is None else weights)
    if not weights or not set(weights).issubset(DEFAULT_WEIGHTS) or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in weights.values()):
        raise ValueError('Objective weights must be finite and refer to supported metrics')
    seed_sim = Simulation(locations, config)
    # Freeze the exact same initial inventory for every candidate and counterfactual.
    base = copy.deepcopy(config)
    base['initial_pallets'] = copy.deepcopy(seed_sim.initial_pallets)
    base.pop('incoming_pallets', None)
    groups = []
    for sku in sorted({p['sku'] for p in seed_sim.pallets}):
        groups.append(tuple(sorted(p['id'] for p in seed_sim.pallets if p['sku'] == sku)))
    zone_ids, choices = [], []
    for z in config['zones']:
        low = max([z.get('min_setpoint_c', z['setpoint_c'])] + [p['min_temp_c'] for p in seed_sim.pallets if p['zone'] == z['id']])
        high = min([z.get('max_setpoint_c', z['setpoint_c'])] + [p['max_temp_c'] for p in seed_sim.pallets if p['zone'] == z['id']])
        options = sorted(set(z.get('setpoint_options_c', [z['setpoint_c']])))
        if not options or not all(isinstance(t, (int, float)) and math.isfinite(t) and low <= t <= high for t in options):
            raise ValueError('Setpoint candidates must satisfy equipment and every stored product range')
        zone_ids.append(z['id'])
        choices.append(options)
    domain_size = math.prod(math.factorial(len(g)) for g in groups) * math.prod(len(c) for c in choices)
    if method == 'exhaustive' and domain_size > max_evaluations:
        raise ValueError(f'Exact search needs {domain_size} evaluations, above budget {max_evaluations}; use a smaller decision window or --method genetic (best-known labels only)')
    cache = {}
    best = None
    evaluated_metrics = []

    def evaluate(gene):
        nonlocal best
        if gene in cache:
            return cache[gene]
        candidate = copy.deepcopy(base)
        orders, targets = gene
        candidate['policy'] = 'planned'
        candidate['pallet_priority'] = list(itertools.chain.from_iterable(orders))
        for zone, target in zip(candidate['zones'], targets):
            zone['setpoint_c'] = target
        sim = Simulation(locations, candidate)
        summary = sim.run()
        value = score(summary, weights)
        cache[gene] = value
        evaluated_metrics.append(metrics(summary))
        if best is None or value < best[0] - 1e-10:
            best = (value, gene, summary, sim.events, candidate)
        return value

    default_targets = tuple(z['setpoint_c'] for z in config['zones'])
    if not all(t in c for t, c in zip(default_targets, choices)):
        raise ValueError('Setpoint options must include the initial setpoint')
    default = (tuple(groups), default_targets)
    evaluate(default)
    if method == 'exhaustive':
        permutations = [list(itertools.permutations(g)) for g in groups]
        for orders in itertools.product(*permutations):
            for targets in itertools.product(*choices):
                evaluate((orders, targets))
        status = 'optimal_in_declared_domain'
    else:
        rng = random.Random(config['seed'])
        def random_gene():
            return (tuple(tuple(rng.sample(g, len(g))) for g in groups), tuple(rng.choice(c) for c in choices))
        pool = [default] + [random_gene() for _ in range(population-1)]
        for generation in range(generations):
            for gene in pool:
                if gene not in cache and len(cache) >= max_evaluations:
                    break
                evaluate(gene)
            ranked = sorted((g for g in pool if g in cache), key=lambda g: cache[g])
            parents = ranked[:max(1, len(ranked)//2)]
            pool = [parents[0]]
            while len(pool) < population:
                a, b = rng.choice(parents), rng.choice(parents)
                orders = []
                for ga, gb in zip(a[0], b[0]):
                    cut = rng.randrange(len(ga)+1)
                    child = list(ga[:cut]) + [p for p in gb if p not in ga[:cut]]
                    if len(child) > 1 and rng.random() < 0.5:
                        i, j = rng.sample(range(len(child)), 2)
                        child[i], child[j] = child[j], child[i]
                    orders.append(tuple(child))
                targets = tuple(rng.choice(c) if rng.random() < 0.3 else rng.choice((ta, tb)) for c,ta,tb in zip(choices,a[1],b[1]))
                pool.append((tuple(orders), targets))
        status = 'best_known_no_optimality_proof'
    baselines = {}
    disrupted_fefo = None
    for policy in ('fifo', 'fefo'):
        candidate = copy.deepcopy(base)
        candidate['policy'] = policy
        candidate.pop('pallet_priority', None)
        baseline_sim = Simulation(locations, candidate)
        baseline = baseline_sim.run()
        baselines[policy] = dict(metrics(baseline), objective=score(baseline, weights))
        if policy == 'fefo':
            disrupted_fefo = baseline_sim
    disruption_effect = {'disruptions_present': bool(base.get('disruptions'))}
    if base.get('disruptions'):
        undisturbed_config = copy.deepcopy(base)
        undisturbed_config.update(policy='fefo', disruptions=[])
        undisturbed_config.pop('pallet_priority', None)
        undisturbed = Simulation(locations, undisturbed_config)
        undisturbed_summary = undisturbed.run()
        reference_trace = {(r['minute'], r['zone']): r for r in undisturbed.trace}
        temperature_delta = max((abs(r['temperature_c'] - reference_trace[(r['minute'],r['zone'])]['temperature_c'])
                                 for r in disrupted_fefo.trace if (r['minute'],r['zone']) in reference_trace), default=0)
        metric_delta = {k: baselines['fefo'][k] - undisturbed_summary[k] for k in DEFAULT_WEIGHTS}
        disruption_effect.update(max_physical_temperature_change_c=temperature_delta,
                                 fefo_metric_changes=metric_delta,
                                 has_physical_or_dispatch_impact=temperature_delta > 1e-6 or any(abs(v) > 1e-6 for v in metric_delta.values()),
                                 note='Realized effect from paired FEFO simulations; generated prose is not a physics prediction.')
    value, gene, summary, events, candidate = best
    # Keep a nondominated set of objective vectors, not an unsupported optimality claim.
    pareto = []
    directions = {k: 1 if v >= 0 else -1 for k,v in weights.items() if v != 0}
    unique = {tuple(m[k] for k in directions):m for m in evaluated_metrics}
    vectors = list(unique.values())
    for m in vectors:
        if not any(all(n[k]*d <= m[k]*d + 1e-9 for k,d in directions.items()) and
                   any(n[k]*d < m[k]*d - 1e-9 for k,d in directions.items()) for n in vectors):
            pareto.append(m)
    return dict(status=status, method=method, objective=value, weights=weights, evaluations=len(cache),
                decision_domain={'pallet_order_groups': [list(g) for g in groups],
                                 'setpoint_options_c': dict(zip(zone_ids, choices)), 'size': domain_size,
                                 'fixed': 'greedy put-away before planning, wave arrival order, no idling/relocation, static setpoints, original picking rules'},
                plan={'put_away': seed_sim.put_away, 'pallet_priority': candidate['pallet_priority'], 'zone_setpoints_c': dict(zip(zone_ids, gene[1]))},
                metrics=metrics(summary), baselines=baselines,
                disruption_effect=disruption_effect,
                kg_food_saved_vs_fifo=baselines['fifo']['expired_kg']-summary['expired_kg'],
                kg_food_saved_vs_fefo=baselines['fefo']['expired_kg']-summary['expired_kg'],
                pareto_metrics=pareto, events=events, replay_config=candidate)
