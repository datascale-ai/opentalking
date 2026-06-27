"""Capability providers — importing any sub-package auto-registers its adapters
via opentalking.core.registry. To force-load every provider in one go, call
opentalking.providers.bootstrap().
"""


def bootstrap() -> None:
    """Import every provider sub-package so its registrations take effect."""
    from opentalking.providers import (  # noqa: F401
        llm,
        rtc,
        stt,
        synthesis,
        tts,
    )
