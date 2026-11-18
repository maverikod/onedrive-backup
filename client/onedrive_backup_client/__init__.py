"""Python client for the OneDrive Backup API."""
__version__ = "0.3.7"

from .api import BackupClient, ClientError

__all__ = ["BackupClient", "ClientError", "__version__"]

