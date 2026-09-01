"""Project-specific exception types."""


class UMCMError(Exception):
    """Base class for all expected µMCM errors."""


class SchemaError(UMCMError):
    """Raised when an event schema is malformed or inconsistent."""


class TraceValidationError(UMCMError):
    """Raised when a trace does not conform to its event catalog."""


class ExpressionTypeError(UMCMError):
    """Raised when an expression is not well typed."""


class SerializationError(UMCMError):
    """Raised when YAML/JSON content cannot be decoded into the IR."""
