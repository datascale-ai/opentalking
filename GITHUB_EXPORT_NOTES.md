This directory is a cleaned GitHub-ready export from the working tree at `/data1/xuxin/opentalking`.

Not included in this export:
- `models/` checkpoints and weights
- runtime/debug outputs such as `debug/`, `output/`, `logs/`, `temp_voice/`
- local Python/Node caches such as `.venv/`, `__pycache__/`, `node_modules/`
- generated avatar caches such as `examples/avatars/*/prepared/` and `.flashtalk_idle_cache*.npz`

Before running:
1. Install Python dependencies from the project configuration.
2. Install web dependencies under `apps/web/`.
3. Download or mount required model files into `models/`.
