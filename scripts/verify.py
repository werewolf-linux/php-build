#!/usr/bin/env python3
"""Verify provenance, and that the derivation keeps everything Wolfi builds with."""
from pathlib import Path
import re
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from derive import derive, REMOVED
from inputs import verify, INPUTS

FLAG = re.compile(r'--[a-zA-Z0-9_-]+(?:=[^\s\\]+)?')

def configure(config):
    return next(x['runs'] for x in config['pipeline'] if x.get('name') == 'Configure')

def check(upstream, derived, root=ROOT):
    """Raise AssertionError unless derived keeps what upstream builds with."""
    assert 'git' in derived['pipeline'][0]['needs']['packages'], 'the source fetch needs Git in the guest'
    removed = set(REMOVED.values())
    kept = set(FLAG.findall(configure(upstream))) - removed
    assert kept <= set(FLAG.findall(configure(derived))), 'upstream configure flags removed'
    assert not removed & set(FLAG.findall(configure(derived))), 'a removed facility is still configured'
    assert derived['environment'] == upstream['environment'], 'upstream build environment changed'
    patches = lambda c: [x for x in c['pipeline'] if x.get('uses') == 'patch']
    assert patches(upstream) == patches(derived), "Wolfi's patches changed"
    ours = next(i for i, x in enumerate(derived['pipeline']) if x.get('name') == 'Apply Werewolf policy patches')
    assert derived['pipeline'][ours - 1] == patches(upstream)[-1], "our patches must follow Wolfi's"
    # Configure loses only the removed flags, which the checks above hold.
    steps = lambda c: [x for x in c['pipeline'][1:]
                       if x.get('name') not in ('Apply Werewolf policy patches', 'Configure')]
    assert steps(upstream) == steps(derived), 'an upstream build step changed'
    for test in upstream['test']['pipeline']:
        assert test in derived['test']['pipeline'], "Wolfi's package test removed"
    assert derived['update'] == {'enabled': False}
    series = (root / 'patches/series').read_text().split()
    assert len(series) == len(set(series)) and series, 'patches/series lists each patch once'
    assert set(series) == {p.name for p in (root / 'patches').glob('*.patch')}, 'patches/series and patches/ differ'
    for number, name in enumerate(series, 1):
        assert re.fullmatch(r'%04d-[a-z0-9-]+\.patch' % number, name), name
        text = (root / 'patches' / name).read_text()
        for field in ('SPDX-License-Identifier:', 'Subject:', 'Upstream-Status:', 'Reference:', 'Base-Commit:'):
            assert field in text.split('\ndiff --git', 1)[0], name + ' has no ' + field

def main():
    lock = verify()
    assert re.fullmatch('[0-9a-f]{40}', lock['wolfi_commit'])
    assert re.fullmatch('[0-9a-f]{40}', lock['php_commit'])
    check(yaml.safe_load((INPUTS / 'upstream.yaml').read_text()), derive())
    print('PASS: input hashes, upstream flags, environment, patches, steps and tests, patch series')

if __name__ == '__main__':
    main()
