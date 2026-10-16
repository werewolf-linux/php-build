#!/usr/bin/env python3
"""Record a successful native build; this runs only after all package tests."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
from inputs import ROOT, INPUTS, verify, sha256
from derive import epoch

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--arch', choices=['x86_64', 'aarch64'], required=True)
    args = parser.parse_args()
    lock = verify()
    packages = ROOT / 'build/packages'
    if not (packages / args.arch / 'APKINDEX.tar.gz').is_file():
        raise ValueError('Missing signed package index')
    shutil.copyfile(INPUTS / 'upstream.lock.json', packages / 'upstream.lock.json')
    for path in ['tools.lock.json', 'policy.json', 'build/php.yaml', 'release/packages.pub']:
        shutil.copyfile(ROOT / path, packages / Path(path).name)
    shutil.copyfile(ROOT / 'build/keys/werewolf-packages.rsa.pub', packages / 'werewolf-packages.rsa.pub')
    shutil.copytree(ROOT / 'patches', packages / 'patches')
    subprocess.run(['tar', '-czf', str(packages / 'php-source.tar.gz'),
                    '--exclude=.git', '-C', str(ROOT / 'build/source'), '.'], check=True)
    subprocess.run(['tar', '-czf', str(packages / 'wolfi-inputs.tar.gz'),
                    '-C', str(INPUTS), '.'], check=True)
    record = {'build_id': lock['build_id'], 'arch': args.arch,
              'source_sha': os.environ['GITHUB_SHA'], 'run_id': os.environ['GITHUB_RUN_ID'],
              'version': lock['version'] + '-r' + str(epoch(lock['epoch'], lock['revision'])),
              'sha256': {str(p.relative_to(packages)): sha256(p)
                         for p in sorted(packages.rglob('*')) if p.is_file()}}
    (packages / 'build.json').write_text(json.dumps(record, indent=2) + '\n')

if __name__ == '__main__':
    main()
