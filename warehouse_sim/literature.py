"""Import source-backed kinetic priors from the user-supplied supplement.

Source: Zou et al. (2025), https://doi.org/10.1016/j.jfoodeng.2025.112577
Tables S5/S8: observed constant-temperature shelf-life endpoints.
Table S17: normative orange shelf life, Q10 and storage ranges.
Interpolation and normalization below are explicit implementation choices.
"""
import copy
import hashlib
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from .physics import tabulated_rate

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
M = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
NS = {'w':W}


def doc_text(element, omit_references=False):
    parts = []
    def walk(node):
        if omit_references and node.tag == '{'+W+'}r':
            position = node.find('w:rPr/w:vertAlign',NS)
            value = ''.join(t.text or '' for t in node.findall('w:t',NS))
            if position is not None and position.get('{'+W+'}val') == 'superscript' and value.strip().isdigit():
                return
        if node.tag in ('{'+W+'}t','{'+M+'}t'):
            parts.append(node.text or '')
        for child in node:
            walk(child)
    walk(element)
    return ''.join(parts)


def tables(path):
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read('word/document.xml'))
    if 'Digital twin integration for dynamic quality loss control in fruit supply chains' not in doc_text(root):
        raise ValueError('Document title does not match the referenced supplement')
    result, caption = {}, None
    for element in root.find('w:body',NS):
        if element.tag == '{'+W+'}p':
            match = re.match(r'Table\s+(S\d+)(?:\.|\s)',doc_text(element).strip())
            if match:
                caption = match[1]
        elif element.tag == '{'+W+'}tbl' and caption:
            result[caption] = [[doc_text(cell,True).strip() for cell in row.findall('w:tc',NS)]
                               for row in element.findall('w:tr',NS)]
            caption = None
    if not {'S5','S8','S17'}.issubset(result):
        raise ValueError('Supplement must contain Tables S5, S8 and S17')
    return result


def build_profile(path, base):
    data = tables(path)
    strawberry = []
    for row in data['S5'][1:]:
        if len(row) >= 4:
            strawberry.append(dict(temperature_c=float(row[0]), shelf_life_hours=float(row[2])*24))
    apples, indicator = [], None
    for row in data['S8'][1:]:
        if row[0]:
            indicator = row[0]
        if indicator == 'b* value':
            apples.append(dict(temperature_c=float(row[1]), shelf_life_hours=float(row[3])*24))
    table17 = {row[0]:row[1:] for row in data['S17'][1:]}
    header = data['S17'][0][1:]
    orange_index = header.index('Orange')
    days = float(table17['Recommended shelf life (days)'][orange_index])
    q10_cells = table17['Q10']
    q10_entries = [[dict(q10=float(number), temperature_annotation=domain)
                    for number,domain in re.findall(r'(\d+(?:\.\d+)?)\s*\(([^)]+)\)',cell)]
                   for cell in q10_cells[:4]]
    if len(strawberry) != 5 or len(apples) != 4 or not all(q10_entries):
        raise ValueError('Unexpected supplemental data layout; manual review required')
    for curve in (strawberry,apples):
        tabulated_rate(curve,curve[0]['temperature_c'])
    if days <= 0:
        raise ValueError('Invalid recommended orange shelf life')
    sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    audit = []
    recommended = table17['Recommended shelf life (days)']
    printed_rates = table17['Rate constant value k0 (%/min)']
    for i,fruit in enumerate(header[:4]):
        rate = float(printed_rates[i])
        life = float(recommended[i])
        audit.append(dict(fruit=fruit, printed_k0=rate, printed_units='%/min', recommended_days=life,
                          fraction_budget_consumed=rate*life*1440,
                          percent_budget_consumed=rate*life*1440/100))
    prototype = copy.deepcopy(base['products'][0])
    def product(sku,zone,reference,low,high,life,q10,curve=None):
        p = dict(prototype,sku=sku,zone=zone,reference_temp_c=reference,min_temp_c=low,
                 max_temp_c=high,life_hours=life,q10=q10,pallets=2)
        p['kinetic_model'] = 'tabulated_shelf_life' if curve else 'zou_linear_q10'
        if curve:
            p['shelf_life_curve'] = curve
        else:
            p.pop('shelf_life_curve',None)
        return p
    products = [
        product('apples','chilled',4,0,4,1/tabulated_rate(apples,4),q10_entries[3][0]['q10'],apples),
        product('oranges','cool',4,0,4,days*24,q10_entries[2][0]['q10']),
        product('strawberries','temperate',4,4,10,1/tabulated_rate(strawberry,4),q10_entries[0][0]['q10'],strawberry)]
    config = copy.deepcopy(base)
    if [z['id'] for z in config['zones']] != ['chilled','cool','temperate']:
        raise ValueError('Paper-profile template needs chilled/cool/temperate zone IDs in that order')
    for zone,temp in zip(config['zones'],(0,2,4)):
        zone.update(temperature_c=temp,setpoint_c=temp,min_setpoint_c=temp,max_setpoint_c=temp+1,
                    setpoint_options_c=[temp,temp+1])
    config['products'] = products
    config.pop('initial_pallets',None)
    config.pop('incoming_pallets',None)
    config['waves'] = [dict(at_minute=i*30,sku=p['sku'],quantity_kg=p['pallet_kg']) for i,p in enumerate(products)]
    parameters = {p['sku']:{k:copy.deepcopy(p[k]) for k in ('life_hours','reference_temp_c','q10','kinetic_model','shelf_life_curve') if k in p} for p in products}
    report = dict(target_kind='verified_literature_shelf_life',parameters=parameters,
                  method='Zero-order additive quality budget with published endpoint rates or explicitly normative Q10 prior',
                  source_file=Path(path).name,source_sha256=sha,
                  source_url='https://doi.org/10.1016/j.jfoodeng.2025.112577',
                  source_tables={'strawberries':'S5 observed shelf life', 'apples':'S8 observed b* shelf life',
                                 'oranges':'S17 recommended shelf life and Q10; Annex II citrus paragraph anchors 4 C'},
                  q10_cells_without_superscript_citations=dict(zip(header[:4],q10_entries)),
                  unused_printed_rate_audit=audit,
                  initial_quality_budget=1.0,rejection_budget=0.0,
                  normalization='Constant-temperature quality rate = 1 / published shelf-life hours. Interpolate reciprocal life, not life. Divide by reference rate to consume reference-life hours.',
                  model_extensions=['Piecewise-linear zero-order rate interpolation of S5/S8 endpoints extends scalar Eq. (1). No curve extrapolation.',
                                    'Orange uses normative 56-day/Q10=2 prior, not an independently measured batch calibration.',
                                    'Published strawberry/apple Q10 values are retained as provenance; tabulated curves take precedence.',
                                    'Strawberry zone 4-5 C is an experimental handling scenario, warmer than the S17 optimal 0-3 C range.',
                                    'Three zone temperatures and controller constants are scenario choices, not inferred thermal calibration.'],
                  limitations='Literature-conditioned quality expiry, not microbiological safety clearance or independent validation on these warehouse batches. S17 printed rates were not imported because units/normalization and strawberry/lychee lifetimes are inconsistent.')
    config['kinetic_provenance'] = report
    return config,report
