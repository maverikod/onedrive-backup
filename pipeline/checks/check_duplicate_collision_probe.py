'''duplicate_collision_probe: probe P1 and the product grouping of row BE2 (matrix TODO 10.17.11 (1), 10.17.14 CONDITION).

Mode: live, read-only, against the deployed container. Part 1 repeats probe P1 on the folder of the two collision groups of library 1:
`docker exec <container> rclone --config <config> --onedrive-drive-id <drive_id> --onedrive-drive-type documentLibrary lsjson
--files-only --hash --no-mimetype onedrive:<folder>` (the read-only builder of rclone_remote_access; no file content, no secret) and
compares the groups, names, item ids and the rule (10.17.2 (a)-(d)) with pipeline/probe_p1.json. A group whose names differ in
extension, or a rule other than (b), contradicts 10.17.2: STOP and the revision returns to the user (reported as STATE).
Part 2 feeds the live names, ids and sizes to the REAL backup_libraries over the stub rclone of pipeline.dupbox and compares the
service-side grouping (the duplicates of the run record) with the probe: every member except the first listed one is an extra.
Findings: PRODUCT when the service has no grouping equal to the probe, STATE when the library no longer holds the probed groups,
ENVIRONMENT when docker, the service or the data file cannot be used.
'''

from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from typing import Any

from pipeline import dupprobe, live
from pipeline.checks import check_rclone_remote_access as rra
from pipeline.dupbox import DupBox, Item, key
from pipeline.dupcheck import D1, entry, extras_of, start
from pipeline.report import Report


def live_rows(report: Report, data: dict[str, Any]) -> list[dict[str, Any]] | None:
    '''The live folder listing of probe P1, or None after a finding.'''
    container = rra.container_name()
    settings = json.loads((rra.ROOT / 'config' / 'backup.json').read_text(encoding='utf-8'))
    config, remote = str(settings['rclone_config']), str(settings['onedrive_remote'])
    drive = data['library']['drive_id']
    libraries = rra.inventory(report)
    if libraries is None:
        return None
    if drive not in {item[1] for item in libraries}:
        report.state.append('library 1 (drive_id %s) is not in the discovery inventory: probe P1 cannot be repeated' % drive)
        return None
    argv = rra._argv(container, config, 'lsjson', [remote + data['folder'], '--files-only', '--hash', '--no-mimetype'], drive)
    done: subprocess.CompletedProcess[str] = rra._run(argv)
    if done.returncode != 0:
        report.env.append('probe P1 lsjson exited %d: %s' % (done.returncode, rra.redact(done.stderr or done.stdout)))
        return None
    try:
        rows = json.loads(done.stdout)
    except ValueError:
        rows = None
    if not isinstance(rows, list):
        report.env.append('probe P1 lsjson printed no JSON list: %s' % rra.redact(done.stdout))
        return None
    return [row for row in rows if isinstance(row, dict)]


def probe_part(report: Report, data: dict[str, Any], rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    '''Compare the live groups with the record and the rule; return the live groups (members in listing order).'''
    found: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        found[key(str(row['Name']))].append(row)
    groups = [members for members in found.values() if len(members) > 1]
    live_ids = {str(row['ID']).split('#', 1)[1]: str(row['Name']) for members in groups for row in members}
    if live_ids != dupprobe.group_ids(data):
        report.state.append('the collision groups of the folder differ from probe P1: live %s, recorded %s' % (sorted(live_ids.items()), sorted(dupprobe.group_ids(data).items())))
    for members in groups:
        names = [str(row['Name']) for row in members]
        found_rule = dupprobe.rule_of(names)
        if found_rule != data['rule'] or len({dupprobe.extension(name) for name in names}) != 1:
            report.state.append('P1 CONTRADICTS 10.17.2: the group %s obeys rule (%s) and its extensions are %s; recorded rule (%s); STOP, the revision returns to the user'
                                % (ascii(names), found_rule, sorted({dupprobe.extension(name) for name in names}), data['rule']))
    report.info.append('probe P1 live: %d entries in the folder, %d collision group(s), rule (%s), ids %s' % (len(rows), len(groups), data['rule'], sorted(live_ids)))
    return groups


def product_part(report: Report, groups: list[list[dict[str, Any]]], folder: str) -> None:
    '''The real backup_libraries over the probed names and ids must report every non-first member of every group as an extra.'''
    label, box = 'BE2 probe grouping (the service-side grouping that probe P1 is compared with)', DupBox()
    try:
        items = [Item(folder + '/' + str(row['Name']), str(row['ID']).split('#', 1)[1], ('probe content of ' + str(row['ID'])).encode())
                 for members in groups for row in members]
        box.drive(D1, *items)
        value, _ = start(report, label, box, [D1])
        found = entry(report, label, value, D1)
        if found is None:
            return
        wanted = {(str(row['ID']).split('#', 1)[1], str(row['Name'])) for members in groups for row in members[1:]}
        got = {(row.get('item_id'), row.get('name')) for row in extras_of(found) or []}
        if got != wanted:
            report.product.append('%s: the service-side extras %s differ from the probe %s' % (label, sorted(got, key=str), sorted(wanted)))
    finally:
        box.close()


def run() -> None:
    '''Raise CheckFailure when probe P1 is contradicted or the service grouping differs from it.'''
    report = Report()
    try:
        data = dupprobe.load()
        rows = live_rows(report, data)
        if rows is not None:
            groups = probe_part(report, data, rows)
            product_part(report, groups, data['folder'])
    except live.LiveUnreachable as exc:
        report.env.append('the service cannot be used for the inventory: %s' % rra.redact(str(exc)))
    except rra.DockerUnavailable as exc:
        report.env.append(str(exc))
    except (OSError, ValueError, KeyError) as exc:
        report.env.append('probe P1 inputs cannot be used: %s: %s' % (type(exc).__name__, rra.redact(str(exc))))
    report.finish('duplicate_collision_probe')
