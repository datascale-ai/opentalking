from __future__ import annotations

from typing import Callable, TypeVar

from opentalking.core.interfaces.model_adapter import ModelAdapter

T = TypeVar("T", bound=type)

_ADAPTERS: dict[str, Callable[[], ModelAdapter]] = {}


def register_model(model_type: str) -> Callable[[T], T]:
    def decorator(cls: T) -> T:
        def factory() -> ModelAdapter:
            return cls()  # type: ignore[return-value]

        _ADAPTERS[model_type] = factory
        return cls

    return decorator


def get_adapter(model_type: str) -> ModelAdapter:
    if model_type not in _ADAPTERS:
        raise ValueError(
            f"Unknown model type: {model_type}. Available: {sorted(_ADAPTERS.keys())}"
        )
    return _ADAPTERS[model_type]()


# Model types that bypass the ModelAdapter protocol (remote/special runners)
_REMOTE_MODELS: set[str] = {"flashtalk"}


def list_models(*, include_flashtalk: bool = True) -> list[str]:
    models = set(_ADAPTERS.keys())
    if include_flashtalk:
        models |= _REMOTE_MODELS
    return sorted(models)


def list_available_models(*, flashtalk_mode: str) -> list[str]:
    return list_models(include_flashtalk=flashtalk_mode.strip().lower() != "off")


def ensure_models_imported() -> None:
    """Import side-effect: register built-in adapters."""
    import opentalking.models.musetalk.adapter  # noqa: F401
    import opentalking.models.wav2lip.adapter  # noqa: F401
