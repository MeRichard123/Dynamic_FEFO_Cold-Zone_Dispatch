"""Time-varying GB electricity intensity, with explicit source provenance.

API and units: https://carbon-intensity.github.io/api-definitions/
"""
from datetime import datetime, timezone
import json
import math
import urllib.request


def utc(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Grid timestamps must include a UTC offset')
    return result.astimezone(timezone.utc)


def from_api(payload, start, duration_minutes, prefer='actual'):
    """Convert half-hour GB API intervals; reject gaps and missing intensities."""
    origin = utc(start)
    intervals = []
    for row in payload['data']:
        begin = (utc(row['from'])-origin).total_seconds()/60
        end = (utc(row['to'])-origin).total_seconds()/60
        if end <= 0 or begin >= duration_minutes:
            continue
        value = row['intensity'].get(prefer)
        used = prefer
        if value is None and prefer == 'actual':
            value = row['intensity'].get('forecast')
            used = 'forecast'
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError('Missing/invalid grid intensity')
        intervals.append({'from_minute': max(0, begin), 'to_minute': min(end, duration_minutes),
                          'kg_co2_per_kwh': value/1000, 'value_type': used})
    validate_intervals(intervals, duration_minutes)
    return {'intervals': intervals, 'source': 'https://api.carbonintensity.org.uk',
            'start_utc': origin.isoformat(), 'units': 'kg_CO2_per_kWh', 'geography': 'Great Britain'}


def validate_intervals(intervals, duration):
    cursor = 0
    for row in intervals:
        a, b, v = row['from_minute'], row['to_minute'], row['kg_co2_per_kwh']
        if not all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) for n in (a, b, v)):
            raise ValueError('Grid intervals must be finite')
        if abs(a-cursor) > 1e-8 or b <= a or v < 0:
            raise ValueError('Grid intervals must be contiguous, ordered and nonnegative')
        cursor = b
    if cursor < duration:
        raise ValueError('Grid intervals do not cover the simulation horizon')


def fetch(date, start, duration):
    url = 'https://api.carbonintensity.org.uk/intensity/date/' + date
    with urllib.request.urlopen(url, timeout=30) as response:
        payload = json.load(response)
    result = from_api(payload, start, duration)
    result['request_url'] = url
    result['raw_response'] = payload
    return result
