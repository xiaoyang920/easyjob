"""Install project-owned IK words/synonyms, preserving other IK configuration entries."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT/'src/main/resources/elasticsearch'


def prepare(home):
    home = Path(home).resolve()
    if not (home/'bin/elasticsearch.bat').exists() and not (home/'bin/elasticsearch').exists():
        raise ValueError('Expected Elasticsearch installation directory')
    configs = [home/'config/analysis-ik/IKAnalyzer.cfg.xml']
    if not configs[0].exists():
        configs = list((home/'plugins').glob('*/config/IKAnalyzer.cfg.xml'))
    if len(configs) != 1 or not configs[0].exists():
        raise ValueError('Expected exactly one installed IK configuration')
    config = configs[0]
    original = config.read_bytes()
    tree = ET.fromstring(original)
    entry = next((e for e in tree.findall('entry') if e.get('key') == 'ext_dict'), None)
    if entry is None:
        entry = ET.SubElement(tree, 'entry', key='ext_dict')
    dictionaries = [name.strip() for name in (entry.text or '').split(';') if name.strip()]
    relative = 'custom/easyjob-technical.dic'
    already_configured = relative in dictionaries
    if not already_configured:
        dictionaries.append(relative)
    entry.text = ';'.join(dictionaries)
    # IK uses java.util.Properties.loadFromXML, which requires this exact DOCTYPE.
    xml = (b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<!DOCTYPE properties SYSTEM "http://java.sun.com/dtd/properties.dtd">\n'
        + ET.tostring(tree, encoding='utf-8'))
    if already_configured and b'<!DOCTYPE properties SYSTEM "http://java.sun.com/dtd/properties.dtd">' in original:
        xml = original
    changes = {config: xml, config.parent/relative: (ASSETS/'easyjob-technical.dic').read_bytes(),
        home/'config/analysis/easyjob-synonyms.txt': (ASSETS/'easyjob-synonyms.txt').read_bytes()}
    if any(not path.resolve().is_relative_to(home) for path in changes):
        raise ValueError('Analysis paths must remain inside the selected ES installation')
    return home, changes


def install(home, check=False):
    home, planned = prepare(home)
    changed = {path: content for path, content in planned.items() if not path.exists() or path.read_bytes() != content}
    backup = ROOT/'logs/chinese-search-install'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    if changed and not check:
        backup.mkdir(parents=True)
        for number, (path, content) in enumerate(changed.items()):
            if path.exists():
                (backup/f'{number}-{path.name}').write_bytes(path.read_bytes())
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    restart = any(path.name != 'easyjob-synonyms.txt' for path in changed)
    return {'changed_files': [str(path.relative_to(home)) for path in changed], 'check_only': check,
        'es_restart_required': restart, 'search_analyzer_reload_required': bool(changed) and not restart,
        'backup': str(backup) if changed and not check else None,
        'dictionary_sha256': hashlib.sha256((ASSETS/'easyjob-technical.dic').read_bytes()).hexdigest(),
        'synonyms_sha256': hashlib.sha256((ASSETS/'easyjob-synonyms.txt').read_bytes()).hexdigest()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--es-home', required=True)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    print(json.dumps(install(args.es_home, args.check), ensure_ascii=False, indent=2))
