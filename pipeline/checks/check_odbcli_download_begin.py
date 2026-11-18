'''odbcli_download_begin: odbcli download-begin EXPORT_ID (O16)

Mode: live against the production service or its disposable instances (block B4, revision 4 of the matrix TODO); the logic is in pipeline.b4cli.
Findings are kept apart as PRODUCT, STATE and ENVIRONMENT; a case that needs S1 or credentials is RED with that reason.
'''

from __future__ import annotations

from pipeline import b4cli


def run() -> None:
    '''Raise CheckFailure when the check is RED.'''
    b4cli.odbcli_download_begin()
