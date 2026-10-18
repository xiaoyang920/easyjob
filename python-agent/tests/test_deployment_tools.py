import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('deployment_tools',Path(__file__).resolve().parents[2]/'scripts/deploy.py')
deploy=importlib.util.module_from_spec(spec);spec.loader.exec_module(deploy)

class DeploymentToolsTests(unittest.TestCase):
    def test_deployment_and_integration_baselines_do_not_drift(self):
        self.assertEqual((deploy.ROOT/'deploy/mysql/schema.sql').read_bytes(),(deploy.ROOT/'tests/integration/schema.sql').read_bytes())
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def fixture(self, member='uploads/7/x.png', kind=tarfile.REGTYPE):
        (self.root/'database.sql').write_text('CREATE TABLE example (id INT);',encoding='utf-8')
        with tarfile.open(self.root/'assets.tar.gz','w:gz') as archive:
            item=tarfile.TarInfo(member);item.type=kind
            if kind==tarfile.REGTYPE:item.size=3;archive.addfile(item,io.BytesIO(b'img'))
            else:item.linkname='/outside';archive.addfile(item)
        (self.root/'manifest.json').write_text(json.dumps({'format':1,'project':'source-project','snapshot':'backup-20261017120000-abcdef12',
            'files':{name:deploy.sha(self.root/name) for name in deploy.FILES}}),encoding='utf-8')
    def test_validates_hashes_and_rejects_tampering(self):
        self.fixture();self.assertEqual(deploy.verify_backup(self.root)['project'],'source-project')
        with (self.root/'database.sql').open('a') as stream:stream.write('changed')
        with self.assertRaises(ValueError):deploy.verify_backup(self.root)
    def test_rejects_traversal_absolute_paths_and_links(self):
        for name,kind in [('../escape',tarfile.REGTYPE),('/absolute',tarfile.REGTYPE),('uploads/link',tarfile.SYMTYPE),('other/x',tarfile.REGTYPE)]:
            with self.subTest(name=name):
                self.fixture(name,kind)
                with self.assertRaises(ValueError):deploy.verify_backup(self.root)
    def test_restore_refuses_source_and_existing_target_before_mutating_docker(self):
        self.fixture()
        with patch.object(deploy,'run') as run:
            with self.assertRaises(ValueError):deploy.restore('source-project',self.root)
            run.assert_not_called()
        with patch.object(deploy,'docker',return_value='docker'),patch.object(deploy.subprocess,'run') as cli,patch.object(deploy,'run') as run:
            cli.return_value.stdout=b'existing-volume'
            with self.assertRaises(ValueError):deploy.restore('existing-target',self.root)
            run.assert_not_called()
    def test_generated_secrets_are_unique_and_existing_env_is_never_overwritten(self):
        (self.root/'.env.example').write_text((deploy.DEPLOY/'.env.example').read_text(encoding='utf-8'),encoding='utf-8')
        with patch.object(deploy,'DEPLOY',self.root):
            deploy.init_env()
            text=(self.root/'.env').read_text(encoding='utf-8')
            self.assertNotIn('MYSQL_PASSWORD=\n',text)
            self.assertIn('DEEPSEEK_API_KEY=\n',text)
            with self.assertRaises(FileExistsError):deploy.init_env()
            self.assertEqual((self.root/'.env').read_text(encoding='utf-8'),text)
