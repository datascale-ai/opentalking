from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


def load_model_paths() -> Any:
    module_name = "_opentalking_core_model_paths_standalone"
    module = sys.modules.get(module_name)
    if module is not None:
        return module

    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "opentalking" / "core" / "model_paths.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load model path helpers from {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
