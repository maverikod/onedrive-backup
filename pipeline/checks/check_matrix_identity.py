'''matrix_identity: pipeline/matrix.yaml carries the recorded identity of the project matrix TODO.

Mode: recorded. The pipeline cannot reach the Plan Manager, so the identity written into the
snapshot is validated for shape and against the project id recorded in CLAUDE.md. The snapshot
stores the TODO updated_at and the SHA-256 of the TODO description it was materialized from, so a
live comparison is possible from outside the pipeline.
'''

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from pipeline import matrix
from pipeline.checks import CheckFailure

ROOT = Path(__file__).resolve().parents[2]
UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
SHA256 = re.compile(r'^[0-9a-f]{64}$')
RECORDED_PROJECT = re.compile(r'CAS project ID: ([0-9a-f-]{36})')


def run() -> None:
    try:
        data = matrix.load()
    except (OSError, ValueError) as exc:
        raise CheckFailure('pipeline/matrix.yaml cannot be loaded: %s' % exc)
    ident = data.get('identity')
    if not isinstance(ident, dict):
        raise CheckFailure('pipeline/matrix.yaml has no identity block')
    problems: list[str] = []
    for key in ('project_id', 'matrix_todo_id'):
        if not UUID.match(str(ident.get(key, ''))):
            problems.append('identity.%s is not a lowercase uuid: %r' % (key, ident.get(key)))
    if ident.get('project_name') != 'onedrive-backup':
        problems.append('identity.project_name must be onedrive-backup, got %r' % ident.get('project_name'))
    anchor = ident.get('matrix_todo_anchor') or {}
    if anchor.get('type') != 'project' or anchor.get('project_id') != ident.get('project_id'):
        problems.append('identity.matrix_todo_anchor must be the project anchor of identity.project_id')
    try:
        datetime.fromisoformat(str(ident.get('matrix_todo_updated_at')))
    except ValueError:
        problems.append('identity.matrix_todo_updated_at is not an ISO timestamp: %r'
                        % ident.get('matrix_todo_updated_at'))
    if not SHA256.match(str(ident.get('matrix_todo_description_sha256', ''))):
        problems.append('identity.matrix_todo_description_sha256 is not a sha256 hex digest')
    if ident.get('plan_id') is not None or ident.get('plan_revision') is not None:
        problems.append('the project has no plan: identity.plan_id and plan_revision must be null')
    if ident.get('comparison_mode') != 'recorded':
        problems.append('identity.comparison_mode must be recorded')
    approval = ident.get('user_approval') or {}
    if not approval.get('date') or not approval.get('quote'):
        problems.append('identity.user_approval must record the date and the quote of the user approval')
    try:
        recorded = RECORDED_PROJECT.search((ROOT / 'CLAUDE.md').read_text(encoding='utf-8'))
    except OSError as exc:
        recorded = None
        problems.append('CLAUDE.md cannot be read: %s' % exc)
    if recorded and recorded.group(1) != ident.get('project_id'):
        problems.append('identity.project_id %s differs from the project id %s recorded in CLAUDE.md'
                        % (ident.get('project_id'), recorded.group(1)))
    if recorded is None and not problems:
        problems.append('CLAUDE.md records no CAS project ID')
    if problems:
        raise CheckFailure('%d violation(s):\n  - %s' % (len(problems), '\n  - '.join(problems)))
