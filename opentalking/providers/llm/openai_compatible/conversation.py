from __future__ import annotations


class ConversationHistory:
    """Manages conversation history for a session with a max turn limit."""

    def __init__(
        self,
        system_prompt: str = "\u4f60\u662f\u4e00\u4e2a\u53cb\u597d\u7684\u6570\u5b57\u4eba\u52a9\u624b\u3002",
        max_turns: int = 20,
    ) -> None:
        self.system_prompt = system_prompt
        self.max_turns = max_turns
        self._messages: list[dict[str, str]] = []

    def add_user(self, text: str) -> None:
        """Add a user message."""
        self._messages.append({"role": "user", "content": text})
        self._trim()

    def add_assistant(self, text: str) -> None:
        """Add an assistant response."""
        self._messages.append({"role": "assistant", "content": text})
        self._trim()

    def get_messages(self) -> list[dict[str, str]]:
        """Get full message list including the system prompt for an API call."""
        return [{"role": "system", "content": self.system_prompt}] + list(
            self._messages
        )

    def _trim(self) -> None:
        """Keep only the last ``max_turns * 2`` messages (user+assistant pairs)."""
        max_msgs = self.max_turns * 2
        if len(self._messages) > max_msgs:
            self._messages = self._messages[-max_msgs:]

    def clear(self) -> None:
        """Remove all conversation history."""
        self._messages.clear()
