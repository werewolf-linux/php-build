import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import inputs
import refresh

FIXTURE = ROOT / 'tests/fixtures/php-8.5.yaml'


class Capture(unittest.TestCase):
    def wolfi(self, root, streams=('8.4', '8.5')):
        """A Wolfi checkout holding the fixture recipe as each stream."""
        for stream in streams:
            config = yaml.safe_load(FIXTURE.read_text())
            config['package']['name'] = 'php-' + stream
            config['package']['version'] = stream + '.1'
            (root / ('php-' + stream + '.yaml')).write_text(yaml.safe_dump(config))
            (root / ('php-' + stream)).mkdir()
            (root / ('php-' + stream) / 'install-pear.patch').write_text('patch\n')
        (root / 'pipelines').mkdir()
        (root / 'pipelines/strip.yaml').write_text('name: strip\n')
        (root / 'wolfi-signing.rsa.pub').write_text('key\n')

    def test_streams_sort_numerically(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for stream in ['8.5', '8.10', '8.4', '10.0']:
                (root / ('php-' + stream + '.yaml')).write_text('')
            (root / 'php-8.5-other.yaml').write_text('')
            self.assertEqual(['8.4', '8.5', '8.10', '10.0'], refresh.streams(root))

    def test_a_recipe_must_be_its_streams_and_pinned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.wolfi(root)
            self.assertEqual('php-8.5.yaml', refresh.recipe(root, '8.5')[0].name)
            with self.assertRaisesRegex(ValueError, 'no recipe'):
                refresh.recipe(root, '8.6')
            config = yaml.safe_load((root / 'php-8.5.yaml').read_text())
            config['pipeline'][0]['with']['expected-commit'] = 'main'
            (root / 'php-8.5.yaml').write_text(yaml.safe_dump(config))
            with self.assertRaisesRegex(ValueError, 'exact source pin'):
                refresh.recipe(root, '8.5')
            config['package']['version'] = '8.6.0'
            (root / 'php-8.5.yaml').write_text(yaml.safe_dump(config))
            with self.assertRaisesRegex(ValueError, 'identity'):
                refresh.recipe(root, '8.5')

    def test_capture_locks_the_policys_stream_and_reports_newer_ones(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout, project = root / 'os', root / 'project'
            checkout.mkdir()
            self.wolfi(checkout, ('8.4', '8.5', '8.6'))
            project.mkdir()
            (project / 'policy.json').write_text(json.dumps({'revision': 2, 'stream': '8.5'}))
            git = {('rev-parse', 'HEAD'): 'c' * 40 + '\n', ('status', '--porcelain'): ''}
            with patch.object(refresh, 'ROOT', project), \
                 patch.object(refresh, 'policy_hashes', lambda: {'policy.json': '0' * 64}), \
                 patch.object(refresh.subprocess, 'check_output', lambda args, text: git[tuple(args[3:])]):
                lock, newer = refresh.capture(checkout, project / 'build/inputs')
            self.assertEqual(['8.6'], newer)
            self.assertEqual(('php-8.5.yaml', '8.5', '8.5.1', 2, 'c' * 40),
                             (lock['recipe'], lock['stream'], lock['version'], lock['revision'], lock['wolfi_commit']))
            self.assertEqual(lock['build_id'], inputs.identity(lock))
            captured = project / 'build/inputs'
            self.assertEqual({'upstream.yaml', 'upstream/install-pear.patch', 'pipelines/strip.yaml',
                              'wolfi-signing.rsa.pub'}, set(lock['sha256']))
            self.assertTrue((captured / 'upstream.lock.json').is_file())

    def test_an_unrelated_wolfi_commit_does_not_rebuild_but_source_and_policy_do(self):
        lock = {'recipe': 'php-8.5.yaml', 'php_commit': '1' * 40, 'revision': 1,
                'sha256': {'upstream.yaml': '2' * 64}, 'mode': {'upstream.yaml': 0o644},
                'policy_sha256': {'patches/series': '3' * 64}, 'wolfi_commit': '4' * 40}
        first = inputs.identity(lock)
        self.assertEqual(first, inputs.identity(dict(lock, wolfi_commit='5' * 40)))
        for changed in [{'php_commit': '6' * 40}, {'revision': 2}, {'policy_sha256': {'patches/series': '7' * 64}}]:
            self.assertNotEqual(first, inputs.identity(dict(lock, **changed)))

    def test_the_stream_is_major_dot_minor(self):
        for bad in ['8', '8.5.1', 'latest', '8.x']:
            with self.assertRaises(ValueError):
                refresh.stream_key(bad)


if __name__ == '__main__':
    unittest.main()
