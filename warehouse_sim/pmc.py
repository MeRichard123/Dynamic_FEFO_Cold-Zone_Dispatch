"""Explicit footwear-to-produce augmentation, preserving source lineage."""
import copy
import csv
from datetime import datetime
import hashlib
import io
import math
from pathlib import Path
import random
import zipfile

from .layout import Location, load_layout, zone_slots
from .io_utils import atomic_json
import json
from collections import defaultdict


def archive_csv(archive, name, delimiter=';'):
    matches = [n for n in archive.namelist() if Path(n).name == name]
    if len(matches) != 1:
        raise ValueError(f'Archive must contain exactly one {name}')
    return list(csv.DictReader(io.StringIO(archive.read(matches[0]).decode('utf-8-sig')), delimiter=delimiter))



class PMCIndex:
    """Read/index the archive once; optional SHA-keyed JSON cache across runs."""
    CACHE_VERSION = 2

    def __init__(self, path, cache_dir=None):
        self.path = Path(path)
        self.sha256 = hashlib.sha256(self.path.read_bytes()).hexdigest()
        cache = Path(cache_dir)/f'pmc-v{self.CACHE_VERSION}-{self.sha256}.json' if cache_dir else None
        payload = None
        self.cache_status = 'built_from_archive'
        if cache and cache.exists():
            try:
                candidate = json.loads(cache.read_text())
                expected_hash = candidate.pop('cache_sha256')
                actual_hash = hashlib.sha256(json.dumps(candidate,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                if expected_hash != actual_hash:
                    raise ValueError('cache checksum mismatch')
                if candidate['version'] == self.CACHE_VERSION and candidate['source_sha256'] == self.sha256:
                    # Detect truncated/incompatible cache structures before use.
                    if sum(len(rows) for rows in candidate['rows_by_wave'].values()) != candidate['source_pick_rows']:
                        raise ValueError('cache row count mismatch')
                    if set(candidate['dates']) != set(candidate['rows_by_wave']):
                        raise ValueError('cache wave index mismatch')
                    payload = candidate
                    self.cache_status = 'loaded_from_disk'
            except (ValueError,KeyError,TypeError):
                self.cache_status = 'rebuilt_invalid_cache'
        if payload is None:
            self.locations = load_layout(self.path)
            with zipfile.ZipFile(self.path) as archive:
                rows = archive_csv(archive,'Picking_Wave.csv')
                orders = archive_csv(archive,'Customer_Order.csv')
            dates, grouped = {}, defaultdict(list)
            for row in orders:
                wave = row['waveNumber'].strip()
                t = datetime.strptime(row['creationDate'],'%d/%m/%Y %H:%M')
                dates[wave] = min(t,dates.get(wave,t))
            for row in rows:
                grouped[row['waveNumber'].strip()].append({k:row[k].strip() for k in
                    ('locations','reference','quantityToPick (units)')})
            if set(grouped)-dates.keys():
                raise ValueError('Picking waves lack customer-order timestamps')
            payload = dict(version=self.CACHE_VERSION,source_sha256=self.sha256,
                           source_pick_rows=len(rows),rows_by_wave=dict(grouped),
                           dates={w:dates[w].isoformat() for w in grouped},
                           locations={k:[v.x,v.y,v.z] for k,v in self.locations.items()})
            if cache:
                checksum = hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                atomic_json(cache,dict(payload,cache_sha256=checksum))
        else:
            self.locations = {k:Location(k,*v) for k,v in payload['locations'].items()}
        self.rows_by_wave = payload['rows_by_wave']
        self.source_pick_rows = payload['source_pick_rows']
        self.dates = {w:datetime.fromisoformat(t) for w,t in payload['dates'].items()}
        self.ordered_waves = sorted(self.rows_by_wave,key=lambda w:(self.dates[w],int(w)))
        self.raw_offsets = {w:i for i,w in enumerate(self.ordered_waves)}
        self.eligible_waves = [w for w in self.ordered_waves if any(r['locations'] in self.locations for r in self.rows_by_wave[w])]
        eligible = set(self.eligible_waves)
        self.ineligible_waves = [w for w in self.ordered_waves if w not in eligible]


def convert(path, template, max_waves=5, kg_per_unit=1.0, arrival_scale=1.0, max_pallets_per_zone=None, wave_offset=0, index=None, wave_ids=None):
    """Map pick-row locations to zone produce; never claim shoes are real food."""
    if max_waves < 1 or kg_per_unit <= 0 or arrival_scale <= 0 or wave_offset < 0:
        raise ValueError('Wave limit and conversion factors must be positive')
    config = copy.deepcopy(template)
    life_range = config.get('initial_life_fraction', [0.5, 1.0])
    if (len(life_range) != 2 or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                      and math.isfinite(v) for v in life_range)
            or not 0 < life_range[0] <= life_range[1] <= 1):
        raise ValueError('initial_life_fraction must be [low, high] within (0, 1]')
    data = index if index is not None else PMCIndex(path)
    if data.path.resolve() != Path(path).resolve():
        raise ValueError('PMC index belongs to another source path')
    locations = data.locations
    slots = zone_slots(locations, config['zones'])
    zone_of = {s: z for z, values in slots.items() for s in values}
    products = {}
    for product in config['products']:
        if product['zone'] in products:
            raise ValueError('PMC converter needs one synthetic product prototype per zone')
        products[product['zone']] = product
    if set(products) != set(slots):
        raise ValueError('Every zone needs a product prototype')
    dates = data.dates
    all_waves = data.ordered_waves
    chosen = list(wave_ids) if wave_ids is not None else all_waves[wave_offset:wave_offset+max_waves]
    if len(set(chosen)) != len(chosen) or not set(chosen).issubset(data.rows_by_wave):
        raise ValueError('Invalid explicit source-wave selection')
    rows = [dict(row,waveNumber=w) for w in chosen for row in data.rows_by_wave[w]]
    if not chosen:
        raise ValueError('Requested source-wave window extends beyond the dataset')
    origin = min(dates[w] for w in chosen)
    selected = set(chosen)
    window_slots = set(locations)
    if max_pallets_per_zone is not None:
        if max_pallets_per_zone < 1:
            raise ValueError('Decision window must contain at least one pallet per zone')
        touched = {r['locations'].strip() for r in rows if r['waveNumber'].strip() in selected}
        window_slots = {s for zid, values in slots.items() for s in sorted(touched.intersection(values))[:max_pallets_per_zone]}
    excluded_window_rows = 0
    demand, slot_demand, source_refs = {}, {}, {}
    exclusions = {}
    selected_rows = 0
    for row in rows:
        wave = row['waveNumber'].strip()
        if wave not in selected:
            continue
        selected_rows += 1
        slot = row['locations'].strip()
        if slot not in locations:
            exclusions[slot] = exclusions.get(slot, 0) + 1
            continue
        if slot not in window_slots:
            excluded_window_rows += 1
            continue
        zid = zone_of[slot]
        sku = products[zid]['sku']
        amount = float(row['quantityToPick (units)']) * kg_per_unit
        if amount <= 0:
            raise ValueError('Source picking quantity must be positive')
        demand[(wave, sku)] = demand.get((wave, sku), 0) + amount
        slot_demand[slot] = slot_demand.get(slot, 0) + amount
        source_refs.setdefault(slot, set()).add(row['reference'].strip())
    if not slot_demand:
        raise ValueError('Selected waves contain no storage-location picks')
    config['waves'] = [dict(at_minute=(dates[w]-origin).total_seconds()/60*arrival_scale,
                            sku=sku, quantity_kg=amount, source_wave=w)
                       for (w, sku), amount in sorted(demand.items(), key=lambda item: (dates[item[0][0]], int(item[0][0]), item[0][1]))]
    latest = max(w['at_minute'] for w in config['waves'])
    if latest >= config['duration_minutes']:
        raise ValueError('Selected wave arrivals exceed horizon; extend duration or change arrival_scale')
    rng = random.Random(config['seed'])
    config['initial_pallets'] = []
    for slot, quantity in sorted(slot_demand.items()):
        zid = zone_of[slot]
        p = products[zid]
        config['initial_pallets'].append(dict(id='PMC-'+slot, sku=p['sku'], zone=zid, slot=slot,
                                             quantity_kg=quantity, remaining_life_hours=p['life_hours']*rng.uniform(*life_range),
                                             source_references=sorted(source_refs[slot])))
    digest = data.sha256
    report = dict(source_file=Path(path).name, source_sha256=digest, source_pick_rows=data.source_pick_rows,
                  source_wave_count=len(all_waves), selected_source_waves=chosen,
                  source_wave_offset=data.raw_offsets[chosen[0]],
                  source_wave_selection='explicit_cohort' if wave_ids is not None else 'raw_offset',
                  selected_pick_rows=selected_rows, excluded_nonstorage_rows=sum(exclusions.values()),
                  excluded_locations=exclusions, excluded_outside_decision_window_rows=excluded_window_rows,
                  max_pallets_per_zone=max_pallets_per_zone, layout_slots=len(locations),
                  zone_slots={z:len(s) for z,s in slots.items()}, synthetic_pallets=len(config['initial_pallets']),
                  kg_per_footwear_unit=kg_per_unit, arrival_time_scale=arrival_scale,
                  synthetic_initial_life_fraction=life_range,
                  source_first_timestamp=origin.isoformat(),
                  semantics='Synthetic produce by slot zone; reference IDs retained only for lineage. No food observations inferred.')
    config['pmc_provenance'] = report
    return config, report
