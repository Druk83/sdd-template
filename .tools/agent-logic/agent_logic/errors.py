class AgentLogicError(Exception):
    """Base error for expected user-facing failures."""


class InputError(AgentLogicError):
    """Raised when input cannot be accepted under the MVP contract."""


class OutputError(AgentLogicError):
    """Raised when an output artifact cannot be written safely."""