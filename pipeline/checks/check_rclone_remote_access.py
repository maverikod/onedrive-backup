'''rclone_remote_access: the rclone of the DEPLOYED container reaches every library of the discovery inventory (row RC1, bug 68fc1822).

Mode: live, against the deployed container. The container name is the host of ONEDRIVE_BACKUP_URL in pipeline/endpoints.env, the
same name binding that pipeline.environment resolves with docker inspect; nothing is hardcoded. Two assertions:
  (a) `rclone version` inside the container reports at least MIN_VERSION. Source of the minimum: the rclone changelog, release
      v1.69.0 (2025-01-12), Onedrive section, "Add support for OAuth client credential flow" (https://rclone.org/changelog/), and the
      option --onedrive-client-credentials in https://rclone.org/onedrive/. The deployed rclone.conf is app-only client_credentials.
  (b) for EVERY library of the current discovery inventory (backup_sites_list, then backup_libraries_list per site) the read-only
      `rclone lsjson onedrive: --max-depth 1` with the deployed rclone config and that library drive id exits 0 and prints a JSON list
      (an empty library prints []).
Read-only by construction: only the rclone sub-commands in READ_ONLY are ever built (guarded in _argv), rclone.conf is never read or
printed, every printed rclone text is redacted. Findings: PRODUCT when the container rclone cannot do what the backup needs, STATE
when the inventory is not ready, ENVIRONMENT when docker or the service cannot be used from this run.
'''

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from pipeline import credentials, live
from pipeline.report import Report

ROOT = Path(__file__).resolve().parents[2]
MIN_VERSION = (1, 69, 0)
READ_ONLY = ('version', 'lsjson')
VERSION_LINE = re.compile(r'^rclone v(\d+)[.](\d+)[.](\d+)')
SECRET_TEXT = re.compile(r'(?i)\b(token|secret|password|authorization|client_id|client_secret)(\s*[=:]\s*)[^\s"\x27,;]+')
PAGE = 1000
TIMEOUT = 180


class DockerUnavailable(RuntimeError):
    '''docker cannot be run, or the container is not running, from this pipeline run (environment RED).'''


def redact(text: str) -> str:
    '''Return text on one line, without any secret form of the run credentials or a token-looking assignment, at most 300 chars.'''
    for value in credentials.secret_values():
        if value:
            text = text.replace(value, '<redacted>')
    return SECRET_TEXT.sub(lambda found: found.group(1) + found.group(2) + '<redacted>', ' '.join(text.split()))[:300]


def _argv(container: str, config: str, sub: str, tail: list[str], drive: str | None = None) -> list[str]:
    '''Build `docker exec <container> rclone --config <config> [drive selection] <sub> ...`; only read-only sub-commands are built.'''
    if sub not in READ_ONLY:
        raise ValueError('rclone sub-command %r is not read-only; allowed: %s' % (sub, READ_ONLY))
    selection = ['--onedrive-drive-id', drive, '--onedrive-drive-type', 'documentLibrary'] if drive else []
    return ['docker', 'exec', container, 'rclone', '--config', config] + selection + [sub] + tail


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        raise DockerUnavailable('%s cannot be run: %s: %s' % (argv[0], type(exc).__name__, redact(str(exc))))


def container_name() -> str:
    '''Return the container name: the host of the service URL of pipeline/endpoints.env.'''
    name = urlparse(live.base_url()).hostname
    if not name:
        raise live.LiveUnreachable('the service URL names no host, so no container can be bound')
    return name


def _pages(command: str, params: dict, report: Report, label: str) -> list[dict] | None:
    '''Return every item of a paged inventory command, or None after a STATE finding.'''
    items: list[dict] = []
    offset = 0
    while True:
        kind, code, message, data = live.request(command, dict(params, limit=PAGE, offset=offset))
        if kind != 'success' or not isinstance(data, dict) or not isinstance(data.get('items'), list):
            report.state.append('%s: the discovery inventory cannot be read (%s %s %s); the check needs a finished inventory'
                                % (label, kind, code, redact(str(message))))
            return None
        page = [item for item in data['items'] if isinstance(item, dict)]
        items += page
        offset += len(data['items'])
        if not data['items'] or offset >= int(data.get('total') or 0):
            return items


def inventory(report: Report) -> list[tuple[str, str]] | None:
    '''Return [(site_id, drive_id)] of the current discovery inventory, or None after a STATE finding.'''
    sites = _pages('backup_sites_list', {}, report, 'backup_sites_list')
    if sites is None:
        return None
    libraries: list[tuple[str, str]] = []
    for site in sorted({str(item['site_id']) for item in sites if item.get('site_id')}):
        found = _pages('backup_libraries_list', {'site_id': site}, report, 'backup_libraries_list site_id=' + site)
        if found is None:
            return None
        libraries += [(site, str(item['drive_id'])) for item in found if item.get('drive_id')]
    if not libraries:
        report.state.append('the discovery inventory lists no document library: there is nothing to reach with rclone')
        return None
    return libraries


def _running(container: str) -> None:
    done = _run(['docker', 'inspect', '--type', 'container', '--format', '{{.State.Running}}', container])
    if done.returncode != 0 or done.stdout.strip() != 'true':
        raise DockerUnavailable('container %s is not running (docker inspect exit %d: %s)'
                                % (container, done.returncode, redact(done.stdout + done.stderr)))


def _version(report: Report, container: str, config: str) -> None:
    argv = _argv(container, config, 'version', [])
    done = _run(argv)
    first = done.stdout.splitlines()[0] if done.stdout.strip() else ''
    if done.returncode != 0:
        report.product.append('rclone version in the container %s exited %d: %s' % (container, done.returncode, redact(done.stderr)))
        return
    found = VERSION_LINE.match(first)
    if not found:
        report.product.append('rclone version in the container %s printed no version line: %r' % (container, redact(first)))
        return
    have = tuple(int(part) for part in found.groups())
    report.info.append('container rclone version line: %s (minimum %s)' % (redact(first), '.'.join(map(str, MIN_VERSION))))
    if have < MIN_VERSION:
        report.product.append('container rclone is "%s": older than v%s, the first release with the OAuth client credential flow that the app-only'
                              ' rclone.conf (client_credentials, no token key) needs (rclone changelog v1.69.0 2025-01-12, Onedrive)'
                              % (redact(first), '.'.join(map(str, MIN_VERSION))))


def _libraries(report: Report, container: str, config: str, remote: str, libraries: list[tuple[str, str]]) -> None:
    report.info.append('read-only argv per library: docker exec %s rclone --config %s --onedrive-drive-id <drive_id> --onedrive-drive-type'
                       ' documentLibrary lsjson %s --max-depth 1 (rclone.conf is never read or printed)' % (container, config, remote))
    for number, (site, drive) in enumerate(libraries, 1):
        done = _run(_argv(container, config, 'lsjson', [remote, '--max-depth', '1'], drive))
        label = 'library %d/%d site_id=%s drive_id=%s' % (number, len(libraries), site, drive)
        if done.returncode != 0:
            report.product.append('%s: rclone lsjson exited %d: %s' % (label, done.returncode, redact(done.stderr or done.stdout)))
            continue
        try:
            listing = json.loads(done.stdout)
        except ValueError:
            listing = None
        if not isinstance(listing, list):
            report.product.append('%s: rclone lsjson exit 0 but the output is not a JSON list: %s' % (label, redact(done.stdout)))


def run() -> None:
    '''Raise CheckFailure when the container rclone cannot read a library of the inventory.'''
    report = Report()
    try:
        container = container_name()
        settings = json.loads((ROOT / 'config' / 'backup.json').read_text(encoding='utf-8'))
        config, remote = str(settings['rclone_config']), str(settings['onedrive_remote'])
        _running(container)
        _version(report, container, config)
        libraries = inventory(report)
        if libraries is not None:
            _libraries(report, container, config, remote, libraries)
    except live.LiveUnreachable as exc:
        report.env.append('the service cannot be used for the inventory: %s' % redact(str(exc)))
    except DockerUnavailable as exc:
        report.env.append(str(exc))
    except (OSError, ValueError, KeyError) as exc:
        report.env.append('config/backup.json cannot be used: %s' % redact(str(exc)))
    report.finish('rclone_remote_access')
