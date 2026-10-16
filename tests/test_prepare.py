from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import prepare


def change(before, after):
    return '--- a/policy.txt\n+++ b/policy.txt\n@@ -1 +1 @@\n-' + before + '\n+' + after + '\n'


class Application(unittest.TestCase):
    def test_wolfis_patches_in_recipe_order(self):
        config = {'pipeline': [{'uses': 'git-checkout'}, {'uses': 'patch', 'with': {'patches': 'a.patch b.patch'}},
                               {'name': 'Configure'}, {'uses': 'patch', 'with': {'patches': 'c.patch'}}]}
        self.assertEqual(['a.patch', 'b.patch', 'c.patch'], prepare.upstream_patches(config))

    def test_a_patch_applies_strictly_or_names_itself_and_gits_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source'
            source.mkdir()
            (source / 'policy.txt').write_text('base\n')
            good, bad = Path(directory) / 'good.patch', Path(directory) / 'bad.patch'
            good.write_text(change('base', 'upstream'))
            bad.write_text(change('base', 'downstream'))
            prepare.apply(source, good, "Wolfi's good.patch")
            self.assertEqual('upstream\n', (source / 'policy.txt').read_text())
            with self.assertRaises(SystemExit) as stopped:
                prepare.apply(source, bad, 'patches/0001-bad.patch')
            message = str(stopped.exception.code)
            self.assertTrue(message.startswith('prepare: patches/0001-bad.patch does not apply\n'))
            self.assertIn('policy.txt', message)
            self.assertEqual('upstream\n', (source / 'policy.txt').read_text())


if __name__ == '__main__':
    unittest.main()
