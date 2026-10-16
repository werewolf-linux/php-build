import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import publish

FIXTURE = yaml.safe_load((ROOT / 'tests/fixtures/php-8.5.yaml').read_text())


def stanza(name, version, arch='aarch64'):
    return 'P:{}\nV:{}\nA:{}\nS:10\n'.format(name, version, arch).strip()


class StableIndex(unittest.TestCase):
    def keys(self, directory):
        private, public = Path(directory) / 'key.rsa', Path(directory) / 'key.pub'
        subprocess.run(['openssl', 'genrsa', '-out', str(private), '2048'], check=True, capture_output=True)
        subprocess.run(['openssl', 'rsa', '-in', str(private), '-pubout', '-out', str(public)],
                       check=True, capture_output=True)
        return private, public

    def test_a_signed_index_authenticates_and_holds_every_stanza(self):
        with tempfile.TemporaryDirectory() as directory:
            private, public = self.keys(directory)
            found = {'php-8.5-8.5.11-r1003.apk': stanza('php-8.5', '8.5.11-r1003'),
                     'php-8.5-fpm-8.5.11-r1003.apk': stanza('php-8.5-fpm', '8.5.11-r1003')}
            index = Path(directory) / 'APKINDEX.tar.gz'
            index.write_bytes(publish.signed_index(found, private))
            self.assertEqual(found, publish.entries(publish.authenticated(index, public)))

    def test_a_changed_index_does_not_authenticate(self):
        with tempfile.TemporaryDirectory() as directory:
            private, public = self.keys(directory)
            data = publish.signed_index({'a-1-r1.apk': stanza('a', '1-r1')}, private)
            forged = publish.signed_index({'a-1-r1.apk': stanza('a', '2-r1')}, private)
            # The first build's signature over the second build's index.
            signature = publish.members(data)[0][0]
            index = Path(directory) / 'APKINDEX.tar.gz'
            index.write_bytes(signature + publish.members(forged)[1][0])
            with self.assertRaises(subprocess.CalledProcessError):
                publish.authenticated(index, public)

    def test_merge_keeps_every_published_build_and_never_replaces_one(self):
        previous = {'a-1-r1.apk': 'old'}
        merged, added = publish.merge(previous, {'a-1-r1.apk': 'rebuilt', 'a-2-r1.apk': 'new'})
        self.assertEqual({'a-1-r1.apk': 'old', 'a-2-r1.apk': 'new'}, merged)
        self.assertEqual(['a-2-r1.apk'], added)

    def test_archives_are_the_same_bytes_from_the_same_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'tree'
            (root / 'aarch64').mkdir(parents=True)
            (root / 'aarch64/a.apk').write_bytes(b'apk')
            one, two = Path(directory) / 'one.tar.gz', Path(directory) / 'two.tar.gz'
            publish.archive(root, one)
            (root / 'aarch64/a.apk').touch()
            publish.archive(root, two)
            self.assertEqual(one.read_bytes(), two.read_bytes())


class Packages(unittest.TestCase):
    def test_every_range_and_named_subpackage_is_expected(self):
        config = copy.deepcopy(FIXTURE)
        names = publish.package_names(config)
        self.assertIn('php-8.5', names)
        self.assertIn('php-8.5-fpm', names)
        self.assertIn('php-8.5-phar', names)
        self.assertIn('php-8.5-phar-config', names)
        self.assertNotIn('php-8.5-${{range.key}}', names)
        extensions = len(FIXTURE['data'][0]['items'])
        self.assertEqual(1 + 2 * extensions + len(FIXTURE['subpackages']) - 2, len(names))

    def test_the_version_published_is_wolfis_with_our_epoch(self):
        self.assertEqual('8.5.11-r1003', publish.expected({'version': '8.5.11', 'epoch': 3, 'revision': 1}))
        self.assertEqual('8.5.11-r2004', publish.expected({'version': '8.5.11', 'epoch': 4, 'revision': 2}))


class Status(unittest.TestCase):
    def test_a_release_is_built_staged_or_complete(self):
        cases = [(None, 'build'),
                 ({'draft': True, 'assets': [{'name': 'php-aarch64.tar.gz'}]}, 'build'),
                 ({'draft': True, 'assets': [{'name': 'release.json'}]}, 'publish'),
                 ({'draft': False, 'assets': [{'name': 'release.json'}]}, 'complete')]
        for found, state in cases:
            with self.subTest(state=state), patch.object(publish, 'release', return_value=found):
                self.assertEqual(state, publish.status('build-x'))
        with patch.object(publish, 'release', return_value={'draft': False, 'assets': []}), \
             self.assertRaises(ValueError):
            publish.status('build-x')


if __name__ == '__main__':
    unittest.main()
