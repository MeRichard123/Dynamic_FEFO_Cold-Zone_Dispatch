"""Inspect local CSV/ZIP source schemas without using images or inventing labels."""
import csv
import io
from pathlib import Path
import zipfile


def describe_csv(name, text):
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    preview = []
    rows = 0
    for row in reader:
        rows += 1
        if len(preview) < 2:
            preview.append(row)
    return dict(file=name, columns=reader.fieldnames, rows=rows, preview=preview,
                calibration_requirement='Longitudinal batch IDs, timestamps, temperatures, and quantitative quality or time-to-expiry are needed; binary class labels alone cannot identify decay rates.')


def inspect(path):
    path = Path(path)
    if path.suffix.lower()=='.zip':
        with zipfile.ZipFile(path) as archive:
            csvs = [i for i in archive.infolist() if i.filename.lower().endswith('.csv')]
            # Avoid accidentally loading large image archives into memory.
            results = [describe_csv(i.filename, archive.read(i).decode('utf-8-sig')) for i in csvs if i.file_size <= 100_000_000]
            images = sum(n.lower().endswith(('.jpg','.jpeg','.png','.webp')) for n in archive.namelist())
            return {'csv_files':results, 'image_files_not_used':images,
                    'oversize_csvs_not_read':[i.filename for i in csvs if i.file_size > 100_000_000]}
    return {'csv_files':[describe_csv(path.name, path.read_text(encoding='utf-8-sig'))], 'image_files_not_used':0}
