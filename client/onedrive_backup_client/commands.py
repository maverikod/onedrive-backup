'''One method per server command of the OneDrive Backup service, shared by the client class (BackupClient).'''

from __future__ import annotations

from typing import Any, Optional


class CommandMethods:
    '''The command methods; a method sends its keyword arguments unchanged and leaves an omitted option out.'''

    def call(self, command: str, params: Optional[dict] = None) -> Any:
        '''Run any registered command; implemented by the client class.

        Args:
            command: The command name.
            params: The parameter map or None.

        Returns:
            The data of the command result.
        '''
        raise NotImplementedError

    def _command(self, command: str, **params: Any) -> Any:
        '''Run a command with the parameters that are not None.

        Args:
            command: The command name.
            params: The candidate parameters; None means omitted.

        Returns:
            The data of the command result.
        '''
        return self.call(command, {k: v for k, v in params.items() if v is not None})

    def schedule_get(self, next_count: Optional[int] = None) -> Any:
        '''The backup schedule: text, revision, entries and next runs (backup_schedule_get).

        Args:
            next_count: How many next runs to compute, or None.

        Returns:
            The schedule.
        '''
        return self._command('backup_schedule_get', next_count=next_count)

    def schedule_set(self, text: str, expected_revision: Optional[str] = None, dry_run: bool = False,
                     next_count: Optional[int] = None, actor: str = 'client') -> Any:
        '''Check (dry_run) or store the whole schedule text (backup_schedule_set).

        Args:
            text: The schedule text.
            expected_revision: The revision the text is based on, or None.
            dry_run: True checks without storing.
            next_count: How many next runs to compute, or None.
            actor: Who changes the schedule.

        Returns:
            The stored or checked schedule.
        '''
        return self._command('backup_schedule_set', text=text, expected_revision=expected_revision,
                             dry_run=dry_run or None, next_count=next_count, actor=actor)

    def schedule_status(self, history_limit: Optional[int] = None) -> Any:
        '''The scheduler state, the current and last runs and the next run (backup_schedule_status).

        Args:
            history_limit: How many finished runs to list, or None.

        Returns:
            The status.
        '''
        return self._command('backup_schedule_status', history_limit=history_limit)

    def help(self, cmdname: Optional[str] = None) -> Any:
        '''The command list, or the detail of one command (help).

        Args:
            cmdname: The command name, or None for the list.

        Returns:
            The help result.
        '''
        return self._command('help', cmdname=cmdname)

    def info(self, page: Optional[int] = None) -> Any:
        '''One page of the info manual (info).

        Args:
            page: The page number, or None.

        Returns:
            The page.
        '''
        return self._command('info', page=page)

    def backup_snapshots(self, limit: Optional[int] = None) -> Any:
        '''The restic snapshots (backup_snapshots).

        Args:
            limit: The maximum number of snapshots, or None.

        Returns:
            The snapshots.
        '''
        return self._command('backup_snapshots', limit=limit)

    def backup_list_files(self, snapshot_id: str, prefix: Optional[str] = None, offset: Optional[int] = None,
                          limit: Optional[int] = None) -> Any:
        '''One page of the nodes of a snapshot (backup_list_files).

        Args:
            snapshot_id: The snapshot.
            prefix: The folder prefix, or None.
            offset: Nodes to skip, or None.
            limit: The page size, or None.

        Returns:
            The page.
        '''
        return self._command('backup_list_files', snapshot_id=snapshot_id, prefix=prefix, offset=offset, limit=limit)

    def backup_prepare_download(self, snapshot_id: Optional[str] = None, file_path: Optional[str] = None,
                                file_id: Optional[str] = None, site_id: Optional[str] = None,
                                drive_id: Optional[str] = None, dir: Optional[str] = None,
                                name: Optional[str] = None, copy_index: Optional[int] = None,
                                inline_max_bytes: Optional[int] = None) -> Any:
        '''Stage an export of a snapshot or of one file, or read a small file inline (backup_prepare_download).

        Give exactly one address: file_id alone; snapshot_id and file_path; snapshot_id with site_id, drive_id, dir and
        name (copy_index optional); or snapshot_id alone for the whole snapshot.

        Args:
            snapshot_id: The snapshot.
            file_path: The file inside the snapshot, or None for the whole snapshot.
            file_id: The file id of a search row or a list node, or None.
            site_id: The site of the file (names form), or None.
            drive_id: The library of the file (names form), or None.
            dir: The folder of the file, '' is the library root (names form), or None.
            name: The shown name of the file (names form), or None.
            copy_index: The stored-copy index (names form), or None.
            inline_max_bytes: Files up to this many bytes come back inline in content_b64, or None.

        Returns:
            The export metadata.
        '''
        return self._command('backup_prepare_download', snapshot_id=snapshot_id, file_path=file_path,
                             file_id=file_id, site_id=site_id, drive_id=drive_id, dir=dir, name=name,
                             copy_index=copy_index, inline_max_bytes=inline_max_bytes)

    def backup_download_status(self, export_id: str) -> Any:
        '''The metadata of a staged export (backup_download_status).

        Args:
            export_id: The export.

        Returns:
            The metadata.
        '''
        return self._command('backup_download_status', export_id=export_id)

    def download_chunk(self, export_id: str, offset: int = 0, limit: int = 65536) -> Any:
        '''One base64 slice of a staged export (backup_download_chunk).

        Args:
            export_id: The export.
            offset: The first byte of the slice.
            limit: The most bytes of the slice, 1..262144.

        Returns:
            The slice with its total size, sha256 and eof.
        '''
        return self._command('backup_download_chunk', export_id=export_id, offset=offset, limit=limit)

    def backup_delete_export(self, export_id: str) -> Any:
        '''Delete a staged export (backup_delete_export).

        Args:
            export_id: The export.

        Returns:
            The result.
        '''
        return self._command('backup_delete_export', export_id=export_id)

    def backup_sites_list(self, limit: Optional[int] = None, offset: Optional[int] = None,
                          query: Optional[str] = None) -> Any:
        '''The SharePoint sites (backup_sites_list).

        Args:
            limit: The page size, or None.
            offset: Sites to skip, or None.
            query: A name filter, or None.

        Returns:
            The page.
        '''
        return self._command('backup_sites_list', limit=limit, offset=offset, query=query)

    def backup_libraries_list(self, site_id: str, limit: Optional[int] = None, offset: Optional[int] = None) -> Any:
        '''The document libraries of a site (backup_libraries_list).

        Args:
            site_id: The site.
            limit: The page size, or None.
            offset: Libraries to skip, or None.

        Returns:
            The page.
        '''
        return self._command('backup_libraries_list', site_id=site_id, limit=limit, offset=offset)

    def backup_discovery_status(self) -> Any:
        '''The state of the SharePoint inventory (backup_discovery_status).

        Returns:
            The state.
        '''
        return self._command('backup_discovery_status')

    def backup_download_begin(self, export_id: str) -> Any:
        '''Register a transfer session of a staged export (backup_download_begin).

        Args:
            export_id: The export.

        Returns:
            The transfer session.
        '''
        return self._command('backup_download_begin', export_id=export_id)

    def filter_options(self, site_ids: Optional[list] = None) -> Any:
        '''Sites that have indexed snapshots and the backup dates of the ticked sites (backup_filter_options).

        Args:
            site_ids: The ticked sites, or None for all.

        Returns:
            The options.
        '''
        return self._command('backup_filter_options', site_ids=site_ids)

    def search_files(self, site_ids: Optional[list] = None, dates: Optional[list] = None, name_part: str = '',
                     limit: int = 100, offset: int = 0, site_id: Optional[str] = None,
                     drive_id: Optional[str] = None, dir: Optional[str] = None,
                     recursive: Optional[bool] = None) -> Any:
        '''Files of the ticked sites and dates whose name matches, inside the folder scope (backup_search_files).

        Args:
            site_ids: The ticked sites, or None.
            dates: The ticked backup dates, or None.
            name_part: The name part, a star is a wildcard.
            limit: The page size.
            offset: Rows to skip.
            site_id: The scope site, or None.
            drive_id: The scope library of the site, or None.
            dir: The scope folder of the library, '' is the library root, or None.
            recursive: True takes the whole subtree of the folder, or None.

        Returns:
            The page.
        '''
        return self._command('backup_search_files', site_ids=site_ids or None, dates=dates or None,
                             name_part=name_part or None, limit=limit, offset=offset, site_id=site_id,
                             drive_id=drive_id, dir=dir, recursive=recursive)

    def suggest_names(self, text: str, site_ids: Optional[list] = None, dates: Optional[list] = None,
                      limit: int = 10, site_id: Optional[str] = None, drive_id: Optional[str] = None,
                      dir: Optional[str] = None, recursive: Optional[bool] = None) -> Any:
        '''Distinct file names for the autocomplete list, inside the folder scope (backup_suggest_names).

        Args:
            text: The typed text.
            site_ids: The ticked sites, or None.
            dates: The ticked backup dates, or None.
            limit: The maximum number of names.
            site_id: The scope site, or None.
            drive_id: The scope library of the site, or None.
            dir: The scope folder of the library, '' is the library root, or None.
            recursive: True takes the whole subtree of the folder, or None.

        Returns:
            The names.
        '''
        return self._command('backup_suggest_names', text=text, site_ids=site_ids or None, dates=dates or None,
                             limit=limit, site_id=site_id, drive_id=drive_id, dir=dir, recursive=recursive)

    def folder_children(self, site_id: Optional[str] = None, drive_id: Optional[str] = None,
                        dir: Optional[str] = None, site_ids: Optional[list] = None, dates: Optional[list] = None,
                        name_part: str = '', limit: int = 200, offset: int = 0) -> Any:
        '''Children of one node of the folder tree site -> library -> folders with file counts (backup_folder_children).

        Args:
            site_id: The site of the parent, or None for the sites.
            drive_id: The library of the parent, or None.
            dir: The folder of the parent, '' is the library root, or None.
            site_ids: The ticked sites, or None.
            dates: The ticked backup dates, or None.
            name_part: The name part, a star is a wildcard.
            limit: The page size.
            offset: Children to skip.

        Returns:
            The page of nodes with the path to the parent.
        '''
        return self._command('backup_folder_children', site_id=site_id, drive_id=drive_id, dir=dir,
                             site_ids=site_ids or None, dates=dates or None, name_part=name_part or None,
                             limit=limit, offset=offset)
