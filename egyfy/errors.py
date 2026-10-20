"""Errors that can be reported to API clients."""


class ParserError(Exception):
    """Base class for expected application errors."""


class InvalidDocument(ParserError):
    """The uploaded file cannot be read or accepted."""


class DocumentExpired(ParserError):
    """The client refers to a document that is no longer cached."""


class PageOutOfRange(ParserError):
    """The requested page does not exist or no pages were selected."""


class InvalidOptions(ParserError):
    """One or more processing options are invalid."""


class RequestTooLarge(ParserError):
    """The request body exceeds the configured upload limit."""

