#!/usr/bin/env python3
"""Release notes for a validated build: what it is, what changed, and its evidence.

Pure functions of facts that scripts/publish.py gathers; nothing here reads
the network or the disk, so a release's notes are made once and kept."""
import json
import re

FORMAT = 'php-build-release-notes/1'
SOURCE = 'https://github.com/werewolf-linux/php-build'
DESIGN = 'https://github.com/werewolf-linux/werewolf/blob/main/docs/design/hardened-interpreters.md'
SECDB = 'https://packages.wolfi.dev/os/security.json'
WOLFI = 'https://github.com/wolfi-dev/os'
PHP = 'https://github.com/php/php-src'

def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()

def version_key(version):
    """apk's order for the versions PHP carries (8.5.11-r3), or None."""
    match = re.fullmatch(r'(\d+(?:\.\d+)*)-r(\d+)', version)
    return (tuple(int(x) for x in match.group(1).split('.')), int(match.group(2))) if match else None

def security(secdb, stream, previous, current):
    """Wolfi's advisories for stream fixed in (previous, current], and how many through current."""
    fixes = {}
    for package in secdb['packages']:
        if package['pkg']['name'] == stream:
            fixes = package['pkg'].get('secfixes') or {}
    top, floor = version_key(current), version_key(previous) if previous else None
    window, through = [], []
    for version, ids in sorted(fixes.items(), key=lambda item: version_key(item[0]) or ((), -1)):
        key = version_key(version)
        if key is None or key > top:
            continue
        through.append({'version': version, 'ids': sorted(ids)})
        if floor is not None and key > floor:
            window.append({'version': version, 'ids': sorted(ids)})
    return {'stream': stream, 'previous': previous, 'current': current, 'fixed': window,
            'cumulative': sum(len(x['ids']) for x in through), 'not_affected': len(fixes.get('0', []))}

def build(facts):
    """The notes, as data: facts with what changed worked out."""
    previous = facts['previous']
    made = dict(facts, format=FORMAT)
    made['first'] = previous is None
    if previous is not None:
        made['wolfi_changed'] = previous.get('wolfi_version') != facts['source']['wolfi_version']
        made['php_changed'] = previous.get('php_commit') != facts['source']['php_commit']
    return made

def markdown(made):
    source, previous = made['source'], made['previous']
    lines = ['# PHP ' + made['version'], '',
             "Wolfi's `{}` {} ([wolfi-dev/os@{}]({}/tree/{})), php-src [{}]({}/commit/{}), with the {} "
             'protections of [patches/series]({}/tree/{}/patches) ([design]({})).'.format(
                 source['recipe'], source['wolfi_version'], source['wolfi_commit'][:12], WOLFI,
                 source['wolfi_commit'], source['php_commit'][:12], PHP, source['php_commit'],
                 len(made['patches']), SOURCE, made['commit'], DESIGN), '',
             '- Stable repository: ' + made['repository']['stable'],
             '- This build: ' + made['repository']['snapshot'],
             '- Built by: ' + made['run'], '', '## Changes', '']
    if made['first']:
        lines.append('The first release.')
    else:
        lines.append('Since ' + previous['version'] + ':')
        lines.append('')
        if made['wolfi_changed']:
            lines.append("- Wolfi's build: {} → {}".format(previous.get('wolfi_version') or 'unknown',
                                                            source['wolfi_version']))
        if made['php_changed'] and previous.get('php_commit'):
            lines.append('- php-src: [{}...{}]({}/compare/{}...{})'.format(
                previous['php_commit'][:12], source['php_commit'][:12], PHP,
                previous['php_commit'], source['php_commit']))
        if made['commits'] is None:
            lines.append('- This repository: unavailable (GitHub did not answer)')
        else:
            for commit in made['commits']:
                lines.append('- [{}]({}/commit/{}) {}'.format(commit['sha'][:12], SOURCE, commit['sha'],
                                                               commit['subject']))
            if not made['commits']:
                lines.append('- This repository: unchanged')
    found = made['security']
    lines += ['', '## Security', '']
    if found['fixed']:
        for fix in found['fixed']:
            lines.append("- Wolfi's {}: {}".format(fix['version'], ', '.join(fix['ids'])))
    else:
        lines.append('No advisory Wolfi lists for `{}` was fixed since the previous release.'.format(found['stream']))
    lines.append('')
    lines.append('{} advisories fixed through {}; {} listed as not affecting this stream.'.format(
        found['cumulative'], found['current'], found['not_affected']))
    lines += ['', '## Patches', ''] + ['- `' + name + '`' for name in made['patches']]
    lines += ['', '## Packages', '', '| Package | ' + ' | '.join(made['architectures']) + ' |',
              '| --- |' + ' ---: |' * len(made['architectures'])]
    sizes = {}
    for arch, found_packages in made['architectures'].items():
        for package in found_packages['packages']:
            sizes.setdefault(package['name'], {})[arch] = package['size']
    for name in sorted(sizes):
        lines.append('| ' + name + ' | ' + ' | '.join(
            '{:,}'.format(sizes[name][a]) if a in sizes[name] else '—' for a in made['architectures']) + ' |')
    return '\n'.join(lines) + '\n'
