#!/usr/bin/env python3
"""Capture Wolfi's recipe for the PHP stream policy.json names, unchanged.

A newer stream in Wolfi is reported, not followed: a minor release changes the
language, so a person moves policy.json's stream (scripts/drift.py files it)."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import yaml
from inputs import ROOT, INPUTS, identity, policy_hashes, sha256, file_modes

STREAM = re.compile(r'([0-9]+)\.([0-9]+)')
NEWER = ROOT / 'build/newer-stream.json'

def stream_key(stream):
    match = STREAM.fullmatch(stream)
    if not match:
        raise ValueError('A PHP stream is MAJOR.MINOR: ' + repr(stream))
    return int(match.group(1)), int(match.group(2))

def streams(checkout):
    """The PHP streams Wolfi builds, oldest first."""
    found = []
    for path in checkout.glob('php-*.yaml'):
        match = re.fullmatch(r'php-([0-9]+\.[0-9]+)\.yaml', path.name)
        if match:
            found.append(match.group(1))
    return sorted(found, key=stream_key)

def recipe(checkout, stream):
    path = checkout / ('php-' + stream + '.yaml')
    if not path.is_file():
        raise ValueError('Wolfi has no recipe for PHP ' + stream)
    config = yaml.safe_load(path.read_text())
    package = config.get('package', {})
    version = str(package.get('version', ''))
    if package.get('name') != 'php-' + stream or not re.fullmatch(re.escape(stream) + r'\.[0-9]+', version):
        raise ValueError('Review changed Wolfi PHP ' + stream + ' recipe identity')
    source = config['pipeline'][0]
    commit = str(source.get('with', {}).get('expected-commit', ''))
    if source.get('uses') != 'git-checkout' or not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('Wolfi PHP ' + stream + ' recipe has no exact source pin')
    return path, config

def capture(checkout, destination=INPUTS):
    policy = json.loads((ROOT / 'policy.json').read_text())
    revision, stream = policy['revision'], policy['stream']
    if type(revision) is not int or revision < 1:
        raise ValueError('Policy revision must be a positive integer')
    stream_key(stream)
    path, config = recipe(checkout, stream)
    commit = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
    if subprocess.check_output(['git', '-C', str(checkout), 'status', '--porcelain'], text=True).strip():
        raise ValueError('Wolfi checkout has local changes')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix='inputs-') as directory:
        candidate = Path(directory)
        shutil.copyfile(path, candidate / 'upstream.yaml')
        shutil.copytree(checkout / path.stem, candidate / 'upstream')
        shutil.copytree(checkout / 'pipelines', candidate / 'pipelines')
        shutil.copyfile(checkout / 'wolfi-signing.rsa.pub', candidate / 'wolfi-signing.rsa.pub')
        lock = {'repository': 'https://github.com/wolfi-dev/os', 'recipe': path.name, 'stream': stream,
                'wolfi_commit': commit, 'php_commit': config['pipeline'][0]['with']['expected-commit'],
                'version': str(config['package']['version']), 'epoch': config['package']['epoch'],
                'revision': revision,
                'sha256': {str(p.relative_to(candidate)): sha256(p) for p in sorted(candidate.rglob('*')) if p.is_file()},
                'mode': file_modes(candidate),
                'policy_sha256': policy_hashes()}
        lock['build_id'] = identity(lock)
        (candidate / 'upstream.lock.json').write_text(json.dumps(lock, indent=2) + '\n')
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(candidate, destination)
    return lock, [s for s in streams(checkout) if stream_key(s) > stream_key(stream)]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--wolfi', type=Path, help='clean existing Wolfi checkout for offline use')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='neutered-wolfi-') as directory:
        checkout = args.wolfi
        if checkout is None:
            checkout = Path(directory) / 'os'
            subprocess.run(['git', 'clone', '--depth=1', 'https://github.com/wolfi-dev/os.git', str(checkout)], check=True)
        lock, newer = capture(checkout)
    NEWER.unlink(missing_ok=True)
    if newer:
        NEWER.write_text(json.dumps({'stream': lock['stream'], 'newer': newer,
                                     'wolfi_commit': lock['wolfi_commit']}) + '\n')
        print('Wolfi builds newer PHP than policy.json names:', ', '.join(newer))
    print('Wolfi PHP', lock['version'] + '-r' + str(lock['epoch']), 'build', lock['build_id'])

if __name__ == '__main__':
    main()
