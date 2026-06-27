from __future__ import annotations

import re


class SentenceSplitter:
    """Accumulates streaming text deltas and yields complete sentences.

    Splits on Chinese punctuation: \u3002 \uff01 \uff1f
    Splits on English punctuation followed by space or end: .  !  ?
    """

    # Chinese sentence-ending punctuation: split immediately after them.
    # English sentence-ending punctuation: split when followed by a space.
    _SPLIT_RE = re.compile(
        r"("                                          # whole sentence boundary
        r"[\u3002\uff01\uff1f][”’」』）》】〕〉）\]\"']*"  # Chinese punct + optional closers
        r"|[.!?][”’」』）》】〕〉）\]\"']*(?:\s|$)"        # English punct + closers + whitespace/end
        r")"
    )

    def __init__(self) -> None:
        self._buffer: str = ""

    def feed(self, delta: str) -> list[str]:
        """Feed a text delta, return a list of complete sentences (may be empty)."""
        self._buffer += delta
        sentences: list[str] = []

        while True:
            m = self._SPLIT_RE.search(self._buffer)
            if m is None:
                break
            end = m.end()
            sentence = self._buffer[:end].strip()
            if sentence:
                sentences.append(sentence)
            self._buffer = self._buffer[end:]

        return sentences

    def flush(self) -> str | None:
        """Return any remaining text in the buffer (call at end of stream)."""
        if self._buffer.strip():
            text = self._buffer.strip()
            self._buffer = ""
            return text
        self._buffer = ""
        return None
