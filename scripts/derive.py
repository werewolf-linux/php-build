#!/usr/bin/env python3
"""Derive a build context from the unchanged, pinned Wolfi PHP recipe.

Every step this edits is checked first: a recipe that has changed there stops
the derivation, for a person to review, rather than being edited blind."""
import json
from pathlib import Path
import re
import shutil
import yaml

ROOT = Path(__file__).resolve().parents[1]
# What the build leaves out, and the configure flag that builds each.
REMOVED = {'${{package.name}}-dbg': '--enable-phpdbg=shared',  # phpdbg, an interactive debugger
           '${{package.name}}-pear': '--with-pear'}  # PEAR, which installs code from the network
# The package test loads these, so the probe sees their functions and wrapper held.
PROBE_PACKAGES = ['${{package.name}}-pcntl', '${{package.name}}-phar']
SOURCE = 'https://github.com/php/php-src.git'
PROBE_PHP, PROBE_SH = 'WEREWOLF_PROBE_PHP', 'WEREWOLF_PROBE_SH'

def epoch(wolfi_epoch, revision):
    """Our epoch: above every Wolfi rebuild of the same PHP release, so apk
    prefers ours, and moving when either Wolfi's epoch or our revision does."""
    if not 0 <= wolfi_epoch < 1000:
        raise ValueError('Review Wolfi epoch ' + str(wolfi_epoch) + ': ours would no longer sort above it')
    return 1000 * revision + wolfi_epoch

def fetch(commit):
    # The guest fetches the one commit the lock names, and checks it is that one.
    return ('git init -q .\n'
            'for delay in 0 15 45; do\n'
            '  sleep "$delay"\n'
            '  if git -c fetch.fsckObjects=true fetch --no-tags --depth=1 ' + SOURCE + ' ' + commit + '; then\n'
            '    test "$(git rev-parse FETCH_HEAD)" = ' + commit + '\n'
            '    git checkout -q --detach ' + commit + '\n'
            '    exit 0\n'
            '  fi\n'
            'done\n'
            'echo "php-src ' + commit + ': fetch failed three times" >&2\n'
            'exit 1\n')

def probe():
    php = (ROOT / 'tests/probe.php').read_text()
    sh = (ROOT / 'tests/probe.sh').read_text()
    for text in (php, sh):
        if '${{' in text or PROBE_PHP in text or PROBE_SH in text:
            raise ValueError('tests/probe.* cannot be embedded in a Melange recipe')
    return ("cat > /tmp/probe.php <<'" + PROBE_PHP + "'\n" + php + PROBE_PHP + '\n' +
            "cat > /tmp/probe.sh <<'" + PROBE_SH + "'\n" + sh + PROBE_SH + '\n' +
            'sh /tmp/probe.sh /tmp/probe.php\n')

def derive():
    config = yaml.safe_load((ROOT / 'build/inputs/upstream.yaml').read_text())
    lock = json.loads((ROOT / 'build/inputs/upstream.lock.json').read_text())
    original = config['package']['name']
    if original != 'php-' + lock['stream'] or str(config['package']['version']) != lock['version']:
        raise ValueError('Review changed upstream package identity before deriving')
    pipeline = config['pipeline']
    source = pipeline[0]
    assert source.get('with', {}).get('expected-commit') == lock['php_commit'], 'source pin differs from the lock'
    if source != {'uses': 'git-checkout', 'with': {'repository': 'https://github.com/php/php-src',
                                                   'tag': 'php-${{package.version}}',
                                                   'expected-commit': lock['php_commit']}}:
        raise ValueError('Review changed upstream source checkout before deriving')
    pipeline[0] = {'name': 'Fetch the locked php-src commit', 'needs': {'packages': ['git']},
                   'runs': fetch(lock['php_commit'])}
    # Wolfi's patches first, as Wolfi applies them; then ours, without fuzz.
    patched = [i for i, step in enumerate(pipeline) if step.get('uses') == 'patch']
    if not patched or patched != list(range(1, patched[-1] + 1)):
        raise ValueError('Review changed upstream patch steps before deriving')
    pipeline.insert(patched[-1] + 1, {'name': 'Apply Werewolf policy patches', 'runs':
        'while IFS= read -r patch; do\n'
        '  git apply --check "werewolf/patches/$patch"\n'
        '  git apply "werewolf/patches/$patch"\n'
        'done < werewolf/patches/series\n'})
    configure = [step for step in pipeline if step.get('name') == 'Configure']
    if len(configure) != 1:
        raise ValueError('Review changed upstream configure step before deriving')
    for flag in REMOVED.values():
        line = re.compile(r'^[ \t]*' + re.escape(flag) + r'[ \t]*\\\n', re.M)
        configure[0]['runs'], count = line.subn('', configure[0]['runs'])
        if count != 1:
            raise ValueError('Review changed upstream configure flag ' + flag + ' before deriving')
    wolfi = str(config['package']['version']) + '-r' + str(config['package']['epoch'])
    config['package']['epoch'] = epoch(config['package']['epoch'], lock['revision'])
    config['package']['description'] += ' (Werewolf fixed hardening policy)'
    names = [sub['name'] for sub in config['subpackages']]
    if not set(REMOVED) <= set(names):
        raise ValueError('Review changed upstream subpackages before deriving')
    kept = [sub for sub in config['subpackages'] if sub['name'] not in REMOVED]
    for sub in kept:
        runtime = sub.get('dependencies', {}).get('runtime', [])
        if any(name in REMOVED for name in runtime):
            raise ValueError('Review ' + sub['name'] + ': it depends on a package this build leaves out')
    config['subpackages'] = kept
    # Each package names the Wolfi build it rebuilds: werewolf matches Wolfi's
    # CVE fixes against that (lib/prebuilt.zig), not against our epoch.
    for section in [config['package']] + kept:
        section.setdefault('dependencies', {}).setdefault('provides', []).append(
            'wolfi-origin:' + original + ':' + wolfi)
    test = config['test']
    test.setdefault('environment', {}).setdefault('contents', {}).setdefault('packages', []).extend(PROBE_PACKAGES)
    test['pipeline'].append({'name': 'Werewolf protections hold, and allowances take each back',
                             'runs': probe()})
    config['update'] = {'enabled': False}
    return config

def main():
    context = ROOT / 'build/context'
    if context.exists():
        shutil.rmtree(context)
    shutil.copytree(ROOT / 'build/inputs/upstream', context)
    # Beside Wolfi's files, under a name php-src does not use at its top.
    shutil.copytree(ROOT / 'patches', context / 'werewolf/patches')
    recipe = ROOT / 'build/php.yaml'
    recipe.write_text(yaml.safe_dump(derive(), sort_keys=False, width=120))
    print(recipe)

if __name__ == '__main__':
    main()
