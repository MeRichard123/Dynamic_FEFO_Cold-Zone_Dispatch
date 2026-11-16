import argparse
import csv
import json
from pathlib import Path
import sys
import zipfile

from .engine import Simulation
from .layout import load_layout


def main():
    parser = argparse.ArgumentParser(description='Run a synthetic cold-chain simulation on the PMC layout')
    parser.add_argument('--dataset', type=Path, required=True, help='PMC ZIP archive or Storage_Location.csv')
    parser.add_argument('--config', type=Path, default=Path('examples/simulation.json'))
    parser.add_argument('--output', type=Path, default=Path('runs/demo'))
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text())
        simulation = Simulation(load_layout(args.dataset), config)
        result = simulation.run()
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / 'config.json').write_text(json.dumps(config, indent=2) + '\n')
        (args.output / 'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
        with (args.output / 'events.jsonl').open('w') as f:
            for event in simulation.events:
                f.write(json.dumps(event, allow_nan=False) + '\n')
        with (args.output / 'temperatures.csv').open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['minute', 'zone', 'temperature_c', 'measured_temperature_c', 'door_open', 'compressor_kwh', 'grid_carbon_kg'])
            writer.writeheader()
            writer.writerows(simulation.trace)
        with (args.output / 'layout.csv').open('w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['slot', 'zone', 'source_x', 'source_y', 'source_z'])
            for zid, slots in simulation.slots.items():
                for slot in slots:
                    loc = simulation.locations[slot]
                    writer.writerow([slot, zid, loc.x, loc.y, loc.z])
        print(json.dumps({key: result[key] for key in ('layout_locations', 'dispatched_kg', 'expired_kg', 'remaining_kg', 'compressor_kwh', 'grid_kg_co2', 'mass_balance_error_kg')}, indent=2))
        print(f'Artifacts written to {args.output}')
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        print(f'Cannot run simulation: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
