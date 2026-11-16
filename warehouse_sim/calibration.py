"""Fit normalized zero-order Zou Eq. (1) to longitudinal quality observations.

Method source: https://doi.org/10.1016/j.jfoodeng.2025.112577
OLS fitting below is our implementation, not a parameter fit from that paper.
"""
import csv
from datetime import datetime
import hashlib
import io
import math
from pathlib import Path


def calibrate(path, reference_temperatures):
    groups = {}
    for row in csv.DictReader(io.StringIO(Path(path).read_text(encoding='utf-8-sig'))):
        try:
            sku, batch = row['sku'], row['batch']
            t = datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00'))
            if t.tzinfo is None:
                raise ValueError('Calibration timestamps must include timezone')
            temp, quality = float(row['temperature_c']), float(row['quality'])
            if not math.isfinite(temp) or not math.isfinite(quality) or not 0 <= quality <= 1:
                raise ValueError('Invalid temperature or normalized quality')
            groups.setdefault((sku, batch), []).append((t, temp, quality))
        except KeyError as exc:
            raise ValueError('Calibration requires sku,batch,timestamp,temperature_c,quality columns') from exc
    samples = {}
    for (sku, batch), values in groups.items():
        if sku not in reference_temperatures:
            raise ValueError(f'Missing reference temperature for {sku}')
        values.sort()
        for first, second in zip(values, values[1:]):
            dt = (second[0]-first[0]).total_seconds()/3600
            if dt <= 0:
                raise ValueError('Duplicate timestamps within calibration batch')
            # Zero-quality endpoints are censored and cannot identify exact loss.
            if first[2] <= 0 or second[2] <= 0:
                continue
            x = dt
            y = dt * ((first[1]+second[1])/2-reference_temperatures[sku])/10
            target = first[2]-second[2]
            samples.setdefault(sku, []).append((x, y, target))
    result = {}
    for sku, values in samples.items():
        rate, sensitivity = fit_exposures(values, sku)
        q10 = 1+sensitivity/rate
        rmse = math.sqrt(sum((q-rate*x-sensitivity*y)**2 for x,y,q in values)/len(values))
        result[sku] = dict(reference_temp_c=reference_temperatures[sku], q10=q10,
                           k0_quality_per_hour=rate, life_hours=1/rate,
                           intervals=len(values), interval_loss_rmse=rmse)
    if set(result) != set(reference_temperatures):
        raise ValueError('Not every requested SKU has identifiable longitudinal quality observations')
    return dict(method='Zou Eq. (1), normalized-quality OLS',
                target_kind='quantitative_quality_observations', validation_status='fit_only_no_independent_holdout',
                parameters=result,
                source_file=Path(path).name, source_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                limitations='Fits observations only; independent batch validation required. Quality=0 treated as censored; not food-safety clearance.')


def require_calibration(report, allow_estimated=False):
    """Distinguish an observed-quality fit from an explicitly allowed seed fit."""
    if not isinstance(report, dict) or not report.get('parameters'):
        raise ValueError('Run requires fitted kinetic parameters with source provenance')
    kind = report.get('target_kind')
    if kind == 'estimated_freshness_surrogate':
        if not allow_estimated:
            raise ValueError('Estimated freshness is not observed-quality calibration; '
                             'use measured quality observations or explicitly allow '
                             '--allow-estimated-calibration for a surrogate run')
    elif kind not in ('quantitative_quality_observations', 'verified_literature_shelf_life'):
        raise ValueError('Calibration target provenance is unspecified or unsupported; regenerate the fit report')


def apply_calibration(config, report):
    for product in config['products']:
        fit = report['parameters'][product['sku']]
        if product['reference_temp_c'] != fit['reference_temp_c']:
            raise ValueError('Calibration and scenario reference temperatures must match')
        product.update({k: fit[k] for k in ('q10', 'life_hours')})
        if 'shelf_life_curve' in fit:
            product['shelf_life_curve'] = fit['shelf_life_curve']
            product['kinetic_model'] = 'tabulated_shelf_life'
        else:
            product.pop('shelf_life_curve',None)
            product['kinetic_model'] = 'zou_linear_q10'
    if config.get('initial_pallets'):
        raise ValueError('Apply calibration before PMC conversion; existing pallet quality cannot be inferred from new rates')
    config['kinetic_provenance'] = report
    return config


def fit_exposures(values, label):
    """Fit loss = rate*hours + sensitivity*temperature_exposure by OLS."""
    xx = sum(x*x for x,y,q in values)
    yy = sum(y*y for x,y,q in values)
    xy = sum(x*y for x,y,q in values)
    xq = sum(x*q for x,y,q in values)
    yq = sum(y*q for x,y,q in values)
    det = xx*yy-xy*xy
    if len(values) < 3 or det <= 1e-10 * max(xx*yy, 1):
        raise ValueError(f'{label}: insufficient independent temperature exposures')
    rate = (xq*yy-yq*xy)/det
    sensitivity = (yq*xx-xq*xy)/det
    if rate <= 0 or sensitivity < 0:
        raise ValueError(f'{label}: observations do not support positive rate and Q10 >= 1')
    return rate, sensitivity


def calibrate_cold_chain(path, config, mapping, allow_estimated=False, allow_extrapolation=False):
    """Fit a surrogate from aggregate transport records, never invented trajectories.

    Dataset: https://www.kaggle.com/datasets/datcolabssnet/cold-chain-logistics-dataset
    Equation: https://doi.org/10.1016/j.jfoodeng.2025.112577 (Eq. 1).
    Mapping sensitivity classes to produce SKUs is synthetic and operator-specified.
    """
    if not allow_estimated:
        raise ValueError('Source has Estimated_Freshness_Percent, not measured spoilage; explicitly allow estimated targets for a surrogate fit')
    data = list(csv.DictReader(io.StringIO(Path(path).read_text(encoding='utf-8-sig'))))
    required = {'Temperature_C', 'Product_Sensitivity', 'Actual_Transit_Time_hr',
                'Initial_Freshness_Percent', 'Estimated_Freshness_Percent'}
    if not data or not required.issubset(data[0]):
        raise ValueError('Input does not have the documented cold-chain aggregate fields')
    products = {p['sku']:p for p in config['products']}
    if set(mapping) != set(products):
        raise ValueError('Sensitivity mapping must explicitly cover every scenario SKU')
    result = {}
    for sku, product in products.items():
        reference = product['reference_temp_c']
        train, validation, temperatures = [], [], []
        increases, censored = 0, 0
        category = mapping[sku]
        for row in data:
            if row['Product_Sensitivity'] != category:
                continue
            temp, duration, first, final = [float(row[k]) for k in
                ('Temperature_C', 'Actual_Transit_Time_hr', 'Initial_Freshness_Percent', 'Estimated_Freshness_Percent')]
            if not all(math.isfinite(v) for v in (temp,duration,first,final)) or duration <= 0 or not (0 <= first <= 100 and 0 <= final <= 100):
                raise ValueError('Invalid cold-chain exposure or freshness percentage')
            if first == 0 or final == 0:
                censored += 1
                continue
            temperatures.append(temp)
            loss = (first-final)/100
            increases += loss < 0
            sample = (duration, duration*(temp-reference)/10, loss)
            # Identical source rows always stay in the same split.
            digest = hashlib.sha256(repr(sorted(row.items())).encode()).hexdigest()
            (validation if int(digest[:8],16)%5 == 0 else train).append(sample)
        if not train or not validation:
            raise ValueError(f'{sku}: source category {category} lacks training/holdout rows')
        rate, sensitivity = fit_exposures(train, sku)
        low, high = min(temperatures), max(temperatures)
        extrapolated = product['min_temp_c'] < low or product['max_temp_c'] > high or not low <= reference <= high
        if extrapolated and not allow_extrapolation:
            raise ValueError(f'{sku}: product temperature domain extends outside source [{low}, {high}] C; explicitly allow extrapolation or revise the template')
        def error(samples):
            errors = [q-rate*x-sensitivity*y for x,y,q in samples]
            baseline = [q-(sum(v[2] for v in train)/len(train)) for x,y,q in samples]
            return dict(rmse_quality_fraction=math.sqrt(sum(v*v for v in errors)/len(errors)),
                        mean_absolute_error= sum(abs(v) for v in errors)/len(errors),
                        train_mean_baseline_rmse=math.sqrt(sum(v*v for v in baseline)/len(baseline)))
        holdout_error = error(validation)
        result[sku] = dict(reference_temp_c=reference, q10=1+sensitivity/rate,
                           k0_quality_per_hour=rate, life_hours=1/rate, sensitivity_class=category,
                           training_rows=len(train), holdout_rows=len(validation),
                           source_temperature_range_c=[low,high], extrapolation=extrapolated,
                           estimated_freshness_increases=increases, censored_rows=censored,
                           training_error=error(train), row_holdout_error=holdout_error,
                           beats_constant_mean_holdout=holdout_error['rmse_quality_fraction'] < holdout_error['train_mean_baseline_rmse'])
    return dict(method='Zou Eq. (1), aggregate estimated-freshness surrogate OLS',
                target_kind='estimated_freshness_surrogate', parameters=result, source_rows=len(data),
                source_file=Path(path).name, source_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                source_url='https://www.kaggle.com/datasets/datcolabssnet/cold-chain-logistics-dataset',
                synthetic_sensitivity_to_sku_mapping=mapping,
                assumptions=['Temperature_C treated as constant transit exposure for Actual_Transit_Time_hr.',
                             'Initial minus estimated final freshness is a normalized quality-loss proxy.',
                             'Loading, humidity and other covariates are omitted; fitted rate is effective, not intrinsic.',
                             'Sensitivity class to produce SKU transfer is synthetic.',
                             'Row-level holdout is not independent batch or experimental validation.'],
                limitations='Estimated-target seed calibration only. No measured biological spoilage or food-safety validation.')
