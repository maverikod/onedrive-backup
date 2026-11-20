'''SPA manifest and build cases of the UI-VUE checks: V3 (G5, R23) and V6 (G6, R24).

V3 reads the manifest the DEPLOYED SPA serves (/command-manifest.json) and compares it with the live help of the service. V6 exports the
tracked files of frontend/ into two clean directories, runs npm ci and npm run build in each with a fixed SOURCE_DATE_EPOCH, compares the
file lists and the SHA-256 of every file, scans the artifacts, compares the versions with VERSION and runs the Vitest suite (npm test)
once. Node and npm come from the host PATH; their absence is an ENVIRONMENT finding, never a pass. No value of the run credentials is
ever printed.
'''

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from pipeline import b4base as base, credentials, live
from pipeline.report import Report
from pipeline.vuebase import KEY_MARKERS, ROOT, SECRET_FILES, lan_try, tracked_files

EPOCH = '1700000000'
TYPE_NAMES = {'str': 'string', 'int': 'integer', 'bool': 'boolean', 'float': 'number', 'dict': 'object', 'list': 'array'}
NPM_TIMEOUT = 900
GROUPS = ('auth', 'commands', 'paging', 'polling', 'download', 'error banner', 'no-demo-data')
DESCRIBE = re.compile(r'describe\(\s*[\'"`]([^\'"`]+)')


def _type(value: object) -> str:
    '''Normalized type name of a schema entry (a string, a list of strings or a mapping with type or types).'''
    if isinstance(value, dict):
        value = value.get('type', value.get('types'))
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return TYPE_NAMES.get(str(value).lower(), str(value).lower())


def live_schema(command: str) -> dict:
    '''Parameters the live help documents for one command: name -> specification.'''
    status, decoded = base.rpc('help', {'cmdname': command}, live.token())
    try:
        return dict(decoded['result']['data']['metadata']['parameters'])
    except (KeyError, TypeError, ValueError):
        return {}


def _required(spec: object) -> bool:
    return bool(isinstance(spec, dict) and spec.get('required'))


def manifest_cases(report: Report, root: str) -> None:
    '''V3 (R23): GET /command-manifest.json -> 200 JSON {version, used, not_used}; version == VERSION; used and not_used partition the live help command set; not_used within {backup_download_begin}; every used parameter exists live with the same type and every live required parameter is in the manifest.'''
    got = lan_try(report, 'V3 GET /command-manifest.json', root, 'GET', '/command-manifest.json')
    if got is None:
        return
    if got[0] != 200:
        report.product.append('V3 GET /command-manifest.json: answered %d %s, expected 200 with the SPA command manifest' % (got[0], base.brief(got[2])))
        return
    try:
        manifest = json.loads(got[2])
    except ValueError:
        report.product.append('V3 /command-manifest.json is not JSON: %s' % base.brief(got[2]))
        return
    if not isinstance(manifest, dict) or sorted(manifest) != ['not_used', 'used', 'version']:
        report.product.append('V3 the manifest keys are %s, expected exactly version, used, not_used' % (sorted(manifest) if isinstance(manifest, dict) else type(manifest).__name__))
        return
    if manifest['version'] != base.version():
        report.product.append('V3 manifest version %r, expected the VERSION file content %r' % (manifest['version'], base.version()))
    used, unused = manifest['used'], manifest['not_used']
    if not isinstance(used, dict) or not isinstance(unused, list):
        report.product.append('V3 manifest used must be an object and not_used a list')
        return
    try:
        names = base.live_commands()
    except live.LiveUnreachable as exc:
        report.env.append('V3 live help: not executed, the service is unreachable: %s' % exc)
        return
    if set(used) | set(unused) != set(names) or set(used) & set(unused):
        report.product.append('V3 used %s and not_used %s do not partition the live help commands %s (missing %s, unexpected %s, in both %s)'
                              % (sorted(used), sorted(unused), names, sorted(set(names) - set(used) - set(unused)), sorted((set(used) | set(unused)) - set(names)), sorted(set(used) & set(unused))))
    if not set(unused) <= {'backup_download_begin'}:
        report.product.append('V3 not_used holds %s, only backup_download_begin may be unused' % sorted(set(unused) - {'backup_download_begin'}))
    for command, params in sorted(used.items()):
        schema = live_schema(command)
        for name, spec in (params if isinstance(params, dict) else {}).items():
            if name not in schema:
                report.product.append('V3 manifest %s sends the parameter %s, which the live schema does not accept (%s)' % (command, name, sorted(schema)))
            elif _type(spec) != _type(schema[name]):
                report.product.append('V3 manifest %s.%s has the type %s, the live schema has %s' % (command, name, _type(spec), _type(schema[name])))
        absent = sorted(name for name, spec in schema.items() if _required(spec) and name not in (params if isinstance(params, dict) else {}))
        if absent:
            report.product.append('V3 manifest %s omits the live required parameter(s) %s' % (command, absent))


def _export(target: Path) -> list[str]:
    '''Copy the tracked files of frontend/ (working tree content) into target; return the relative names.'''
    names = [item for item in (tracked_files() or []) if item.startswith('frontend/')]
    for item in names:
        dest = target / item
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / item, dest)
    return names


def _npm(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, SOURCE_DATE_EPOCH=EPOCH, CI='1')
    return subprocess.run(['npm'] + args, cwd=cwd, env=env, capture_output=True, text=True, timeout=NPM_TIMEOUT)


def _tail(text: str) -> str:
    for secret in (item for item in credentials.secret_values() if item):
        text = text.replace(secret, '<value>')
    return text.strip()[-300:]


def _digests(dist: Path) -> dict[str, str]:
    return {str(p.relative_to(dist)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(dist.rglob('*')) if p.is_file()}


def _artifacts(report: Report, dist: Path, digests: dict[str, str]) -> None:
    '''V6 artifacts: no key, certificate or env file, no private-key marker, no run credential, no sourcemap source under /home or /root.'''
    secrets = [item for item in credentials.secret_values() if item]
    for name in digests:
        path = dist / name
        if Path(name).name.lower() == '.env' or name.lower().endswith(SECRET_FILES[1:]):
            report.product.append('V6 artifact %s is a secret, key or certificate file' % name)
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        if any(marker in text for marker in KEY_MARKERS):
            report.product.append('V6 artifact %s holds a private key marker' % name)
        if any(value in text for value in secrets):
            report.product.append('V6 artifact %s holds the run password' % name)
        if name.endswith('.map') and re.search(r'"/(home|root)/', text):
            report.product.append('V6 artifact %s names an absolute home path in its sources' % name)


def build_cases(report: Report) -> None:
    '''V6 (R24, G6): two clean builds are identical, the artifacts are clean, the versions equal VERSION, npm test exits 0 and the required Vitest groups exist.'''
    version_file = ROOT / 'frontend' / '.node-version'
    if shutil.which('node') is None or shutil.which('npm') is None:
        report.env.append('V6 build: node and npm are not on PATH, the reproducibility, version and Vitest cases cannot run (Node 22 on the host)')
        return
    wanted = version_file.read_text(encoding='utf-8').strip().lstrip('v').split('.')[0] if version_file.is_file() else None
    have = subprocess.run(['node', '-v'], capture_output=True, text=True).stdout.strip().lstrip('v').split('.')[0]
    if wanted and have != wanted:
        report.env.append('V6 build: node major %s on PATH, frontend/.node-version pins %s' % (have, wanted))
        return
    if not (ROOT / 'frontend' / 'package.json').is_file():
        report.product.append('V6 build: frontend/package.json does not exist, nothing to build')
        return
    digests = []
    with tempfile.TemporaryDirectory(prefix='vue-build-') as work:
        for number in (1, 2):
            tree = Path(work) / ('b%d' % number)
            _export(tree)
            site = tree / 'frontend'
            for args in (['ci'], ['run', 'build']):
                done = _npm(args, site)
                if done.returncode != 0:
                    report.product.append('V6 build %d: npm %s exited %d: %s' % (number, ' '.join(args), done.returncode, _tail(done.stdout + done.stderr)))
                    return
            if number == 1:
                tested = _npm(['test'], site)
                if tested.returncode != 0:
                    report.product.append('V6 npm test (vitest run) exited %d: %s' % (tested.returncode, _tail(tested.stdout + tested.stderr)))
            digests.append(_digests(site / 'dist'))
            if number == 1:
                _artifacts(report, site / 'dist', digests[0])
                manifest = site / 'dist' / 'command-manifest.json'
                shown = json.loads(manifest.read_text(encoding='utf-8')).get('version') if manifest.is_file() else None
                lock = json.loads((site / 'package-lock.json').read_text(encoding='utf-8')) if (site / 'package-lock.json').is_file() else {}
                for label, value in (('dist/command-manifest.json', shown), ('package-lock.json', lock.get('version')), ('package-lock.json packages[""]', lock.get('packages', {}).get('', {}).get('version'))):
                    if value != base.version():
                        report.product.append('V6 %s: version %r, expected the VERSION file content %r' % (label, value, base.version()))
    if digests and digests[0] != digests[1]:
        differ = sorted(set(digests[0]) ^ set(digests[1]) | {n for n in set(digests[0]) & set(digests[1]) if digests[0][n] != digests[1][n]})
        report.product.append('V6 two builds of the same source differ: %s (the build must be reproducible: same file list and SHA-256 per file)' % differ[:8])
    names = ' '.join(DESCRIBE.findall(' '.join((ROOT / item).read_text(encoding='utf-8', errors='replace') for item in (tracked_files() or [])
                                                if item.startswith('frontend/') and re.search(r'\.(test|spec)\.[jt]s$', item)))).lower()
    absent = [group for group in GROUPS if group not in names]
    if absent:
        report.product.append('V6 the Vitest groups %s are missing (required: %s)' % (absent, list(GROUPS)))
