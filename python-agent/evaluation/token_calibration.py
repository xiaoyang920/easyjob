"""Summarize estimate/actual pairs from saved reports without retaining text."""
import argparse
import json
from pathlib import Path
import statistics


def pairs(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'token_calibration' and isinstance(item, list):
                yield from item
            else:
                yield from pairs(item)
    elif isinstance(value, list):
        for item in value:
            yield from pairs(item)


def summarize(rows):
    groups, seen = {}, set()
    for index, row in enumerate(rows):
        key = row.get('call_id') or f'uncorrelated-{index}'
        if key in seen:
            continue
        seen.add(key)
        group = (row.get('model', 'unknown'), row.get('estimator', 'unknown'),
                 bool(row.get('image_count')), bool(row.get('schema_count')))
        groups.setdefault(group, []).append(row)
    output = []
    for (model, estimator, images, schemas), items in groups.items():
        ratios = [row['actual_input_tokens'] / row['estimated_input_tokens'] for row in items
                  if row.get('status') == 'measured' and type(row.get('actual_input_tokens')) is int
                  and type(row.get('estimated_input_tokens')) is int and row['estimated_input_tokens'] > 0]
        output.append({'model': model, 'estimator': estimator, 'images': images, 'schemas': schemas,
            'samples': len(items), 'measured_samples': len(ratios), 'missing_or_failed': len(items)-len(ratios),
            'actual_over_estimate_median': statistics.median(ratios) if ratios else None,
            'actual_over_estimate_max': max(ratios) if ratios else None})
    return {'mode': 'observational_only', 'automatic_budget_adjustment': False, 'groups': output}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--reports', type=Path, nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows = [row for report in args.reports for row in pairs(json.loads(report.read_text(encoding='utf-8')))]
    result = summarize(rows)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
