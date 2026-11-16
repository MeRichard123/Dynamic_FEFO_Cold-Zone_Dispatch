"""Lumped thermal model in kW, kWh/K, Celsius and minutes."""
import math


def thermal_step(temperature, setpoint, ambient, ua_kw_k, capacity_kwh_k,
                 max_cooling_kw, cop, minutes):
    """Exact constant-input RC step with capped ideal setpoint control.

    Returns final temperature and compressor electricity in kWh. Cooling can
    reach but cannot overshoot the setpoint during this integration interval.
    """
    if minutes <= 0:
        return temperature, 0.0
    hours = minutes / 60
    exponent = ua_kw_k * hours / capacity_kwh_k
    decay = math.exp(-exponent)
    one_minus_decay = -math.expm1(-exponent)
    free_end = temperature * decay + ambient * one_minus_decay
    required = max(0, (free_end - setpoint) * ua_kw_k / one_minus_decay)
    cooling = min(max_cooling_kw, required)
    final = free_end - cooling / ua_kw_k * one_minus_decay
    return final, cooling * hours / cop


# Zou et al. (2025), Eq. (1): linear temperature factor, not exponential Q10.
# https://doi.org/10.1016/j.jfoodeng.2025.112577
# Derivation and deviations are recorded in docs/simulation-methods.md.
def decay_factor(temperature, reference_c, q10):
    factor = 1 + (q10 - 1) * (temperature - reference_c) / 10
    if factor <= 0 or not math.isfinite(factor):
        raise ValueError('Temperature outside positive-rate domain of Zou Eq. (1)')
    return factor


def life_consumed(start_c, end_c, reference_c, q10, minutes):
    """Zou Eq. (1) normalized by k0 to reference-temperature life hours.

    Endpoint-average temperature approximates the interval temperature.
    Initial quality budget and reference rate are encoded by input life_hours;
    no published product calibration or trained temperature predictor is used.
    """
    return minutes / 120 * (decay_factor(start_c, reference_c, q10)
                            + decay_factor(end_c, reference_c, q10))


def tabulated_rate(curve, temperature):
    """Interpolate reciprocal shelf life (quality/hour), never extrapolate.

    A segment is a linear temperature-dependent zero-order rate, extending
    Zou Eq. (1) with observed shelf-life endpoints in supplement Tables S5/S8.
    https://doi.org/10.1016/j.jfoodeng.2025.112577
    """
    if not isinstance(curve, list) or len(curve) < 2:
        raise ValueError('Shelf-life curve needs at least two temperature points')
    previous = None
    for point in curve:
        t, h = point['temperature_c'], point['shelf_life_hours']
        if not all(isinstance(v, (int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in (t,h)) or h <= 0:
            raise ValueError('Invalid shelf-life curve point')
        if previous is not None and (t <= previous[0] or h > previous[1]):
            raise ValueError('Curve temperatures must increase and shelf life must not increase')
        previous = (t,h)
    minimum, maximum = curve[0]['temperature_c'], curve[-1]['temperature_c']
    if not minimum-1e-9 <= temperature <= maximum+1e-9:
        raise ValueError('Temperature outside literature shelf-life curve; extrapolation is not permitted')
    temperature = min(max(temperature,minimum),maximum)  # integration roundoff only
    for low, high in zip(curve,curve[1:]):
        if low['temperature_c'] <= temperature <= high['temperature_c']:
            weight = (temperature-low['temperature_c'])/(high['temperature_c']-low['temperature_c'])
            return (1-weight)/low['shelf_life_hours'] + weight/high['shelf_life_hours']
    raise ValueError('Invalid shelf-life interpolation interval')


def pallet_factor(pallet, temperature):
    model = pallet.get('kinetic_model', 'tabulated_shelf_life' if 'shelf_life_curve' in pallet else 'zou_linear_q10')
    if model not in ('tabulated_shelf_life', 'zou_linear_q10'):
        raise ValueError('Unknown kinetic model')
    if model == 'tabulated_shelf_life':
        if 'shelf_life_curve' not in pallet:
            raise ValueError('Tabulated kinetic model requires a shelf-life curve')
        return tabulated_rate(pallet['shelf_life_curve'], temperature)/tabulated_rate(pallet['shelf_life_curve'], pallet['reference_temp_c'])
    if 'shelf_life_curve' in pallet:
        raise ValueError('Scalar kinetic model conflicts with a tabulated shelf-life curve')
    return decay_factor(temperature, pallet['reference_temp_c'], pallet.get('q10',2))


def pallet_life_consumed(pallet, start_c, end_c, minutes):
    return minutes/120 * (pallet_factor(pallet,start_c)+pallet_factor(pallet,end_c))
