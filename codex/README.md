# onedrive-backup Codex prompt package

`../AGENTS.md` is the entrypoint. This directory contains the project-bound
Codex contract bundle generated from `templates/codex/v1.7.88` by `scripts/bind_bundles.py`.

Package version: `v1.7.88`

## Layout

- `roles/common.yaml` and `roles/triggers.yaml`: the only orchestrator startup reads.
- `modes.yaml`: event-loaded mode semantics with no routing authority; forbidden at orchestrator startup.
- `roles/*.yaml`: event-loaded law and stage contracts.
- `ops/*.yaml`: lazily loaded operating cards (delivery, testing, CAS, doc-store, model selection).
- `VERSION`: bundle version marker.

## Project bindings

- Project: `onedrive-backup`
- Local checkout: `/home/vasilyvz/projects/tools/onedrive-backup`
- Deployment host: `root@192.168.254.26`
- CAS project ID: `f6130c8b-1fde-4a35-bdae-e857dfbd6555`
- CAS server: `code-analysis-server-vvz`

## Notes

- This bundle is Codex-only; the other runtime's files are not modified by it.
- Relative bundle references resolve from `codex/`.
- Project-specific laws live after the marker at the end of `roles/laws.yaml`; project-specific entrypoint sections after the marker at the end of the entrypoint. Everything else is regenerated from the template.
