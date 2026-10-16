#!/usr/bin/env python3
"""Keep signing material out of command arguments, logs, and build context."""
import os
from pathlib import Path
import subprocess

target = Path('build/keys/werewolf-packages.rsa')
target.parent.mkdir(parents=True, exist_ok=True)
value = os.environ.pop('PHP_APK_SIGNING_KEY', '')
if value:
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        # Melange requires PKCS#1; OpenSSL 3 defaults to PKCS#8.
        subprocess.run(['openssl', 'rsa', '-traditional', '-passin', 'pass:'],
                       input=value, text=True, stdout=output,
                       stderr=subprocess.PIPE, check=True)
    with Path(str(target) + '.pub').open('wb') as output:
        subprocess.run(['openssl', 'rsa', '-in', str(target), '-pubout'], stdout=output, check=True)
elif target.exists():
    assert Path(str(target) + '.pub').is_file(), 'Existing signing key has no public key'
    target.chmod(0o600)
else:
    subprocess.run([os.environ.get('MELANGE', 'melange'), 'keygen', str(target)], check=True)
    target.chmod(0o600)
    print('Ephemeral CI signing key; artifacts require explicit trust and are not production releases')

if value:
    if Path(str(target) + '.pub').read_bytes() != Path('release/packages.pub').read_bytes():
        raise SystemExit('Signing key does not match Werewolf APK trust root')
