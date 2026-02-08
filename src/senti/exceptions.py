"""Custom exception hierarchy for Senti."""


class SentiError(Exception):
    """Base exception for all Senti errors."""


class ConfigError(SentiError):
    """Configuration is invalid or missing."""


class LLMError(SentiError):
    """LLM call failed."""


class ToolError(SentiError):
    """Tool execution failed."""


class SandboxError(SentiError):
    """Sandbox container error."""


class SandboxTimeoutError(SandboxError):
    """Sandbox container exceeded time limit."""


class ApprovalDeniedError(ToolError):
    """User denied a HITL approval request."""


class ApprovalTimeoutError(ToolError):
    """HITL approval request timed out."""


class RedactionError(SentiError):
    """Redaction processing failed."""


class TokenLimitError(SentiError):
    """Token or loop limit exceeded."""
