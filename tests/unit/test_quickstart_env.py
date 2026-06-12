from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_quickstart_source_env_exports_plain_assignments(tmp_path: Path) -> None:
    if shutil.which("bash") is None:
        pytest.skip("bash is not available")
    env_file = tmp_path / "quickstart.env"
    env_file.write_text(
        "OPENTALKING_TEST_PLAIN_ASSIGNMENT=from_quickstart_env\n",
        encoding="utf-8",
    )

    script = f"""
set -euo pipefail
source scripts/quickstart/_helpers.sh
quickstart_source_env {env_file}
bash -c 'test "$OPENTALKING_TEST_PLAIN_ASSIGNMENT" = from_quickstart_env'
"""

    subprocess.run(["bash", "-lc", script], cwd=REPO_ROOT, check=True)


def test_quickstart_entrypoints_use_exporting_env_loader() -> None:
    entrypoints = [
        "scripts/quickstart/start_opentalking.sh",
        "scripts/quickstart/start_frontend.sh",
    ]

    for relpath in entrypoints:
        source = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        assert "source \"$script_dir/_helpers.sh\"" in source
        assert "quickstart_source_env \"$env_file\"" in source



def test_quickstart_source_env_preserves_calling_environment(tmp_path: Path) -> None:
    if shutil.which("bash") is None:
        pytest.skip("bash is not available")
    env_file = tmp_path / "quickstart.env"
    env_file.write_text(
        "OPENTALKING_TEST_OVERRIDE=from_quickstart_env\n"
        "OPENTALKING_TEST_DEFAULT=from_quickstart_env\n",
        encoding="utf-8",
    )

    script = f"""
set -euo pipefail
export OPENTALKING_TEST_OVERRIDE=from_calling_shell
source scripts/quickstart/_helpers.sh
quickstart_source_env {env_file}
bash -c 'test "$OPENTALKING_TEST_OVERRIDE" = from_calling_shell'
bash -c 'test "$OPENTALKING_TEST_DEFAULT" = from_quickstart_env'
"""

    subprocess.run(["bash", "-lc", script], cwd=REPO_ROOT, check=True)


def test_quickstart_source_env_keeps_new_env_file_assignments(tmp_path: Path) -> None:
    if shutil.which("bash") is None:
        pytest.skip("bash is not available")
    env_file = tmp_path / "quickstart.env"
    env_file.write_text(
        "OPENTALKING_QUICKTALK_ASSET_ROOT=/models/quicktalk\n"
        "OPENTALKING_WAV2LIP_DEVICE=cuda:6\n",
        encoding="utf-8",
    )

    script = f"""
set -euo pipefail
export OPENTALKING_TORCH_DEVICE=cuda:6
unset OPENTALKING_QUICKTALK_ASSET_ROOT
unset OPENTALKING_WAV2LIP_DEVICE
source scripts/quickstart/_helpers.sh
quickstart_source_env {env_file}
bash -c 'test "$OPENTALKING_TORCH_DEVICE" = cuda:6'
bash -c 'test "$OPENTALKING_QUICKTALK_ASSET_ROOT" = /models/quicktalk'
bash -c 'test "$OPENTALKING_WAV2LIP_DEVICE" = cuda:6'
"""

    subprocess.run(["bash", "-lc", script], cwd=REPO_ROOT, check=True)


def test_start_unified_sets_apple_silicon_quicktalk_defaults() -> None:
    source = (REPO_ROOT / "scripts/start_unified.sh").read_text(encoding="utf-8")

    assert 'if [[ "$backend" == "local" && "$model" == "quicktalk" ]]' in source
    assert "quicktalk-cpu" in source
    assert "OPENTALKING_QUICKTALK_DEVICE" in source
    assert "sys.platform == 'darwin'" in source


@pytest.mark.parametrize(
    "relpath",
    [
        "scripts/quickstart/start_opentalking.sh",
        "scripts/quickstart/start_frontend.sh",
    ],
)
def test_quickstart_process_launch_does_not_require_setsid_on_macos(relpath: str) -> None:
    source = (REPO_ROOT / relpath).read_text(encoding="utf-8")
    helpers = (REPO_ROOT / "scripts/quickstart/_helpers.sh").read_text(encoding="utf-8")

    assert "quickstart_detach" in source
    assert "command -v setsid" in helpers
    assert "start_new_session=True" in helpers


def test_start_opentalking_resolves_ffmpeg_fallback() -> None:
    source = (REPO_ROOT / "scripts/quickstart/start_opentalking.sh").read_text(encoding="utf-8")
    helpers = (REPO_ROOT / "scripts/quickstart/_helpers.sh").read_text(encoding="utf-8")

    assert "quickstart_resolve_ffmpeg" in source
    assert 'OPENTALKING_FFMPEG_BIN="${OPENTALKING_FFMPEG_BIN:-ffmpeg}"' not in source
    assert "imageio_ffmpeg.get_ffmpeg_exe()" in helpers


def test_quickstart_source_ascend_env_tolerates_unset_ld_library_path(tmp_path: Path) -> None:
    if shutil.which("bash") is None:
        pytest.skip("bash is not available")
    ascend_env = tmp_path / "set_env.sh"
    ascend_env.write_text(
        'export LD_LIBRARY_PATH="${LD_LIBRARY_PATH}:/mock/ascend/lib64"\n',
        encoding="utf-8",
    )

    script = f"""
set -euo pipefail
unset LD_LIBRARY_PATH
source scripts/quickstart/_helpers.sh
quickstart_source_ascend_env {ascend_env}
bash -c 'case "$LD_LIBRARY_PATH" in *:/mock/ascend/lib64) exit 0 ;; *) exit 1 ;; esac'
"""

    subprocess.run(["bash", "-lc", script], cwd=REPO_ROOT, check=True)
