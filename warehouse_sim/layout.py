import csv
from dataclasses import dataclass
import io
import math
from pathlib import Path
import zipfile


@dataclass(frozen=True)
class Location:
    id: str
    x: float
    y: float
    z: float


def load_layout(path):
    """Read the original CSV directly or from the supplied dataset archive."""
    path = Path(path)
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if Path(n).name == 'Storage_Location.csv']
            if len(names) != 1:
                raise ValueError('Archive must contain exactly one Storage_Location.csv')
            text = archive.read(names[0]).decode('utf-8-sig')
    else:
        text = path.read_text(encoding='utf-8-sig')
    locations = {}
    for row in csv.DictReader(io.StringIO(text)):
        name = row['originalLocation'].strip()
        coords = [float(row[k]) for k in ('x', 'y', 'z')]
        if not name or name in locations or not all(math.isfinite(v) for v in coords):
            raise ValueError('Layout has duplicate/empty IDs or invalid coordinates')
        locations[name] = Location(name, *coords)
    if not locations:
        raise ValueError('Layout is empty')
    return locations


def zone_slots(locations, zone_configs):
    """Assign original aisle prefixes to synthetic thermal zones, explicitly."""
    result, used = {}, set()
    for zone in zone_configs:
        if zone['id'] in result:
            raise ValueError('Duplicate zone ID')
        slots = sorted(k for k in locations if k.split('-')[0] in zone['aisles'])
        if not slots or used.intersection(slots):
            raise ValueError('Zone aisle mapping is empty or overlapping')
        used.update(slots)
        result[zone['id']] = slots
    if used != set(locations):
        raise ValueError('Every layout location must map to exactly one zone')
    return result
