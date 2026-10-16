import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import drift

LOCK = {'version': '8.5.12', 'epoch': 0, 'recipe': 'php-8.5.yaml',
        'wolfi_commit': 'a' * 40, 'php_commit': 'b' * 40}
PREPARE = ('prepare: PHP 8.5.12-r0 from Wolfi aaaa, php-src bbbb\n'
           "prepare: applied Wolfi's install-pear.patch\n"
           'prepare: applied patches/0001-deny-environment-configuration.patch\n'
           'prepare: patches/0002-werewolf-allowances.patch does not apply\n'
           'error: patch failed: main/main.c:769\n'
           'error: main/main.c: patch does not apply\n')
RUN = 'https://github.com/werewolf-linux/php-build/actions/runs/7'


class Report(unittest.TestCase):
    def test_a_patch_failure_names_the_version_the_patch_and_gits_output(self):
        title, body, _ = drift.report('patches', PREPARE, LOCK, '8.5', RUN)
        self.assertEqual('PHP 8.5.12-r0: patches/0002-werewolf-allowances.patch no longer applies', title)
        for fact in ['8.5.12-r0', 'patches/0002-werewolf-allowances.patch does not apply', 'a' * 40,
                     'b' * 40, 'php-8.5.yaml', RUN, 'error: patch failed: main/main.c:769']:
            self.assertIn(fact, body)

    def test_wolfis_own_patch_failing_is_named_too(self):
        log = "prepare: Wolfi's install-pear.patch does not apply\nerror: x\n"
        title, _, _ = drift.report('patches', log, LOCK, '8.5', None)
        self.assertEqual("PHP 8.5.12-r0: Wolfi's install-pear.patch no longer applies", title)

    def test_a_capture_failure_has_no_lock_and_names_the_stream(self):
        title, body, _ = drift.report('refresh', 'ValueError: Review changed Wolfi PHP 8.5 recipe identity\n',
                                      None, '8.5', None)
        self.assertEqual('PHP 8.5: capturing the recipe stopped', title)
        self.assertIn('Review changed Wolfi PHP 8.5 recipe identity', body)

    def test_a_derivation_failure(self):
        title, body, _ = drift.report('derivation', 'ValueError: Review changed upstream configure flag\n',
                                      LOCK, '8.5', None)
        self.assertEqual('PHP 8.5.12-r0: the derivation stopped', title)
        self.assertIn('Review changed upstream configure flag', body)

    def test_a_newer_stream(self):
        newer = json.dumps({'stream': '8.5', 'newer': ['8.6', '8.7'], 'wolfi_commit': 'c' * 40})
        title, body, marker = drift.report('stream', newer, None, '8.5', None)
        self.assertEqual('Wolfi builds PHP 8.7; policy.json follows 8.5', title)
        self.assertIn('8.6, 8.7', body)
        self.assertEqual('stream:8.6,8.7', marker)

    def test_the_marker_ignores_the_run_but_not_the_failure(self):
        one = drift.report('patches', PREPARE, LOCK, '8.5', RUN)[2]
        self.assertEqual(one, drift.report('patches', PREPARE, LOCK, '8.5', RUN + '9')[2])
        self.assertNotEqual(one, drift.report('patches', PREPARE + 'error: more\n', LOCK, '8.5', RUN)[2])

    def test_output_keeps_the_end_strips_colour_and_cannot_close_its_fence(self):
        text = '\n'.join(str(n) for n in range(1000)) + '\n\x1b[31mred\x1b[0m ``` end'
        kept = drift.output(text)
        self.assertEqual(drift.TAIL, len(kept.splitlines()))
        self.assertTrue(kept.endswith("red ''' end"))
        self.assertLessEqual(len(drift.output('x' * 10 ** 6)), drift.LIMIT)


class Filing(unittest.TestCase):
    def runner(self, issues=(), seen=None):
        calls = []
        def run(*args):
            calls.append(args)
            if args[:2] == ('issue', 'list'):
                return json.dumps(list(issues))
            if args[:2] == ('issue', 'view'):
                return json.dumps(seen or {'body': '', 'comments': []})
            if args[:2] == ('issue', 'create'):
                return 'https://github.com/werewolf-linux/php-build/issues/9\n'
            return ''
        return run, calls

    def test_opens_an_issue_with_the_drift_label(self):
        run, calls = self.runner()
        self.assertEqual(('opened', 'https://github.com/werewolf-linux/php-build/issues/9'),
                         drift.file('PHP 1: x', 'body', 'm', run))
        self.assertEqual(('label', 'create', drift.LABEL), calls[0][:3])
        create = next(c for c in calls if c[:2] == ('issue', 'create'))
        self.assertIn('PHP 1: x', create)
        self.assertIn(drift.LABEL, create)

    def test_the_same_failure_again_adds_nothing(self):
        run, calls = self.runner([{'number': 4, 'title': 'PHP 1: x'}],
                                 {'body': 'b\n<!-- drift m -->\n', 'comments': []})
        self.assertEqual(('unchanged', 4), drift.file('PHP 1: x', 'body', 'm', run))
        self.assertFalse(any(c[:2] in (('issue', 'create'), ('issue', 'comment')) for c in calls))

    def test_a_different_failure_under_the_same_title_is_a_comment(self):
        run, calls = self.runner([{'number': 4, 'title': 'PHP 1: x'}],
                                 {'body': '<!-- drift old -->', 'comments': [{'body': '<!-- drift older -->'}]})
        self.assertEqual(('commented', 4), drift.file('PHP 1: x', 'body', 'new', run))
        self.assertTrue(any(c[:3] == ('issue', 'comment', '4') for c in calls))

    def test_a_passing_run_closes_failures_but_not_a_newer_stream(self):
        run, calls = self.runner([{'number': 1, 'title': 'PHP 8.5.12-r0: patches/0002-x.patch no longer applies'},
                                  {'number': 2, 'title': 'Wolfi builds PHP 8.6; policy.json follows 8.5'},
                                  {'number': 3, 'title': 'PHP 8.5: capturing the recipe stopped'}])
        self.assertEqual([1, 3], drift.resolve(drift.FAILED, 'fixed', run))
        self.assertEqual([('issue', 'close', '1', '--comment', 'fixed'), ('issue', 'close', '3', '--comment', 'fixed')],
                         [c for c in calls if c[:2] == ('issue', 'close')])

    def test_failure_titles_and_stream_titles_never_share_a_prefix(self):
        for kind, log, lock in [('patches', PREPARE, LOCK), ('refresh', 'x', None), ('derivation', 'x', LOCK)]:
            title = drift.report(kind, log, lock, '8.5', None)[0]
            self.assertTrue(title.startswith(drift.FAILED) and not title.startswith(drift.STREAM))
        newer = json.dumps({'stream': '8.5', 'newer': ['8.6'], 'wolfi_commit': 'c' * 40})
        title = drift.report('stream', newer, None, '8.5', None)[0]
        self.assertTrue(title.startswith(drift.STREAM) and not title.startswith(drift.FAILED))


if __name__ == '__main__':
    unittest.main()
