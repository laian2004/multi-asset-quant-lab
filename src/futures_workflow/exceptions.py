class WorkflowError(Exception):
    """Base exception for the workflow."""


class SourceNoDataError(WorkflowError):
    """Raised when a source has no data for a requested trading date."""


class PendingRetryError(WorkflowError):
    """Raised when a source should be retried later."""


class ParsingError(WorkflowError):
    """Raised when a response cannot be parsed reliably."""


class ProtectiveBlockError(WorkflowError):
    """Raised when a remote source returns an anti-bot or protective block response."""
