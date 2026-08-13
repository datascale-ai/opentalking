from apps.api.routes.hls_proxy import _rewrite_playlist


def test_rewrite_playlist_adds_session_to_low_latency_uri_tags() -> None:
    playlist = (
        b"#EXTM3U\n"
        b'#EXT-X-MAP:URI="init.mp4"\n'
        b'#EXT-X-PART:DURATION=0.2,URI="seg0.part0.m4s"\n'
        b'#EXT-X-PRELOAD-HINT:TYPE=PART,URI="seg0.part1.m4s"\n'
        b"seg0.m4s\n"
    )

    rewritten = _rewrite_playlist(playlist, "session-1").decode()

    assert 'URI="init.mp4?session=session-1"' in rewritten
    assert 'URI="seg0.part0.m4s?session=session-1"' in rewritten
    assert 'URI="seg0.part1.m4s?session=session-1"' in rewritten
    assert "seg0.m4s?session=session-1" in rewritten
