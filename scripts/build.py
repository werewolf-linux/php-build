#!/usr/bin/env python3
"""Build and test the derived recipe with Melange: bubblewrap on Linux, QEMU elsewhere."""
import argparse
import fcntl
import functools
import hashlib
import http.server
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import threading

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--arch', default=platform.machine())
parser.add_argument('--test-only', action='store_true', help='rerun package tests against existing signed APKs')
args = parser.parse_args()
arch = {'arm64': 'aarch64', 'aarch64': 'aarch64', 'x86_64': 'x86_64'}[args.arch]
os.chdir(ROOT)
melange = os.environ.get('MELANGE', 'melange')
version = json.loads((ROOT / 'tools.lock.json').read_text())['melange']['version']
if f'v{version}' not in subprocess.check_output([melange, 'version'], text=True):
    raise SystemExit(f'Install pinned Melange v{version} with scripts/install-melange.py')
runner = 'bubblewrap' if platform.system() == 'Linux' and shutil.which('bwrap') else 'qemu'
scratch = ROOT / 'build/runner'
scratch.mkdir(parents=True, exist_ok=True)
env = os.environ.copy()
env['TMPDIR'] = str(scratch)
manifest = {'runner': runner, 'arch': arch, 'melange_version': version}

def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()

if runner == 'bubblewrap':
    manifest['kernel'] = platform.release()
    executable = Path(shutil.which('bwrap')).resolve()
    manifest['bubblewrap_sha256'] = sha256(executable)
    profile = executable.with_suffix('.apparmor')
    if profile.is_file():
        manifest['apparmor_profile_sha256'] = sha256(profile)

with (scratch / 'lock').open('w') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    if runner == 'qemu':
        build = os.environ.get('WEREWOLF_BUILD')
        if not build:
            raise SystemExit('Set WEREWOLF_BUILD to a Werewolf build/ARCH holding vmlinuz')
        kernel = Path(build).resolve() / 'vmlinuz'
        if not kernel.is_file():
            raise SystemExit(f'{kernel}: no kernel; build one in werewolf first')
        guest = scratch / f'guest-{arch}.cpio'
        # Always regenerate with the pinned Melange, rather than reuse a guest
        # another version of Melange made. Werewolf's kernel has no modules.
        subprocess.run([melange, 'initramfs', '--arch', arch, '--output', str(guest)], check=True, env=env)
        env.pop('QEMU_KERNEL_MODULES', None)
        env['QEMU_KERNEL_IMAGE'] = str(kernel)
        env['QEMU_BASE_INITRAMFS'] = str(guest)
        env['QEMU_DISKS_PATH'] = str(scratch)
        for name, path in [('kernel', kernel), ('guest', guest)]:
            manifest[name + '_sha256'] = sha256(path)
    packages = ROOT / 'build/packages'
    packages.mkdir(parents=True, exist_ok=True)
    provenance = 'test-runner.json' if args.test_only else 'runner.json'
    (packages / provenance).write_text(json.dumps(manifest, indent=2) + '\n')
    common = ['--runner', runner, '--arch', arch, '--cpu', env.get('MELANGE_CPU', '4'),
              '--memory', env.get('MELANGE_MEMORY', '8Gi')]
    if not args.test_only:
        subprocess.run([melange, 'build', 'build/php.yaml', *common, '--source-dir', 'build/context',
                        '--namespace', 'werewolf', '--pipeline-dir', 'build/inputs/pipelines',
                        '--repository-append', 'https://packages.wolfi.dev/os',
                        '--keyring-append', 'build/inputs/wolfi-signing.rsa.pub',
                        '--signing-key', 'build/keys/werewolf-packages.rsa',
                        '--cache-dir', str(scratch / 'cache'), '--out-dir', str(packages)], check=True, env=env)
    # Package tests are a separate Melange command and self-contained: the
    # probe is in the recipe. They install from the signed local index, which
    # QEMU reaches through its user-network gateway.
    test_context = ROOT / 'build/test-context'
    test_context.mkdir(exist_ok=True)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(packages))
    with http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host = '10.0.2.2' if runner == 'qemu' else '127.0.0.1'
        try:
            subprocess.run([melange, 'test', 'build/php.yaml', *common, '--source-dir', str(test_context),
                            '--pipeline-dirs', 'build/inputs/pipelines', '--test-package-append', 'busybox',
                            '--repository-append', f'http://{host}:{server.server_address[1]}',
                            '--repository-append', 'https://packages.wolfi.dev/os',
                            '--keyring-append', 'build/keys/werewolf-packages.rsa.pub',
                            '--keyring-append', 'build/inputs/wolfi-signing.rsa.pub'], check=True, env=env)
        finally:
            server.shutdown()
            thread.join()
