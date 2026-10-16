"""Offline maintenance checks; actual IK behavior is exercised by chinese-search.py verify."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]


def module(filename, name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


installer = module('install-chinese-analysis.py', 'chinese_installer')
maintenance = module('chinese-search.py', 'chinese_maintenance')
DOCTYPE = b'<!DOCTYPE properties SYSTEM "http://java.sun.com/dtd/properties.dtd">'


class ChineseSearchMaintenanceTests(unittest.TestCase):
    def test_installer_preserves_other_dictionaries_and_java_properties_doctype(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home/'bin').mkdir()
            (home/'bin/elasticsearch').touch()
            config = home/'plugins/ik/config/IKAnalyzer.cfg.xml'
            config.parent.mkdir(parents=True)
            config.write_bytes(b'<?xml version="1.0"?>\n'+DOCTYPE+b'\n<properties>'
                b'<entry key="ext_dict">other.dic</entry><entry key="remote_ext_dict">https://example.invalid/dict</entry>'
                b'</properties>')
            with patch.object(installer, 'ROOT', home/'reports'):
                dry = installer.install(home, check=True)
                self.assertEqual(len(dry['changed_files']), 3)
                self.assertNotIn(b'easyjob-technical', config.read_bytes())
                installer.install(home)
                entries = {e.get('key'): e.text for e in ET.fromstring(config.read_bytes())}
                self.assertEqual(entries['ext_dict'], 'other.dic;custom/easyjob-technical.dic')
                self.assertEqual(entries['remote_ext_dict'], 'https://example.invalid/dict')
                self.assertIn(DOCTYPE, config.read_bytes())
                self.assertEqual(installer.install(home)['changed_files'], [])

    def test_installer_repairs_missing_doctype_even_if_dictionary_is_registered(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home/'bin').mkdir()
            (home/'bin/elasticsearch').touch()
            config = home/'config/analysis-ik/IKAnalyzer.cfg.xml'
            config.parent.mkdir(parents=True)
            config.write_text('<properties><entry key="ext_dict">custom/easyjob-technical.dic</entry></properties>')
            _, planned = installer.prepare(home)
            self.assertIn(DOCTYPE, planned[config])
            self.assertEqual(len(ET.fromstring(planned[config]).findall('entry')), 1)

    def test_additive_mapping_keeps_existing_analyzer_and_does_not_mutate_original(self):
        original = {'title': {'type': 'text', 'analyzer': 'ik_max_word',
            'fields': {'keyword': {'type': 'keyword'}}}}
        result = maintenance.additions(original, ['title'])['properties']['title']
        self.assertEqual(result['analyzer'], 'ik_max_word')
        self.assertEqual(result['fields']['zh']['search_analyzer'], 'easyjob_zh_search')
        self.assertEqual(original['title']['fields'], {'keyword': {'type': 'keyword'}})
        with self.assertRaises(ValueError):
            maintenance.additions({'title': {'type': 'keyword'}}, ['title'])

    def test_migration_failure_unblocks_source_and_never_changes_mapping_without_backup(self):
        class BrokenClone:
            def __init__(self): self.calls = []
            def call(self, method, path, body=None):
                self.calls.append((method, path, body))
                if path == '/article':
                    return {'article': {'settings': {'index': {}}, 'mappings': {'properties': {}}}}
                if '/_clone/' in path: raise RuntimeError('clone unavailable')
                return {}
        es = BrokenClone()
        with patch.object(maintenance, 'fingerprint', return_value={'documents': 2}):
            with self.assertRaisesRegex(RuntimeError, 'clone unavailable'):
                maintenance.apply_index(es, 'article', {'indexes': []})
        self.assertEqual(es.calls[-1], ('PUT', '/article/_settings', {'index.blocks.write': False}))
        self.assertFalse(any('/_mapping' in path or '/_close' in path for _, path, _ in es.calls))

    def test_migration_reopens_index_if_settings_update_fails(self):
        class BrokenSettings:
            def __init__(self): self.calls = []
            def call(self, method, path, body=None):
                self.calls.append((method, path, body))
                if path == '/article':
                    return {'article': {'settings': {'index': {}}, 'mappings': {'properties': {}}}}
                if '/_cluster/health/' in path: return {'status': 'green'}
                if path == '/article/_settings' and body == maintenance.analysis_settings():
                    raise RuntimeError('settings unavailable')
                return {}
        es = BrokenSettings()
        with patch.object(maintenance, 'fingerprint', return_value={'documents': 2}):
            with self.assertRaisesRegex(RuntimeError, 'settings unavailable'):
                maintenance.apply_index(es, 'article', {'indexes': []})
        self.assertEqual(es.calls[-1][1], '/article/_open')
        self.assertFalse(any('/_mapping' in path for _, path, _ in es.calls))

    def test_migration_refuses_unrelated_indexes_and_existing_write_block(self):
        class ReadOnly:
            def call(self, method, path, body=None):
                return {'article': {'settings': {'index': {'blocks': {'write': 'true'}}}}}
        with self.assertRaises(ValueError):
            maintenance.apply_index(ReadOnly(), 'private_memory', {'indexes': []})
        with self.assertRaisesRegex(ValueError, 'already write-blocked'):
            maintenance.apply_index(ReadOnly(), 'article', {'indexes': []})

    def test_fingerprint_requests_es9_vector_rehydration_and_closes_scroll(self):
        class Corpus:
            major = 9
            def __init__(self): self.calls = []
            def call(self, method, path, body=None):
                self.calls.append((method, path, body))
                if path.startswith('/article_vectors/_search'):
                    return {'_scroll_id': 'owned-scroll', 'hits': {'hits': [{'_id': 'same-id',
                        '_source': {'chunk_id': 'same-chunk', 'content_vector': [0.123456789, 0.2]}}]}}
                return {'hits': {'hits': []}}
        es = Corpus()
        result = maintenance.fingerprint(es, 'article_vectors')
        self.assertEqual(result['vectors'], 1)
        self.assertEqual(es.calls[0][2]['_source'], {'exclude_vectors': False})
        self.assertEqual(es.calls[-1], ('DELETE', '/_search/scroll', {'scroll_id': ['owned-scroll']}))

    def test_synonyms_only_run_at_query_time_and_distinct_cache_failures_stay_distinct(self):
        analysis = maintenance.analysis_settings()['analysis']
        self.assertNotIn('easyjob_technical_synonyms', analysis['analyzer']['easyjob_zh_index']['filter'])
        self.assertIn('easyjob_technical_synonyms', analysis['analyzer']['easyjob_zh_search']['filter'])
        self.assertTrue(analysis['filter']['easyjob_technical_synonyms']['updateable'])
        synonyms = (installer.ASSETS/'easyjob-synonyms.txt').read_text(encoding='utf-8')
        for word in ['缓存穿透', '缓存击穿', '缓存雪崩']:
            self.assertNotIn(word, synonyms)


if __name__ == '__main__':
    unittest.main()
