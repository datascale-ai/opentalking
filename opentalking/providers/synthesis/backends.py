from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from opentalking.core.model_config import get_model_backend, get_model_runtime_config


@dataclass(frozen=True)
class ModelBackend:
    model: str
    backend: str
    ws_url: str = ""

    @property
    def uses_flashtalk_protocol(self) -> bool:
        return self.backend in {"omnirt", "direct_ws"} and self.model != "flashhead"

    @property
    def uses_local_adapter(self) -> bool:
        return self.backend == "local"


def _model_config(model: str) -> dict[str, Any]:
    try:
        return get_model_runtime_config(model)
    except ValueError:
        return {}


def direct_ws_url(model: str, settings: Any) -> str:
    model = model.strip().lower()
    config_url = str(_model_config(model).get("ws_url") or "").strip()
    if config_url:
        return config_url
    attr_url = str(getattr(settings, f"{model}_ws_url", "") or "").strip()
    if attr_url:
        return attr_url
    if model == "flashtalk":
        return str(getattr(settings, "flashtalk_ws_url", "") or "").strip()
    if model == "flashhead":
        return str(getattr(settings, "flashhead_ws_url", "") or "").strip()
    return ""


def resolve_model_backend(model: str, settings: Any) -> ModelBackend:
    model = model.strip().lower()
    backend = str(getattr(settings, f"{model}_backend", "") or "").strip().lower()
    if backend not in {"mock", "local", "omnirt", "direct_ws"}:
        backend = get_model_backend(model)
    if backend == "direct_ws":
        return ModelBackend(model=model, backend=backend, ws_url=direct_ws_url(model, settings))
    return ModelBackend(model=model, backend=backend)
