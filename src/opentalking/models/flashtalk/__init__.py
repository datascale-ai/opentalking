from __future__ import annotations

# Lazy imports to avoid pulling in heavy engine/torch dependencies
# when only the WS client (remote mode) is needed.

from opentalking.models.flashtalk.ws_client import FlashTalkWSClient

__all__ = ["FlashTalkLocalAdapter", "FlashTalkWSClient"]


def __getattr__(name: str):
    if name == "FlashTalkLocalAdapter":
        from opentalking.models.flashtalk.local_adapter import FlashTalkLocalAdapter
        return FlashTalkLocalAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
