#!/usr/bin/env python3
"""File what stops a Wolfi PHP release building here as a GitHub issue.

usage: drift.py refresh|derivation|patches LOG    a step of the scheduled check failed
       drift.py resolved                         every step passed: close the failures
       drift.py stream                           whether Wolfi builds a newer PHP than policy.json

One open issue per failure, titled by Wolfi's version and what failed, with
the failing output. A run that fails the same way again adds nothing; the
same title failing differently adds a comment. A run that passes closes them."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from inputs import ROOT, INPUTS

LABEL = 'drift'
TAIL = 200          # lines of output kept: the end is where a failure is
LIMIT = 50000       # characters of output kept; GitHub refuses bodies over 65536
ANSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')
NEWER = ROOT / 'build/newer-stream.json'
WHAT = {'refresh': 'capturing the recipe stopped',
        'derivation': 'the derivation stopped',
        'patches': 'a patch no longer applies'}

def gh(*args, input=None):
    return subprocess.run(['gh', *args], check=True, capture_output=True, text=True, input=input).stdout

def output(text):
    """The end of a step's output, as an issue quotes it."""
    lines = ANSI.sub('', text).replace('```', "'''").splitlines()[-TAIL:]
    kept = '\n'.join(lines)
    return kept[-LIMIT:] if len(kept) > LIMIT else kept

def failing_patch(log):
    found = re.search(r'^prepare: (.+?) does not apply$', log, re.M)
    return found.group(1) if found else None

def report(kind, log, lock, stream, run):
    """An issue's title, body and the marker that says the same failure was filed."""
    if kind == 'stream':
        newer = json.loads(log)
        title = 'Wolfi builds PHP {}; policy.json follows {}'.format(newer['newer'][-1], newer['stream'])
        body = ('Wolfi ([{w}](https://github.com/wolfi-dev/os/tree/{w})) now builds PHP {n}. This repository '
                'follows {s}, the stream `policy.json` names: a new minor release changes the language, so '
                'a person moves it, with the forms that use it.\n'.format(
                    w=newer['wolfi_commit'], n=', '.join(newer['newer']), s=newer['stream']))
        return title, body, 'stream:' + ','.join(newer['newer'])
    quoted = output(log)
    if lock is not None:
        version = 'PHP {}-r{}'.format(lock['version'], lock['epoch'])
        facts = ('- Wolfi recipe: `{}` at [wolfi-dev/os@{}](https://github.com/wolfi-dev/os/blob/{}/{})\n'
                 '- php-src: [{}](https://github.com/php/php-src/commit/{})\n'.format(
                     lock['recipe'], lock['wolfi_commit'][:12], lock['wolfi_commit'], lock['recipe'],
                     lock['php_commit'], lock['php_commit']))
    else:
        version, facts = 'PHP ' + stream, '- Wolfi recipe: `php-{}.yaml`, not captured\n'.format(stream)
    patch = failing_patch(log) if kind == 'patches' else None
    title = '{}: {}'.format(version, patch + ' no longer applies' if patch else WHAT[kind])
    body = ('Wolfi\'s {} no longer builds with Werewolf\'s protections: {}. Werewolf publishes no PHP build '
            'from this recipe until it is fixed.\n\n{}{}\n```\n{}\n```\n'.format(
                version, patch + ' does not apply' if patch else WHAT[kind], facts,
                '- Run: ' + run + '\n' if run else '', quoted))
    return title, body, kind + ':' + hashlib.sha256((title + '\n' + quoted).encode()).hexdigest()[:16]

FAILED = 'PHP '              # titles of what stopped a release (report)
STREAM = 'Wolfi builds PHP '  # titles of a newer stream (report)

def open_issues(run):
    run('label', 'create', LABEL, '--color', 'B60205', '--force',
        '--description', 'A Wolfi release no longer builds with these protections')
    return json.loads(run('issue', 'list', '--label', LABEL, '--state', 'open',
                          '--json', 'number,title', '--limit', '200'))

def resolve(prefix, comment, run=gh):
    """Close each open issue whose title starts with prefix; return their numbers."""
    closed = []
    for issue in open_issues(run):
        if issue['title'].startswith(prefix):
            run('issue', 'close', str(issue['number']), '--comment', comment)
            closed.append(issue['number'])
    return closed

def file(title, body, marker, run=gh):
    """Open the issue, comment on the open one a different failure has, or do nothing."""
    tag = '<!-- drift ' + marker + ' -->'
    issues = open_issues(run)
    with tempfile.TemporaryDirectory() as directory:
        text = Path(directory) / 'body.md'
        text.write_text(body + '\n' + tag + '\n')
        for issue in issues:
            if issue['title'] != title:
                continue
            seen = json.loads(run('issue', 'view', str(issue['number']), '--json', 'body,comments'))
            if tag in seen['body'] or any(tag in c['body'] for c in seen['comments']):
                return 'unchanged', issue['number']
            run('issue', 'comment', str(issue['number']), '--body-file', str(text))
            return 'commented', issue['number']
        created = run('issue', 'create', '--title', title, '--label', LABEL, '--body-file', str(text))
    return 'opened', created.strip()

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('kind', choices=['refresh', 'derivation', 'patches', 'resolved', 'stream'])
    parser.add_argument('log', nargs='?', type=Path)
    args = parser.parse_args()
    run = None
    if os.environ.get('GITHUB_RUN_ID'):
        run = '{}/{}/actions/runs/{}'.format(os.environ.get('GITHUB_SERVER_URL', 'https://github.com'),
                                             os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_RUN_ID'])
    if args.kind == 'resolved':
        lock = json.loads((INPUTS / 'upstream.lock.json').read_text())
        closed = resolve(FAILED, "Wolfi's PHP {}-r{} builds with these protections again{}.".format(
            lock['version'], lock['epoch'], ': ' + run if run else ''))
        print('drift: closed', closed or 'nothing')
        return
    if args.kind == 'stream':
        if not NEWER.is_file():
            stream = json.loads((ROOT / 'policy.json').read_text())['stream']
            closed = resolve(STREAM, 'policy.json follows PHP {}, the newest Wolfi builds.'.format(stream))
            print('drift: closed', closed or 'nothing')
            return
        log = NEWER.read_text()
    elif args.log is None:
        parser.error(args.kind + ' needs the failed step\'s output')
    else:
        log = args.log.read_text(errors='replace') if args.log.is_file() else '(the step wrote no output)'
    path = INPUTS / 'upstream.lock.json'
    lock = json.loads(path.read_text()) if args.kind != 'refresh' and path.is_file() else None
    stream = json.loads((ROOT / 'policy.json').read_text())['stream']
    title, body, marker = report(args.kind, log, lock, stream, run)
    result, issue = file(title, body, marker)
    print('drift:', result, issue, '-', title)

if __name__ == '__main__':
    main()
