"""Strict local-LLM scenario schema; generated text cannot execute code."""
import math

KINDS = ('sensor_bias', 'cooling_failure', 'door_stuck')
BOUNDS = {'sensor_bias': (-5, 5), 'cooling_failure': (0, 1), 'door_stuck': (1, 1)}


def validate_events(events, zones, horizon):
    if not isinstance(events, list) or len(events) > 8:
        raise ValueError('Disruptions must be a list of at most eight events')
    occupied = {}
    for event in events:
        if not isinstance(event, dict) or set(event) != {'kind', 'zone', 'at_minute', 'duration_minutes', 'value'}:
            raise ValueError('Each disruption must match the documented schema exactly')
        kind, zone = event['kind'], event['zone']
        if kind not in KINDS or zone not in zones:
            raise ValueError('Unknown disruption kind or zone')
        for field in ('at_minute', 'duration_minutes', 'value'):
            value = event[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError('Disruption numbers must be finite')
        a, b = event['at_minute'], event['at_minute'] + event['duration_minutes']
        if a < 0 or event['duration_minutes'] <= 0 or b > horizon:
            raise ValueError('Disruption must lie within simulation horizon')
        lo, hi = BOUNDS[kind]
        if not lo <= event['value'] <= hi:
            raise ValueError('Disruption magnitude outside allowed bounds')
        for start, end in occupied.get((kind, zone), []):
            if max(a, start) < min(b, end):
                raise ValueError('Same-kind disruptions may not overlap within a zone')
        occupied.setdefault((kind, zone), []).append((a, b))
    return events


def schema(zones):
    return {'type': 'object', 'additionalProperties': False, 'required': ['description', 'disruptions'],
            'properties': {'description': {'type': 'string'}, 'disruptions': {'type': 'array', 'maxItems': 8,
            'items': {'type': 'object', 'additionalProperties': False,
                     'required': ['kind', 'zone', 'at_minute', 'duration_minutes', 'value'],
                     'properties': {'kind': {'type': 'string', 'enum': list(KINDS)},
                                    'zone': {'type': 'string', 'enum': list(zones)},
                                    'at_minute': {'type': 'number', 'minimum': 0},
                                    'duration_minutes': {'type': 'number', 'exclusiveMinimum': 0},
                                    'value': {'type': 'number'}}}}}}
