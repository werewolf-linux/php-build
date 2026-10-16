#!/bin/sh
# probe.sh PROBE holds the installed php to the protections patches/series
# compiles in, then takes each back with an allowance and sees it return.
# The package test runs it as root, with php.ini-production installed and
# /etc/werewolf/allow/php free to use (scripts/derive.py embeds it).
set -eu
probe=$1
allow=/etc/werewolf/allow/php
work=$(mktemp -d)
trap 'rm -rf "$work" "$allow"' EXIT

expect() {
	name=$1
	want=$2
	shift 2
	got=$("$@" 2>"$work/stderr")
	if [ "$got" != "$want" ]; then
		echo "probe: FAIL: $name" >&2
		echo "  want $want" >&2
		echo "  got  $got" >&2
		cat "$work/stderr" >&2
		exit 1
	fi
	echo "probe: ok: $name"
}

closed='{"functions":[],"unserialize":"__PHP_Incomplete_Class","unserialize_all":"__PHP_Incomplete_Class","unserialize_named":"stdClass","phar_wrapper":false,"allow_url_include":false,"opcache_file_cache":"","memory_limit":"128M"}'
rm -rf "$allow"
expect 'closed without allowances' "$closed" php "$probe"

# Neither the environment, php.ini nor argv opens them again.
mkdir "$work/ini"
printf 'memory_limit = 7M\nallow_url_include = 1\ndisable_functions =\n' >"$work/ini/php.ini"
expect 'PHPRC is ignored' "$closed" env PHPRC="$work/ini" php "$probe"
expect 'PHP_INI_SCAN_DIR is ignored' "$closed" env PHP_INI_SCAN_DIR="$work/ini" php "$probe"
expect 'php.ini and argv cannot lift the floor' "$closed" \
	php -d disable_functions= -d allow_url_include=1 -d opcache.file_cache="$work/cache" "$probe"

# Each allowance takes back what it names, and nothing else.
mkdir -p "$allow"
: >"$allow/exec"
: >"$allow/unserialize"
: >"$allow/phar"
expect 'allowances take back exec, unserialize and phar' \
	'{"functions":["exec"],"unserialize":"stdClass","unserialize_all":"stdClass","unserialize_named":"stdClass","phar_wrapper":true,"allow_url_include":false,"opcache_file_cache":"","memory_limit":"128M"}' \
	php "$probe"

# A link is not an allowance, even to a file: lock times will be links.
rm -f "$allow"/*
: >"$work/target"
ln -s "$work/target" "$allow/system"
expect 'a link is not an allowance' "$closed" php "$probe"
