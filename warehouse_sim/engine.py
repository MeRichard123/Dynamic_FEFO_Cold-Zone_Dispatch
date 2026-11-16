import copy
import math
import random

import simpy

from .carbon import validate_intervals
from .disruptions import validate_events
from .layout import zone_slots
from .physics import pallet_factor, pallet_life_consumed, thermal_step


def positive(value, label, zero=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0 or (not zero and value == 0):
        raise ValueError(f'{label} must be finite and {"nonnegative" if zero else "positive"}')


class Simulation:
    def __init__(self, locations, config):
        self.config = copy.deepcopy(config)
        c = self.config
        for key in ('duration_minutes', 'tick_minutes', 'picker_speed_m_s', 'pick_minutes', 'coordinate_scale_m'):
            positive(c[key], key)
        for key in ('grid_kg_co2_per_kwh',):
            positive(c[key], key, zero=True)
        positive(c['pickers'], 'pickers')
        if int(c['pickers']) != c['pickers']:
            raise ValueError('pickers must be an integer')
        if len(c['dispatch_xy']) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in c['dispatch_xy']):
            raise ValueError('dispatch_xy must contain two finite coordinates')
        self.locations = locations
        self.slots = zone_slots(locations, c['zones'])
        self.zones = {z['id']: copy.deepcopy(z) for z in c['zones']}
        for z in self.zones.values():
            for key in ('ua_closed_kw_k', 'ua_door_kw_k', 'thermal_capacity_kwh_k', 'max_cooling_kw', 'cop'):
                positive(z[key], key)
            for key in ('temperature_c', 'setpoint_c'):
                if not isinstance(z[key], (int, float)) or not math.isfinite(z[key]):
                    raise ValueError(f'{key} must be finite')
            z.update(doors=0, stuck_door=False, sensor_bias_c=0.0, cooling_multiplier=1.0, kwh=0.0, carbon_kg=0.0)
        if not isinstance(c['ambient_c'], (int, float)) or not math.isfinite(c['ambient_c']):
            raise ValueError('ambient_c must be finite')
        if not c['products']:
            raise ValueError('At least one product is required')
        skus = set()
        for product in c['products']:
            if product['sku'] in skus or product['zone'] not in self.zones:
                raise ValueError('Product SKUs must be unique and zone must exist')
            skus.add(product['sku'])
            for key in ('pallet_kg', 'life_hours', 'q10'):
                positive(product[key], key)
            if product['q10'] < 1 or not product['min_temp_c'] <= product['reference_temp_c'] <= product['max_temp_c']:
                raise ValueError('Invalid product Q10 or temperature range')
            for key in ('min_temp_c', 'max_temp_c', 'reference_temp_c'):
                if not math.isfinite(product[key]):
                    raise ValueError('Product temperatures must be finite')
            positive(product['pallets'], 'pallets')
            if int(product['pallets']) != product['pallets']:
                raise ValueError('pallets must be an integer')
        for wave in c['waves']:
            positive(wave['at_minute'], 'wave time', zero=True)
            positive(wave['quantity_kg'], 'wave quantity')
            positive(wave.get('min_remaining_hours', 0), 'minimum life', zero=True)
            if wave['sku'] not in skus or wave['at_minute'] >= c['duration_minutes']:
                raise ValueError('Wave SKU must exist and arrival must precede horizon')
        self.env = simpy.Environment()
        self.pickers = simpy.Resource(self.env, capacity=int(c['pickers']))
        self.last_update = 0
        self.events, self.trace, self.pallets = [], [], []
        self.requests = []
        rng = random.Random(c['seed'])
        allocated = {z: 0 for z in self.zones}
        if 'initial_pallets' not in c:
            for product in c['products']:
                zid = product['zone']
                for i in range(product['pallets']):
                    index = allocated[zid]
                    if index >= len(self.slots[zid]):
                        raise ValueError('Synthetic inventory exceeds zone capacity')
                    self.pallets.append(dict(product, id=f"{product['sku']}-{i+1:03d}", slot=self.slots[zid][index],
                                             remaining_life_hours=product['life_hours'] * rng.uniform(0.5, 1),
                                             quantity_kg=product['pallet_kg'], reserved=False))
                    allocated[zid] += 1
        if 'initial_pallets' in c:
            self.pallets = copy.deepcopy(c['initial_pallets'])
            product_map = {p['sku']: p for p in c['products']}
            used_slots, used_ids = set(), set()
            for pallet in self.pallets:
                if pallet['sku'] not in product_map:
                    raise ValueError('Unknown initial pallet SKU')
                prototype = product_map[pallet['sku']]
                for key in ('zone', 'q10', 'reference_temp_c', 'min_temp_c', 'max_temp_c'):
                    pallet.setdefault(key, prototype[key])
                for key in ('shelf_life_curve','kinetic_model'):
                    if key in prototype:
                        pallet.setdefault(key, copy.deepcopy(prototype[key]))
                if pallet['slot'] not in self.slots.get(pallet['zone'], []) or pallet['slot'] in used_slots or pallet['id'] in used_ids:
                    raise ValueError('Invalid/duplicate initial pallet slot or ID')
                if not isinstance(pallet['id'], str) or not pallet['id']:
                    raise ValueError('Pallet ID must be a nonempty string')
                for key in ('q10', 'reference_temp_c', 'min_temp_c', 'max_temp_c'):
                    if isinstance(pallet[key], bool) or not isinstance(pallet[key], (float, int)) or not math.isfinite(pallet[key]):
                        raise ValueError('Initial pallet kinetic parameters must be finite')
                if pallet['q10'] < 1 or pallet['min_temp_c'] > pallet['max_temp_c']:
                    raise ValueError('Invalid initial pallet kinetic parameters')
                used_slots.add(pallet['slot'])
                used_ids.add(pallet['id'])
                positive(pallet['quantity_kg'], 'initial quantity', zero=True)
                positive(pallet['remaining_life_hours'], 'initial life', zero=True)
                pallet['reserved'] = False
        self.put_away = []
        if c.get('incoming_pallets'):
            from dispatch import plan as plan_putaway
            prototype_map = {p['sku']: p for p in c['products']}
            incoming = []
            for raw in c['incoming_pallets']:
                prototype = prototype_map[raw['sku']]
                incoming.append(dict(prototype))
                incoming[-1].update(raw)
                incoming[-1]['slot'] = None
            dispatch_state = {
                'zones': [dict(id=zid, temperature_c=z['temperature_c'], setpoint_c=z['setpoint_c'],
                               min_setpoint_c=z.get('min_setpoint_c', z['setpoint_c']),
                               max_setpoint_c=z.get('max_setpoint_c', z['setpoint_c']), slots=self.slots[zid])
                          for zid,z in self.zones.items()],
                'pallets': self.pallets+incoming, 'orders': []}
            result = plan_putaway(dispatch_state)
            if len(result['put_away']) != len(incoming):
                raise ValueError('Incoming inventory cannot all be put away; resolve holds before simulation')
            self.put_away = result['put_away']
            assignment = {p['pallet_id']:p for p in self.put_away}
            for pallet in incoming:
                pallet.update(slot=assignment[pallet['id']]['slot'], zone=assignment[pallet['id']]['zone'], reserved=False)
                self.pallets.append(pallet)
        self.initial_pallets = copy.deepcopy(self.pallets)
        self.policy = c.get('policy', 'fefo')
        if self.policy not in ('fefo', 'fifo', 'planned'):
            raise ValueError('Unknown dispatch policy')
        order = c.get('pallet_priority', [])
        if len(order) != len(set(order)) or not set(order).issubset({p['id'] for p in self.pallets}):
            raise ValueError('Invalid pallet priority')
        self.priority = {pid: i for i, pid in enumerate(order)}
        validate_events(c.get('disruptions', []), self.zones, c['duration_minutes'])
        self.grid = c.get('grid_intensity', {}).get('intervals', [])
        if 'grid_intensity' in c:
            validate_intervals(self.grid, c['duration_minutes'])
        self.dispatched_life_kg_hours = 0.0
        self.initial_kg = sum(p['quantity_kg'] for p in self.pallets)
        self.picked_kg = self.waste_kg = 0.0
        self.record()

    def effective_life(self, pallet):
        return pallet['remaining_life_hours'] / pallet_factor(pallet, self.zones[pallet['zone']]['temperature_c'])

    def log(self, event, **details):
        self.events.append(dict(minute=round(self.env.now, 6), event=event, **details))

    def advance(self):
        dt = self.env.now - self.last_update
        if dt <= 0:
            return
        for zid, z in self.zones.items():
            start = z['temperature_c']
            end, energy = thermal_step(start, z['setpoint_c'] - z['sensor_bias_c'], self.config['ambient_c'],
                                      z['ua_closed_kw_k'] + (z['ua_door_kw_k'] if z['doors'] or z['stuck_door'] else 0),
                                      z['thermal_capacity_kwh_k'], z['max_cooling_kw'] * z['cooling_multiplier'], z['cop'], dt)
            z['temperature_c'] = end
            z['kwh'] += energy
            factor = self.config['grid_kg_co2_per_kwh']
            for row in self.grid:
                if row['from_minute'] <= self.last_update < row['to_minute']:
                    factor = row['kg_co2_per_kwh']
                    break
            z['carbon_kg'] += energy * factor
            for p in self.pallets:
                if p['zone'] != zid or p['quantity_kg'] <= 0:
                    continue
                p['remaining_life_hours'] = max(0, p['remaining_life_hours'] - pallet_life_consumed(p, start, end, dt))
                if p['remaining_life_hours'] <= 0:
                    amount = p['quantity_kg']
                    self.waste_kg += amount
                    p['quantity_kg'] = 0
                    self.log('expired', pallet_id=p['id'], quantity_kg=amount)
        self.last_update = self.env.now

    def record(self):
        self.trace.extend(dict(minute=round(self.env.now, 6), zone=zid, temperature_c=z['temperature_c'],
                               measured_temperature_c=z['temperature_c'] + z['sensor_bias_c'],
                               door_open=bool(z['doors'] or z['stuck_door']), compressor_kwh=z['kwh'], grid_carbon_kg=z['carbon_kg']) for zid, z in self.zones.items())

    def clock(self):
        while True:
            yield self.env.timeout(self.config['tick_minutes'])
            self.advance()
            self.record()

    def wave(self, index, wave):
        yield self.env.timeout(wave['at_minute'])
        request = dict(id=index, sku=wave['sku'], requested_kg=wave['quantity_kg'], picked_kg=0.0, status='queued')
        self.requests.append(request)
        self.log('wave_arrived', wave=index, sku=wave['sku'], quantity_kg=wave['quantity_kg'])
        with self.pickers.request() as resource:
            yield resource
            request['status'] = 'active'
            # Each wave starts at dispatch and returns after every pallet visit.
            while request['picked_kg'] < request['requested_kg']:
                self.advance()
                candidates = [p for p in self.pallets if p['sku'] == wave['sku'] and p['quantity_kg'] > 0
                              and not p['reserved'] and self.effective_life(p) >= wave.get('min_remaining_hours', 0)
                              and p['min_temp_c'] <= self.zones[p['zone']]['temperature_c'] <= p['max_temp_c']]
                if not candidates:
                    request['status'] = 'shortage'
                    self.log('shortage', wave=index, unfilled_kg=request['requested_kg'] - request['picked_kg'])
                    return
                if self.policy == 'fefo':
                    key = lambda p: (self.effective_life(p), p['id'])
                elif self.policy == 'fifo':
                    key = lambda p: (p.get('arrival_minute', 0), p['id'])
                else:
                    key = lambda p: (self.priority.get(p['id'], len(self.priority)), self.effective_life(p), p['id'])
                p = min(candidates, key=key)
                p['reserved'] = True
                loc = self.locations[p['slot']]
                origin = self.config['dispatch_xy']
                travel = (abs(loc.x-origin[0]) + abs(loc.y-origin[1])) * self.config['coordinate_scale_m'] / self.config['picker_speed_m_s'] / 60
                self.log('pick_started', wave=index, pallet_id=p['id'], slot=p['slot'], travel_one_way_minutes=travel)
                yield self.env.timeout(travel)
                self.advance()
                z = self.zones[p['zone']]
                z['doors'] += 1
                self.log('door_opened', zone=p['zone'])
                yield self.env.timeout(self.config['pick_minutes'])
                self.advance()
                z['doors'] -= 1
                self.log('door_closed', zone=p['zone'])
                # Stock remains thermally associated with its zone until return to dispatch.
                yield self.env.timeout(travel)
                self.advance()
                safe = (p['remaining_life_hours'] > 0 and self.effective_life(p) >= wave.get('min_remaining_hours', 0)
                        and p['min_temp_c'] <= z['temperature_c'] <= p['max_temp_c'])
                amount = min(p['quantity_kg'], request['requested_kg']-request['picked_kg']) if safe else 0
                p['quantity_kg'] -= amount
                request['picked_kg'] += amount
                self.picked_kg += amount
                self.dispatched_life_kg_hours += amount * self.effective_life(p)
                p['reserved'] = False
                self.log('pick_completed' if amount else 'pick_rejected', wave=index, pallet_id=p['id'], quantity_kg=amount)
                if not amount:
                    request['status'] = 'shortage'
                    return
            request['status'] = 'completed'

    def disturbances(self):
        # Close old events before opening adjacent ones. Separate SimPy
        # processes can otherwise restore an old value over a new event.
        changes = []
        for index, event in enumerate(self.config.get('disruptions', [])):
            changes.append((event['at_minute'], 1, index, event))
            changes.append((event['at_minute'] + event['duration_minutes'], 0, index, event))
        fields = {'sensor_bias': ('sensor_bias_c', 0.0),
                  'cooling_failure': ('cooling_multiplier', 1.0),
                  'door_stuck': ('stuck_door', False)}
        for minute, starting, _, event in sorted(changes):
            yield self.env.timeout(minute - self.env.now)
            self.advance()
            field, normal = fields[event['kind']]
            self.zones[event['zone']][field] = event['value'] if starting else normal
            if starting:
                self.log('disruption_started', **event)
            else:
                self.log('disruption_ended', kind=event['kind'], zone=event['zone'])

    def grid_boundaries(self):
        for row in self.grid[:-1]:
            yield self.env.timeout(row['to_minute'] - self.env.now)
            self.advance()

    def run(self):
        self.env.process(self.clock())
        if self.grid:
            self.env.process(self.grid_boundaries())
        self.env.process(self.disturbances())
        for index, wave in enumerate(self.config['waves'], 1):
            self.env.process(self.wave(index, wave))
        # Process events at the horizon as well as those strictly before it.
        horizon = self.config['duration_minutes']
        while self.env.peek() <= horizon:
            self.env.step()
        if self.env.now < horizon:
            self.env.run(until=horizon)
        self.advance()
        self.record()
        remaining = sum(p['quantity_kg'] for p in self.pallets)
        kwh = sum(z['kwh'] for z in self.zones.values())
        return dict(duration_minutes=horizon, layout_locations=len(self.locations), initial_kg=self.initial_kg,
                    dispatched_kg=self.picked_kg, expired_kg=self.waste_kg, remaining_kg=remaining,
                    mass_balance_error_kg=self.initial_kg-self.picked_kg-self.waste_kg-remaining,
                    compressor_kwh=kwh, grid_kg_co2=sum(z['carbon_kg'] for z in self.zones.values()),
                    dispatched_life_kg_hours=self.dispatched_life_kg_hours,
                    remaining_life_kg_hours=sum(p['quantity_kg']*p['remaining_life_hours'] for p in self.pallets),
                    unfilled_kg=sum(r['requested_kg']-r['picked_kg'] for r in self.requests),
                    requests=self.requests, zones=self.zones, pallets=self.pallets, put_away=self.put_away)
