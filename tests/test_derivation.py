import copy
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
import derive
import verify

FIXTURE = yaml.safe_load((ROOT / 'tests/fixtures/php-8.5.yaml').read_text())
LOCK = {'stream': '8.5', 'version': '8.5.11', 'epoch': 3, 'revision': 1,
        'php_commit': FIXTURE['pipeline'][0]['with']['expected-commit']}


class Derivation(unittest.TestCase):
    def derived(self, change=None, lock=None):
        """derive() over a copy of Wolfi's recipe, after change(recipe)."""
        upstream = copy.deepcopy(FIXTURE)
        if change:
            change(upstream)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'build/inputs').mkdir(parents=True)
            (root / 'build/inputs/upstream.yaml').write_text(yaml.safe_dump(upstream))
            (root / 'build/inputs/upstream.lock.json').write_text(json.dumps(dict(LOCK, **(lock or {}))))
            shutil.copytree(ROOT / 'tests', root / 'tests')
            with patch.object(derive, 'ROOT', root):
                return upstream, derive.derive()

    def test_wolfi_names_and_a_version_above_every_wolfi_rebuild(self):
        _, derived = self.derived()
        self.assertEqual('php-8.5', derived['package']['name'])
        self.assertEqual(1003, derived['package']['epoch'])
        self.assertEqual([s['name'] for s in FIXTURE['subpackages'] if s['name'] not in derive.REMOVED],
                         [s['name'] for s in derived['subpackages']])
        for section in [derived['package']] + derived['subpackages']:
            self.assertIn('wolfi-origin:php-8.5:8.5.11-r3', section['dependencies']['provides'])
            self.assertNotIn('replaces', section['dependencies'])

    def test_epoch_moves_with_wolfi_and_with_the_policy_never_colliding(self):
        seen = {derive.epoch(e, r) for e in range(0, 50) for r in range(1, 20)}
        self.assertEqual(50 * 19, len(seen))
        self.assertGreater(derive.epoch(0, 1), 999)
        with self.assertRaises(ValueError):
            derive.epoch(1000, 1)

    def test_our_patches_follow_wolfis_and_the_source_is_the_locked_commit(self):
        _, derived = self.derived()
        steps = derived['pipeline']
        self.assertIn(LOCK['php_commit'], steps[0]['runs'])
        self.assertEqual(['git'], steps[0]['needs']['packages'])
        self.assertEqual(['patch', 'patch'], [s.get('uses') for s in steps[1:3]])
        self.assertEqual('Apply Werewolf policy patches', steps[3]['name'])
        self.assertIn('git apply --check', steps[3]['runs'])

    def test_removed_facilities_are_neither_built_nor_packaged(self):
        _, derived = self.derived()
        configure = next(s['runs'] for s in derived['pipeline'] if s.get('name') == 'Configure')
        for name, flag in derive.REMOVED.items():
            self.assertNotIn(flag, configure)
            self.assertNotIn(name, [s['name'] for s in derived['subpackages']])

    def test_the_probe_runs_in_the_package_test_with_what_it_loads(self):
        _, derived = self.derived()
        self.assertIn('sh /tmp/probe.sh /tmp/probe.php', derived['test']['pipeline'][-1]['runs'])
        for name in derive.PROBE_PACKAGES:
            self.assertIn(name, derived['test']['environment']['contents']['packages'])
        self.assertEqual({'enabled': False}, derived['update'])

    def test_verify_accepts_the_derivation_of_wolfis_recipe(self):
        upstream, derived = self.derived()
        verify.check(upstream, derived)

    def test_a_future_upstream_flag_survives(self):
        def add(recipe):
            step = next(s for s in recipe['pipeline'] if s.get('name') == 'Configure')
            step['runs'] = step['runs'].replace('--enable-cli \\\n', '--enable-cli \\\n  --enable-future-protection \\\n')
        upstream, derived = self.derived(add)
        self.assertIn('--enable-future-protection',
                      next(s['runs'] for s in derived['pipeline'] if s.get('name') == 'Configure'))
        verify.check(upstream, derived)

    def test_changed_recipes_stop_the_derivation_for_review(self):
        def checkout(recipe):
            recipe['pipeline'][0]['with']['recurse-submodules'] = 'true'

        def flag(recipe):
            step = next(s for s in recipe['pipeline'] if s.get('name') == 'Configure')
            step['runs'] = step['runs'].replace('--enable-phpdbg=shared', '--enable-phpdbg')

        def subpackage(recipe):
            recipe['subpackages'] = [s for s in recipe['subpackages'] if s['name'] != '${{package.name}}-dbg']

        def depends(recipe):
            fpm = next(s for s in recipe['subpackages'] if s['name'] == '${{package.name}}-fpm')
            fpm['dependencies']['runtime'].append('${{package.name}}-pear')

        def patches(recipe):
            recipe['pipeline'].insert(3, recipe['pipeline'].pop(1))

        def name(recipe):
            recipe['package']['name'] = 'php-8.6'

        for change in [checkout, flag, subpackage, depends, patches, name]:
            with self.subTest(change.__name__), self.assertRaisesRegex(ValueError, 'Review'):
                self.derived(change)

    def test_a_source_pin_other_than_the_lock_is_refused(self):
        with self.assertRaises(AssertionError):
            self.derived(lock={'php_commit': '0' * 40})

    def test_verify_refuses_a_relaxed_derivation(self):
        upstream, derived = self.derived()
        for relax in [
            lambda d: d['pipeline'].remove(next(s for s in d['pipeline'] if s.get('uses') == 'patch')),
            lambda d: d['environment']['contents']['packages'].remove('build-base'),
            lambda d: d['test']['pipeline'].pop(0),
            lambda d: d.update(update={'enabled': True}),
        ]:
            relaxed = copy.deepcopy(derived)
            relax(relaxed)
            with self.subTest(relax=relax), self.assertRaises(AssertionError):
                verify.check(upstream, relaxed)


class Probe(unittest.TestCase):
    def test_probe_cannot_end_its_heredoc_early_or_use_melange_variables(self):
        for text in ['${{package.name}}', derive.PROBE_PHP, derive.PROBE_SH]:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                shutil.copytree(ROOT / 'tests', root / 'tests')
                (root / 'tests/probe.sh').write_text('echo ' + text + '\n')
                with patch.object(derive, 'ROOT', root), self.assertRaises(ValueError):
                    derive.probe()


if __name__ == '__main__':
    unittest.main()
