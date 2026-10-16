#!/usr/bin/env python3
"""Check out the locked php-src and apply Wolfi's patches, then ours, strictly.

git apply refuses fuzz. A patch that no longer applies stops here, naming
itself, the version and git's reason, which scripts/drift.py files as an issue."""
import argparse
import json
from pathlib import Path
import subprocess
import yaml
from inputs import INPUTS
from source import checkout

ROOT = Path(__file__).resolve().parents[1]

def upstream_patches(config):
    """Wolfi's patches, in the order its recipe applies them."""
    names = []
    for step in config['pipeline']:
        if step.get('uses') == 'patch':
            names.extend(step['with']['patches'].split())
    return names

def apply(destination, patch, label):
    check = subprocess.run(['git', '-C', str(destination), 'apply', '--check', str(patch)],
                           capture_output=True, text=True)
    if check.returncode:
        raise SystemExit('prepare: ' + label + ' does not apply\n' + (check.stderr or check.stdout).strip())
    subprocess.run(['git', '-C', str(destination), 'apply', str(patch)], check=True)
    print('prepare: applied ' + label, flush=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path)
    parser.add_argument('--source', type=Path, help='local git repository for offline validation')
    args = parser.parse_args()
    if args.destination.exists():
        raise ValueError('Use a new destination; never reset an existing checkout')
    lock = json.loads((INPUTS / 'upstream.lock.json').read_text())
    print('prepare: PHP {}-r{} from Wolfi {}, php-src {}'.format(
        lock['version'], lock['epoch'], lock['wolfi_commit'], lock['php_commit']), flush=True)
    options = {'sources': (str(args.source),)} if args.source else {}
    checkout(args.destination, lock['php_commit'], **options)
    config = yaml.safe_load((INPUTS / 'upstream.yaml').read_text())
    for name in upstream_patches(config):
        apply(args.destination, INPUTS / 'upstream' / name, "Wolfi's " + name)
    for name in (ROOT / 'patches/series').read_text().split():
        apply(args.destination, ROOT / 'patches' / name, 'patches/' + name)
    print('Source prepared at', args.destination)

if __name__ == '__main__':
    main()
