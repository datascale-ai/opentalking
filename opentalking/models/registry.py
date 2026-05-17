from __future__ import annotations

from typing import Callable, TypeVar

from opentalking.core.interfaces.model_adapter import ModelAdapter

T = TypeVar("T", bound=type)

_ADAPTERS: dict[str, Callable[[], ModelAdapter]] = {}
_REMOTE_MODELS: set[str] = {"flashtalk", "flashhead"}


def register_model(model_type: str) -> Callable[[T], T]:
    def decorator(cls: T) -> T:
        def factory() -> ModelAdapter:
            return cls()  # type: ignore[return-value]

        _ADAPTERS[model_type] = factory
        return cls

    return decorator


def get_adapter(model_type: str) -> ModelAdapter:
    ensure_models_imported()
    if model_type not in _ADAPTERS:
        raise ValueError(
            f"Unknown model type: {model_type}. Available: {sorted(_ADAPTERS.keys())}"
        )
    return _ADAPTERS[model_type]()


def list_models(*, include_flashtalk: bool = True) -> list[str]:
    ensure_models_imported()
    models = set(_ADAPTERS.keys())
    models |= _REMOTE_MODELS - {"flashtalk"}
    if include_flashtalk:
        models.add("flashtalk")
    return sorted(models)


def list_available_models(*, flashtalk_mode: str) -> list[str]:
    return list_models(include_flashtalk=flashtalk_mode.strip().lower() != "off")


def ensure_models_imported() -> None:
    """Import side-effect: register built-in local model adapters."""
    import opentalking.models.quicktalk.adapter  # noqa: F401
    import opentalking.models.wav2lip.adapter  # noqa: F401
