'''Errors of the OneDrive Backup client.'''

from __future__ import annotations

from typing import Any


class ClientError(Exception):
    '''A command, transport, protocol or integrity failure.

    code is the error code of the server (a JSON-RPC code such as -32602, or a command code such as 404 or 503)
    and data is the error data of the server (for -32602 data[violation] is unknown, missing, type or value);
    both are None for a local failure.
    '''

    def __init__(self, message: str, code: Any = None, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


class ClientAuthenticationError(ClientError):
    '''The server refused the credentials (HTTP 401).'''
