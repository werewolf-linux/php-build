# php-build

Werewolf's PHP: Wolfi's recipe, captured unchanged, plus seven policy patches
([design](https://github.com/werewolf-linux/werewolf/blob/main/docs/design/hardened-interpreters.md)).
The packages keep Wolfi's names (`php-8.5`, `php-8.5-fpm`, …) and are published, signed
with Werewolf's key, to `https://dist.werewolf-linux.org/apk/php`.

## Differences from Wolfi's build

Same as Wolfi: php-src commit, Wolfi's patches, build environment, configure flags but two,
extensions and package tests.

- **Patches** (`patches/series`), each failing closed on drift:
  1. `PHPRC` and `PHP_INI_SCAN_DIR` are ignored: only the build names configuration.
  2. Allowances are read from `/etc/werewolf/allow/php/NAME`, an empty regular file on the
     image's read-only root; a link is not one. php.ini, argv and the environment allow nothing.
  3. `dl`, `exec`, `passthru`, `pcntl_exec`, `popen`, `proc_open`, `shell_exec` and `system`
     stay disabled whatever php.ini says, unless allowed by name.
  4. `unserialize()` makes objects only of the classes `allowed_classes` names, `true` included,
     unless `unserialize` is allowed; others become `__PHP_Incomplete_Class`.
  5. `allow_url_include=1` is refused, with a warning.
  6. `opcache.file_cache` is refused, with a warning: compiled scripts never come from a
     writable cache.
  7. The `phar://` wrapper is registered only if `phar` is allowed.
- **Removed**: phpdbg (`-dbg`) and PEAR (`-pear`), and the configure flags that build them.
- **Version**: Wolfi's, with epoch 1000 × `policy.json`'s revision + Wolfi's epoch
  (8.5.11-r3 builds 8.5.11-r1003), so apk prefers it over every Wolfi rebuild of the same
  release. Each package provides `wolfi-origin:php-8.5:8.5.11-r3`, by which Werewolf matches
  Wolfi's CVE fixes.
- **Tests**: Wolfi's, and `tests/probe.sh`, which holds the installed PHP to each protection,
  shows php.ini, argv and the environment cannot lift one, and takes each back by allowance.

A form takes one back in `form.yaml` as `allow: [php:proc_open, php:unserialize]`; Werewolf's
build writes `/etc/werewolf/allow/php/proc_open` (`lib/allow.zig` lists the names).

## Building and publishing

`make test` runs the unit tests, offline. `make refresh check derive prepare` captures Wolfi's
recipe for the stream `policy.json` names, verifies it, and applies every patch to the locked
php-src without fuzz; `make build` builds with Melange (macOS: `WEREWOLF_BUILD=../werewolf/build/aarch64`).

CI (`.github/workflows/refresh.yml`) checks Wolfi every ten minutes. Each new Wolfi build is built
on both architectures, tested, and published: a GitHub release `build-ID` named after its version,
an immutable snapshot `builds/ID/`, and the stable repository machines follow.

What stops a new Wolfi build is filed as an issue labelled `drift`
(`scripts/drift.py`), titled with the version and what failed, with the failing output: a patch
that no longer applies, a recipe the derivation no longer recognizes, a recipe that cannot be
captured. A newer PHP stream in Wolfi is filed too; moving `policy.json` to it is a person's
decision. A run that passes again closes them.

Patches are PHP-3.01 and Wolfi inputs keep their license (`LICENSES/`); tooling: `LICENSE`.
