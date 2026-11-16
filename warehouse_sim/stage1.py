"""Stage 1 command-line pipeline. No visual/VLA dependencies."""
import argparse
import copy
import json
from pathlib import Path
import sys
import zipfile

from .batch import build_batch
from .calibration import apply_calibration, calibrate, calibrate_cold_chain, require_calibration
from .carbon import fetch
from .dataset import case_group, make_pair, write_pairs, verify_export, merge_exports
from .layout import load_layout
from .inspect_data import inspect
from .llm import apply_scenario, generate
from .literature import build_profile
from .optimizer import solve
from .pmc import convert
from .pool import generate_pool, load_pool


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('paper-profile', help='Import reviewed supplemental shelf-life tables into an explicit three-fruit model')
    p.add_argument('--supplement', type=Path, required=True)
    p.add_argument('--template', type=Path, default=Path('examples/simulation.json'))
    p.add_argument('--output', type=Path, required=True)
    p = commands.add_parser('batch-build', help='Build and verify disjoint PMC workload cohorts with a recorded scenario')
    p.add_argument('--dataset', type=Path, required=True)
    p.add_argument('--template', type=Path, required=True)
    p.add_argument('--scenario', type=Path, action='append', help='Recorded scenario; repeat to rotate a pool')
    p.add_argument('--scenario-dir', type=Path, help='Completed generate-pool output')
    p.add_argument('--resume', action='store_true')
    p.add_argument('--dry-run', action='store_true', help='Check eligible cohorts, planned split counts and exact-solver budgets without solving')
    p.add_argument('--cache-dir', type=Path, default=Path('runs/cache'))
    p.add_argument('--variant-suite', choices=['single','standard'], default='single')
    p.add_argument('--near-expiry-fraction', type=float, nargs=2, default=[0.0001,0.008])
    p.add_argument('--grid', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--cases', type=int, default=30)
    p.add_argument('--wave-offset', type=int, default=0)
    p.add_argument('--waves-per-case', type=int, default=1)
    p.add_argument('--max-pallets-per-zone', type=int, default=2)
    p.add_argument('--max-evaluations', type=int, default=2000)
    p.add_argument('--allow-estimated-calibration', action='store_true')
    p.add_argument('--initial-life-fraction', type=float, nargs=2, metavar=('LOW','HIGH'),
                   help='Explicit synthetic aged-stock augmentation as fractions of full reference life')
    p = commands.add_parser('merge', help='Verify and merge source exports while preserving workload-group splits')
    p.add_argument('--dataset', type=Path, required=True)
    p.add_argument('--export', type=Path, action='append', required=True)
    p.add_argument('--output', type=Path, required=True)
    p = commands.add_parser('verify', help='Replay JSONL metrics and FIFO food-saved labels')
    p.add_argument('--dataset', type=Path, required=True)
    p.add_argument('--export', type=Path, required=True)
    p = commands.add_parser('inspect-data', help='Inspect downloaded CSV/ZIP source fields')
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p = commands.add_parser('convert', help='Convert PMC coordinates and selected real pick waves to synthetic produce')
    p.add_argument('--dataset', type=Path, required=True)
    p.add_argument('--template', type=Path, default=Path('examples/simulation.json'))
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--max-waves', type=int, default=5)
    p.add_argument('--wave-offset', type=int, default=0)
    p.add_argument('--kg-per-unit', type=float, default=1.0)
    p.add_argument('--arrival-scale', type=float, default=1.0)
    p.add_argument('--max-pallets-per-zone', type=int)
    p = commands.add_parser('calibrate', help='Fit rates to time-temperature-quality CSV')
    p.add_argument('--logs', type=Path, required=True)
    p.add_argument('--config', type=Path, default=Path('examples/simulation.json'))
    p.add_argument('--output', type=Path, required=True)
    p = commands.add_parser('calibrate-cold-chain', help='Fit an explicitly estimated-target seed model from aggregate transport records')
    p.add_argument('--logs', type=Path, required=True)
    p.add_argument('--config', type=Path, default=Path('examples/simulation.json'))
    p.add_argument('--mapping', type=Path, required=True)
    p.add_argument('--allow-estimated-targets', action='store_true')
    p.add_argument('--allow-extrapolation', action='store_true')
    p.add_argument('--output', type=Path, required=True)
    p = commands.add_parser('fetch-grid', help='Cache official GB half-hourly grid data')
    p.add_argument('--date', required=True)
    p.add_argument('--start', required=True, help='ISO timestamp including offset')
    p.add_argument('--minutes', type=float, default=480)
    p.add_argument('--output', type=Path, required=True)
    p = commands.add_parser('generate-pool', help='Generate a resumable pool of varied 4-bit LLM disruptions')
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--model', required=True)
    p.add_argument('--provider', choices=['ollama','unsloth'], default='ollama')
    p.add_argument('--ollama-url', default='http://localhost:11434')
    p.add_argument('--count', type=int, default=24)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--attempts', type=int, default=3)
    p.add_argument('--resume', action='store_true')
    p.add_argument('--output', type=Path, required=True)
    p = commands.add_parser('generate', help='Generate and validate an edge case with a local 4-bit model')
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--model', required=True)
    p.add_argument('--provider', choices=['ollama', 'unsloth'], default='ollama')
    p.add_argument('--ollama-url', default='http://localhost:11434')
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--output', type=Path, required=True)
    for name in ('solve', 'build'):
        p = commands.add_parser(name, help='Optimize paired simulations'+(' and write chat JSONL' if name=='build' else ''))
        p.add_argument('--dataset', type=Path, required=True)
        p.add_argument('--config', type=Path, required=True)
        p.add_argument('--scenario', type=Path, action='append', help='Validated generation output; repeat for multiple variants')
        p.add_argument('--grid', type=Path, help='Cached fetch-grid output')
        p.add_argument('--method', choices=['exhaustive', 'genetic'], default='exhaustive')
        p.add_argument('--max-evaluations', type=int, default=2000)
        p.add_argument('--generations', type=int, default=8)
        p.add_argument('--population', type=int, default=16)
        p.add_argument('--weights', type=Path, help='JSON objective weights')
        p.add_argument('--output', type=Path, required=True)
        p.add_argument('--allow-best-known', action='store_true')
        p.add_argument('--require-calibrated', action='store_true')
        p.add_argument('--allow-estimated-calibration', action='store_true',
                       help='Explicitly permit an estimated-target surrogate when requiring fitted kinetics')
        p.add_argument('--require-measured-grid', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'paper-profile':
            config, report = build_profile(args.supplement, read(args.template))
            write(args.output, config)
            write(args.output.with_suffix('.literature.json'), report)
            print(json.dumps({k:report[k] for k in ('target_kind','source_sha256','source_tables','unused_printed_rate_audit')}, indent=2))
        elif args.command == 'batch-build':
            template = read(args.template)
            if args.initial_life_fraction:
                template['initial_life_fraction'] = args.initial_life_fraction
            pool = [read(path) for path in args.scenario or []]
            if args.scenario_dir:
                pool.extend(load_pool(args.scenario_dir))
            def show_progress(value):
                if value['completed_records']%10==0:
                    print(json.dumps(value),flush=True)
            summary = build_batch(args.dataset, template, pool, read(args.grid), args.output, args.cases,
                                  args.wave_offset, args.waves_per_case, args.max_pallets_per_zone,
                                  args.allow_estimated_calibration, args.max_evaluations,
                                  resume=args.resume,cache_dir=args.cache_dir,variant_suite=args.variant_suite,
                                  near_expiry=args.near_expiry_fraction,progress_callback=show_progress,dry_run=args.dry_run)
            print(json.dumps({k:v for k,v in summary.items() if k!='cohorts'}, indent=2))
            if summary['status'] not in ('complete','planned'):
                return 2
        elif args.command == 'merge':
            print(json.dumps(merge_exports(load_layout(args.dataset), args.export, args.output), indent=2))
        elif args.command == 'verify':
            print(json.dumps(verify_export(load_layout(args.dataset), args.export), indent=2))
        elif args.command == 'inspect-data':
            report = inspect(args.data)
            write(args.output, report)
            print(json.dumps(report, indent=2))
        elif args.command == 'convert':
            config, report = convert(args.dataset, read(args.template), args.max_waves, args.kg_per_unit,
                                     args.arrival_scale, args.max_pallets_per_zone, args.wave_offset)
            write(args.output, config)
            print(json.dumps(report, indent=2))
        elif args.command == 'calibrate':
            config = read(args.config)
            references = {p['sku']:p['reference_temp_c'] for p in config['products']}
            report = calibrate(args.logs, references)
            write(args.output, apply_calibration(config, report))
            write(args.output.with_suffix('.calibration.json'), report)
            print(json.dumps(report, indent=2))
        elif args.command == 'calibrate-cold-chain':
            config = read(args.config)
            report = calibrate_cold_chain(args.logs, config, read(args.mapping), args.allow_estimated_targets, args.allow_extrapolation)
            write(args.output, apply_calibration(config, report))
            write(args.output.with_suffix('.calibration.json'), report)
            print(json.dumps(report, indent=2))
        elif args.command == 'fetch-grid':
            value = fetch(args.date, args.start, args.minutes)
            write(args.output, value)
            print(f'Cached {len(value["intervals"])} intervals from {value["source"]}')
        elif args.command == 'generate-pool':
            result = generate_pool(read(args.config),args.model,args.output,args.count,args.provider,
                                   args.ollama_url,args.seed,args.resume,args.attempts,
                                   progress_callback=lambda p:print(json.dumps(p),flush=True))
            print(json.dumps(result,indent=2))
        elif args.command == 'generate':
            value = generate(read(args.config), args.model, args.provider, args.ollama_url, args.seed)
            write(args.output, value)
            print(json.dumps({'description':value['description'], 'disruptions':value['disruptions']}, indent=2))
        else:
            locations = load_layout(args.dataset)
            base = read(args.config)
            if args.grid:
                base['grid_intensity'] = read(args.grid)
            if args.require_calibrated:
                require_calibration(base.get('kinetic_provenance'), args.allow_estimated_calibration)
            if args.require_measured_grid and base.get('grid_intensity', {}).get('source') != 'https://api.carbonintensity.org.uk':
                raise ValueError('Research run requires cached official GB grid response')
            variants = [read(path) for path in args.scenario] if args.scenario else [None]
            base_id = case_group(base)
            pairs = []
            for index, scenario in enumerate(variants):
                config = copy.deepcopy(base)
                if scenario:
                    apply_scenario(config, scenario)
                solution = solve(locations, config, args.method, args.max_evaluations, args.generations,
                                 args.population, read(args.weights) if args.weights else None)
                target = args.output if len(variants)==1 and args.command=='solve' else args.output/f'solution-{index:04d}.json'
                write(target, solution)
                if args.command == 'build':
                    pairs.append(make_pair(locations, config, solution, base_id, args.allow_best_known))
                print(json.dumps({k:solution[k] for k in ('status','evaluations','objective','kg_food_saved_vs_fifo','kg_food_saved_vs_fefo')}, indent=2))
            if args.command == 'build':
                print(json.dumps(write_pairs(pairs, args.output), indent=2))
    except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile, ImportError) as exc:
        print(f'Stage 1 failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
