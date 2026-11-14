"""Python client for the OneDrive Backup API."""
__version__ = "0.2.0"

from .api import BackupClient, ClientError

__all__ = ["BackupClient", "ClientError", "__version__"]

