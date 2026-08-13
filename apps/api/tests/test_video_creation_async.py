from __future__ import annotations

import time

from apps.api.tests.test_video_creation import _client


def test_async_video_creation_returns_job_before_final_export(tmp_path, monkeypatch) -> None:
    client, _creators = _client(tmp_path, monkeypatch)
    with client:
        response = client.post(
            "/video-creation/jobs",
            data={
                "model": "wav2lip",
                "avatar_id": "anchor",
                "audio_source": "tts_text",
                "text": "async video",
                "execution_mode": "async",
            },
        )
        assert response.status_code == 202, response.text
        payload = response.json()
        assert payload["job_id"].startswith("job_")
        assert payload["status"] in {"queued", "generating", "completed"}
        for _ in range(20):
            current = client.get(f"/video-creation/jobs/{payload['job_id']}").json()
            if current["status"] == "completed":
                break
            time.sleep(0.01)
    assert current["status"] == "completed"
    assert current["final_export_id"] == "export-tts"
    assert "published_duration_ms" not in current
