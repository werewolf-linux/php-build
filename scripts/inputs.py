"""Identify the exact upstream and downstream build inputs."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / 'build/inputs'
POLICY_INPUTS = ['Makefile', 'requirements.txt', 'tools.lock.json', 'policy.json',
                 'scripts', 'tests', 'patches', '.github/workflows', 'release/packages.pub']

def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def policy_hashes(root=ROOT):
    files = []
    for name in POLICY_INPUTS:
        path = root / name
        files.extend(path.rglob('*') if path.is_dir() else [path])
    return {str(p.relative_to(root)): sha256(p) for p in sorted(files)
            if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}

def file_modes(directory):
    return {str(p.relative_to(directory)): p.stat().st_mode & 0o7777
            for p in sorted(directory.rglob('*'))
            if p.is_file() and p.name != 'upstream.lock.json'}

def identity(lock):
    # A Wolfi commit changing an unrelated package is provenance, not a rebuild.
    relevant = {key: lock[key] for key in ['recipe', 'php_commit', 'revision', 'sha256', 'mode', 'policy_sha256']}
    return hashlib.sha256(json.dumps(relevant, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def verify(directory=INPUTS):
    lock = json.loads((directory / 'upstream.lock.json').read_text())
    for name, digest in lock['sha256'].items():
        path = directory / name
        if not path.resolve().is_relative_to(directory.resolve()) or sha256(path) != digest:
            raise ValueError('Upstream input mismatch: ' + name)
    if lock['mode'] != file_modes(directory):
        raise ValueError('Upstream file modes changed in transit')
    if lock['policy_sha256'] != policy_hashes():
        raise ValueError('Downstream policy changed; refresh the inputs')
    if lock['build_id'] != identity(lock):
        raise ValueError('Build identity mismatch')
    return lock
