'''backup_duplicate_names: rows BE2 and BE3, collision detection and keep-both storage (matrix TODO 10.17, block DUP-KEEP-REV10).

Mode: stub-isolated over the REAL onedrive_api.sharepoint_backup.backup_libraries (pipeline.dupbox): a temporary data directory,
a stub rclone (lsjson with ids and hashes, sync with exclude protection, hashsum), a stub restic and a stub Graph content endpoint
in this process, no network, no production state. A control proves the sandbox with a library that has no collision. Cases of 10.17.10:
BE2 no_collision, pair_same_name_group, pair_case_or_nfc_group, three_member_group, primary_by_hash, primary_by_smallest_id_tie,
reserved_name_in_source, scan_failure, duplicate_directory_unsupported; BE3 extra_stored_and_snapshotted, name_stable_across_runs,
name_clash_extends_hex, rerun_no_refetch, sync_does_not_delete_stored_copy, integrity_hash_mismatch_kept_and_error,
hash_unavailable_size_checked, fetch_failure_no_file_and_error, dry_run_writes_nothing, source_object_never_written.
User decisions 2026-11-20 (10.17.14): keep both copies, suffix <stem>.dup-<h8><ext>, ok plus WARNING for kept copies, strict integrity.
'''

from __future__ import annotations

from pipeline import dupcases2, dupcases3, dupcheck
from pipeline.report import Report


def run() -> None:
    '''Raise CheckFailure when the backup cycle does not keep both objects of a collision group as 10.17 requires.'''
    report = Report()
    dupcheck.control(report)
    dupcases2.run_all(report)
    dupcases3.run_all(report)
    report.info.append('isolation: temporary directory under .test-run only; stub rclone, restic and Graph in this process, subprocess refused, '
                       'host paths and network never reached; the quickXorHash is the real algorithm')
    report.finish('backup_duplicate_names')
