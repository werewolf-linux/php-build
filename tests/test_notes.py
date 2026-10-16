from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import notes

SECDB = {'packages': [
    {'pkg': {'name': 'php-8.5', 'secfixes': {'0': ['CVE-2000-0001'], '8.5.10-r0': ['CVE-2026-1'],
                                              '8.5.11-r2': ['CVE-2026-3', 'CVE-2026-2'], '8.5.12-r0': ['CVE-2026-4']}}},
    {'pkg': {'name': 'php-8.4', 'secfixes': {'8.4.20-r0': ['CVE-2026-9']}}}]}


def facts(previous=None, commits=()):
    return {'version': '8.5.11-r1003', 'build_id': 'f' * 64, 'date': '2026-10-15', 'commit': 'c' * 40,
            'run': 'https://github.com/werewolf-linux/php-build/actions/runs/1',
            'source': {'php_commit': 'b' * 40, 'wolfi_commit': 'a' * 40, 'wolfi_version': '8.5.11-r3',
                       'recipe': 'php-8.5.yaml', 'policy_revision': 1},
            'repository': {'stable': 'https://dist.werewolf-linux.org/apk/php/',
                           'snapshot': 'https://dist.werewolf-linux.org/apk/php/builds/' + 'f' * 64,
                           'key_sha256': '0' * 64},
            'patches': ['0001-a.patch', '0002-b.patch'], 'wolfi_inputs': {}, 'previous': previous,
            'commits': list(commits),
            'security': notes.security(SECDB, 'php-8.5', previous['wolfi_version'] if previous else None, '8.5.11-r3'),
            'architectures': {'x86_64': {'packages': [{'name': 'php-8.5', 'version': '8.5.11-r1003', 'size': 1234}]},
                              'aarch64': {'packages': [{'name': 'php-8.5', 'version': '8.5.11-r1003', 'size': 999}]}}}


class Notes(unittest.TestCase):
    def test_security_counts_wolfis_fixes_in_the_window_through_this_build(self):
        found = notes.security(SECDB, 'php-8.5', '8.5.10-r0', '8.5.11-r3')
        self.assertEqual([{'version': '8.5.11-r2', 'ids': ['CVE-2026-2', 'CVE-2026-3']}], found['fixed'])
        self.assertEqual(3, found['cumulative'])
        self.assertEqual(1, found['not_affected'])
        self.assertEqual([], notes.security(SECDB, 'php-8.5', None, '8.5.11-r3')['fixed'])

    def test_the_first_release(self):
        text = notes.markdown(notes.build(facts()))
        self.assertTrue(text.startswith('# PHP 8.5.11-r1003\n'))
        for fact in ['The first release.', '8.5.11-r3', 'php-8.5.yaml', '`0002-b.patch`', '| php-8.5 | 1,234 | 999 |']:
            self.assertIn(fact, text)

    def test_what_changed_since_the_previous_release(self):
        previous = {'version': '8.5.10-r1003', 'build_id': 'e' * 64, 'commit': 'd' * 40,
                    'wolfi_version': '8.5.10-r0', 'php_commit': '9' * 40}
        text = notes.markdown(notes.build(facts(previous, [{'sha': '1' * 40, 'subject': 'Tighten the floor'}])))
        self.assertIn('Since 8.5.10-r1003:', text)
        self.assertIn("Wolfi's build: 8.5.10-r0 → 8.5.11-r3", text)
        self.assertIn('/compare/' + '9' * 40 + '...' + 'b' * 40, text)
        self.assertIn('Tighten the floor', text)
        self.assertIn('CVE-2026-2, CVE-2026-3', text)

    def test_an_unanswered_github_is_unavailable_never_unchanged(self):
        previous = {'version': '8.5.10-r1003', 'build_id': 'e' * 64, 'commit': 'd' * 40,
                    'wolfi_version': '8.5.10-r0', 'php_commit': 'b' * 40}
        made = notes.build(facts(previous))
        made['commits'] = None
        text = notes.markdown(made)
        self.assertIn('unavailable', text)
        self.assertNotIn('unchanged', text)


if __name__ == '__main__':
    unittest.main()
