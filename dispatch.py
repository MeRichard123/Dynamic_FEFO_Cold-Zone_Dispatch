"""Phase 1 dispatch prototype. Standard library only; assumptions are illustrative."""
import argparse
import json
import math
from pathlib import Path
import sys
import urllib.error
import urllib.request

from warehouse_sim.physics import pallet_factor


class InputError(ValueError):
    pass


def number(value, name, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise InputError(f'{name} must be a finite number')
    if minimum is not None and value < minimum:
        raise InputError(f'{name} must be >= {minimum}')
    return value


def validate(state):
    if not isinstance(state, dict):
        raise InputError('State must be an object')
    for key in ('zones', 'pallets', 'orders'):
        if not isinstance(state.get(key), list):
            raise InputError(f'{key} must be a list')
    zone_ids, pallet_ids, slots = set(), set(), set()
    for z in state['zones']:
        zid = z.get('id')
        if not isinstance(zid, str) or not zid or zid in zone_ids:
            raise InputError('Zone IDs must be unique nonempty strings')
        zone_ids.add(zid)
        for k in ('temperature_c', 'setpoint_c', 'min_setpoint_c', 'max_setpoint_c'):
            number(z.get(k), k)
        if not z['min_setpoint_c'] <= z['setpoint_c'] <= z['max_setpoint_c']:
            raise InputError('Zone setpoint must be within equipment limits')
        if not isinstance(z.get('slots'), list):
            raise InputError('Zone slots must be a list')
        for slot in z['slots']:
            if not isinstance(slot, str) or not slot or slot in slots:
                raise InputError('Slot IDs must be unique nonempty strings')
            slots.add(slot)
    occupied = set()
    for p in state['pallets']:
        pid = p.get('id')
        if not isinstance(pid, str) or not pid or pid in pallet_ids:
            raise InputError('Pallet IDs must be unique nonempty strings')
        pallet_ids.add(pid)
        if not isinstance(p.get('sku'), str) or not p['sku']:
            raise InputError('Each pallet needs a SKU')
        for k in ('quantity_kg', 'remaining_life_hours', 'reference_temp_c', 'min_temp_c', 'max_temp_c'):
            number(p.get(k), k, 0 if k in ('quantity_kg', 'remaining_life_hours') else None)
        number(p.get('q10', 2), 'q10', 1)
        if p['min_temp_c'] > p['max_temp_c']:
            raise InputError('Pallet temperature range is reversed')
        slot = p.get('slot')
        if slot is not None:
            if slot not in slots or slot in occupied:
                raise InputError('Occupied slot must exist and contain only one pallet')
            occupied.add(slot)
    for o in state['orders']:
        if not isinstance(o.get('sku'), str) or not o['sku']:
            raise InputError('Each order needs a SKU')
        number(o.get('quantity_kg'), 'order quantity_kg', 0)
        number(o.get('min_remaining_hours', 0), 'min_remaining_hours', 0)
    return state


def life_at(pallet, temperature):
    """Zou et al. (2025), Eq. (1), normalized to reference-life hours.

    https://doi.org/10.1016/j.jfoodeng.2025.112577
    """
    try:
        rate = pallet_factor(pallet, temperature)
        return pallet['remaining_life_hours'] / rate
    except ValueError as exc:
        raise InputError(str(exc)) from exc



def plan(state):
    validate(state)
    zones = state['zones']
    slot_zone = {s: z for z in zones for s in z['slots']}
    occupied = {p['slot'] for p in state['pallets'] if p.get('slot') is not None}
    free = {s for s in slot_zone if s not in occupied}
    assignments, alerts, eligible = [], [], []
    # Most urgent arrivals are placed first. A slot represents one whole pallet.
    for p in sorted(state['pallets'], key=lambda p: (p['remaining_life_hours'], p['id'])):
        if p['remaining_life_hours'] <= 0:
            alerts.append(f"{p['id']}: no remaining life; hold for review")
            continue
        slot = p.get('slot')
        if slot is None:
            candidates = [s for s in free if p['min_temp_c'] <= slot_zone[s]['temperature_c'] <= p['max_temp_c']
                          and p['min_temp_c'] <= slot_zone[s]['setpoint_c'] <= p['max_temp_c']]
            if not candidates:
                alerts.append(f"{p['id']}: no compatible free slot; hold for review")
                continue
            slot = min(candidates, key=lambda s: (abs(slot_zone[s]['temperature_c'] - p['reference_temp_c']), s))
            free.remove(slot)
            assignments.append({'pallet_id': p['id'], 'slot': slot, 'zone': slot_zone[slot]['id']})
        z = slot_zone[slot]
        if not p['min_temp_c'] <= z['temperature_c'] <= p['max_temp_c']:
            alerts.append(f"{p['id']}: current zone temperature outside product range; hold for review")
            continue
        eligible.append((p, slot, life_at(p, z['temperature_c'])))
    remaining = {p['id']: p['quantity_kg'] for p, _, _ in eligible}
    picks, shortages = [], []
    for index, order in enumerate(state['orders'], 1):
        needed = order['quantity_kg']
        candidates = sorted((item for item in eligible if item[0]['sku'] == order['sku']
                             and item[2] >= order.get('min_remaining_hours', 0)), key=lambda item: (item[2], item[0]['id']))
        for p, slot, life in candidates:
            amount = min(needed, remaining[p['id']])
            if amount <= 0:
                continue
            picks.append({'priority': len(picks) + 1, 'order': index, 'pallet_id': p['id'], 'sku': p['sku'],
                          'slot': slot, 'quantity_kg': amount, 'estimated_remaining_hours': round(life, 2)})
            remaining[p['id']] -= amount
            needed -= amount
        if needed > 0:
            shortages.append({'order': index, 'sku': order['sku'], 'unfilled_kg': needed})
    adjustments = []
    # Include held inventory: cooling changes must respect every assigned product.
    locations = {p['id']: p.get('slot') for p in state['pallets']}
    locations.update({a['pallet_id']: a['slot'] for a in assignments})
    for z in zones:
        products = [p for p in state['pallets'] if locations[p['id']] in z['slots']]
        if not products:
            continue
        low = max([z['min_setpoint_c']] + [p['min_temp_c'] for p in products])
        high = min([z['max_setpoint_c']] + [p['max_temp_c'] for p in products])
        if low > high:
            alerts.append(f"{z['id']}: incompatible product temperature ranges; manual relocation required")
            continue
        target = min(max(z['setpoint_c'], low), high)
        if target != z['setpoint_c'] or abs(z['temperature_c'] - target) > 1:
            adjustments.append({'zone': z['id'], 'recommended_setpoint_c': target,
                                'action': 'adjust_setpoint' if target != z['setpoint_c'] else 'inspect_chiller_and_sensor',
                                'reason': 'Maintain shared product range; investigate measured temperature drift'})
    return {'mode': 'deterministic_planner', 'put_away': assignments, 'fefo_picks': picks,
            'chiller_adjustments': adjustments, 'shortages': shortages, 'alerts': alerts,
            'assumptions': ['Zou Eq. (1) linear temperature factor; estimates need calibration and are not food-safety clearance.',
                            'Remaining life is at reference temperature; no historical exposure is inferred.',
                            'Orders are served in input order; FEFO applies within each order.',
                            'One slot per pallet; partial picks allowed; no relocation or energy optimization.',
                            'Chiller recommendations require operator review; no equipment is controlled.']}


def extract(text, model, url):
    schema = json.loads((Path(__file__).parent / 'examples' / 'state.json').read_text())
    prompt = ('Extract warehouse state from the user text into JSON matching the example schema. '
              'Do not invent missing values. Use null for missing required fields. '
              'Only q10 and order min_remaining_hours may be omitted. Slots are globally unique. '
              'remaining_life_hours is measured at reference_temp_c. Return JSON only. Example: '
              + json.dumps(schema))
    request = urllib.request.Request(url.rstrip('/') + '/api/chat', data=json.dumps({
        'model': model, 'stream': False, 'format': 'json', 'options': {'temperature': 0},
        'messages': [{'role': 'system', 'content': prompt}, {'role': 'user', 'content': text}]
    }).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(json.load(response)['message']['content'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--state', type=Path, help='Structured JSON input; no model needed')
    source.add_argument('--text', type=Path, help='Free-text input file, parsed by local Ollama')
    parser.add_argument('--model', default='qwen2.5:7b')
    parser.add_argument('--ollama-url', default='http://localhost:11434')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        state = json.loads(args.state.read_text()) if args.state else extract(args.text.read_text(), args.model, args.ollama_url)
        result = plan(state)
        result['input_mode'] = 'structured_json' if args.state else 'llm_text_extraction'
        rendered = json.dumps(result, indent=2, allow_nan=False) + '\n'
        if args.output:
            args.output.write_text(rendered)
        else:
            print(rendered, end='')
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        print(f'Cannot produce plan: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
