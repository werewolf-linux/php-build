#!/usr/bin/env python3
"""Fetch only the locked php-src commit, with bounded retries."""
import argparse
from pathlib import Path
import re
import subprocess
import time

SOURCES = ('https://github.com/php/php-src.git',)
BACKOFF = (0, 15, 45)


def checkout(destination, commit, sources=SOURCES):
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('Source commit must be an exact SHA-1')
    if (destination / '.git').exists() or (destination / '.git').is_symlink():
        raise ValueError('Refusing to modify an existing Git checkout')
    destination.mkdir(parents=True, exist_ok=True)

    def git(*args, timeout=30):
        return subprocess.run(['git', '-c', 'core.hooksPath=/dev/null',
                               '-c', 'fetch.fsckObjects=true', '-C', str(destination), *args],
                              check=True, capture_output=True, text=True, timeout=timeout).stdout.strip()

    git('init')
    for delay in BACKOFF:
        if delay:
            time.sleep(delay)
        for source in sources:
            print('source: fetching ' + commit + ' from ' + source, flush=True)
            try:
                git('fetch', '--no-tags', '--depth=1', source, commit, timeout=300)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                print('source: fetch failed: ' + str(error), flush=True)
                if error.stderr:
                    detail = error.stderr.decode(errors='replace') if isinstance(error.stderr, bytes) else error.stderr
                    print('source: ' + detail[-1000:].strip(), flush=True)
                continue
            if git('rev-parse', 'FETCH_HEAD') != commit:
                raise ValueError('Fetched source differs from the locked commit')
            git('checkout', '--detach', commit)
            print('source: verified ' + commit, flush=True)
            return
    raise RuntimeError('Source fetch failed after bounded retries for the locked commit')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('commit')
    args = parser.parse_args()
    checkout(args.destination, args.commit)


if __name__ == '__main__':
    main()
