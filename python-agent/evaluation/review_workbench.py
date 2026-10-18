"""Build an offline human-review page from hash-verified, frozen evaluation output."""
import argparse
import json
from pathlib import Path
from evaluation.delivery_quality import digest, read_jsonl, summarize


def bundle(directory):
    directory = Path(directory)
    manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    cases, rows = read_jsonl(directory/'cases.jsonl'), read_jsonl(directory/'trials.jsonl')
    if digest(cases) != manifest['dataset_hash'] or digest(rows) != manifest['trials_hash']:
        raise ValueError('Frozen dataset or outputs changed')
    by_id = {case['id']:case for case in cases}
    if len(by_id) != len(cases) or len({row['id'] for row in rows}) != len(rows):
        raise ValueError('Duplicate evaluation identifiers')
    items = []
    for row in rows:
        case = by_id[row['id']]
        items.append({'id':row['id'],'category':case['category'],'query':case['query'],
            'sources':case.get('sources',[]),'candidate':row.get('candidate_reply',''),'final':row.get('reply',''),
            'error':row.get('error_type'),'audit':row.get('audit'),
            'candidate_hash':digest(row.get('candidate_reply','')),'final_hash':digest(row.get('reply',''))})
    return {'mode':manifest['mode'],'expected':manifest['expected_trials'],'hash':digest(items),'items':items}


def build(directory, output):
    data = bundle(directory)
    # Embedded JSON is data; even a source containing </script> must not become HTML.
    payload = json.dumps(data, ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    template = Path(__file__).with_name('review_workbench.html').read_text(encoding='utf-8')
    path = Path(output)
    if path.exists(): raise ValueError('Use a new output file')
    path.write_text(template.replace('__EVALUATION_BUNDLE__',payload), encoding='utf-8')
    return path


def compare(directory, first, second):
    directory = Path(directory)
    manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    bundle(directory)
    rows = read_jsonl(directory/'trials.jsonl')
    a,b = read_jsonl(first),read_jsonl(second)
    for reviews in (a,b): summarize(rows,reviews,manifest['expected_trials'],manifest['mode'])
    a,b = {r['id']:r for r in a if r.get('reviewer')},{r['id']:r for r in b if r.get('reviewer')}
    if any(a[key]['reviewer'].strip()==b[key]['reviewer'].strip() for key in a.keys() & b.keys()):
        raise ValueError('Independent comparison requires different reviewers')
    fields = ['task_completed','context_coherent','candidate_correct_units','falsely_blocked_units','specific_facts','unsupported_specific_facts']
    disagreements = [{'id':key,'fields':{field:[a[key][field],b[key][field]] for field in fields if a[key][field]!=b[key][field]}}
                     for key in sorted(a.keys() & b.keys()) if any(a[key][field]!=b[key][field] for field in fields)]
    return {'overlap':len(a.keys() & b.keys()),'only_first':sorted(a.keys()-b.keys()),'only_second':sorted(b.keys()-a.keys()),
            'disagreements':disagreements,'resolution':'Human adjudication required; no automatic majority labels.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    page=sub.add_parser('build');page.add_argument('--directory',required=True);page.add_argument('--output',required=True)
    diff=sub.add_parser('compare');diff.add_argument('--directory',required=True);diff.add_argument('--first',required=True);diff.add_argument('--second',required=True);diff.add_argument('--output',required=True)
    args=parser.parse_args()
    if args.command=='build': print(build(args.directory,args.output))
    else:
        path=Path(args.output)
        if path.exists():raise ValueError('Use a new output file')
        path.write_text(json.dumps(compare(args.directory,args.first,args.second),ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
