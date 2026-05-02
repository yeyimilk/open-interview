"""Cross-cutting workspace helpers.

Single-line summaries used in system prompts for /chat-style flows so
the model knows what the user owns without needing to call tools.
"""
from .brief import workspace_brief

__all__ = ["workspace_brief"]
