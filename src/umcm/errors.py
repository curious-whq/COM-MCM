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


class SolverError(UMCMError):
    """Raised when a feasibility backend cannot encode or solve a problem."""


class BackendUnavailableError(SolverError):
    """Raised when a requested optional solver backend is not installed."""


class CompletionError(UMCMError):
    """Raised when a completion specification cannot be instantiated."""


class GraphError(UMCMError):
    """Raised when an execution graph cannot be projected or constructed."""


class AxiomError(UMCMError):
    """Raised when an axiom or relation specification is malformed."""


class AbstractionError(UMCMError):
    """Raised when a hierarchy/abstraction model cannot be applied."""
