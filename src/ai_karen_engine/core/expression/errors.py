class ExpressionError(RuntimeError): ...
class EngineUnavailableError(ExpressionError): ...

class PrivateEvidenceAuthorizationError(ExpressionError):
    """Terminal denial of private-evidence execution; never retry."""


class ExecutionDeadlineExceeded(EngineUnavailableError):
    """Terminal denial by the original execution duration; never fallback."""


class ExecutionAdmissionRejected(EngineUnavailableError):
    """Terminal execution admission failure; never a provider health failure."""
