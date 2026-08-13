from __future__ import annotations

from pathlib import PurePosixPath
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse


router = APIRouter(prefix="/streaming", tags=["streaming-hls"])

_FORWARDED_REQUEST_HEADERS = ("authorization", "cookie", "range", "if-none-match", "if-modified-since")
_FORWARDED_RESPONSE_HEADERS = (
    "cache-control",
    "content-length",
    "content-range",
    "content-type",
    "etag",
    "expires",
    "last-modified",
    "accept-ranges",
)
_URI_ATTRIBUTE_RE = re.compile(r'(URI=)(["\'])([^"\']+)(\2)')


def _hls_upstream_url(request: Request, hls_path: str) -> str:
    # The proxy is deliberately restricted to MediaMTX's live HLS namespace;
    # the browser must never be able to turn this endpoint into an SSRF proxy.
    path = hls_path.strip("/")
    path_parts = PurePosixPath(path).parts
    if not path.startswith("live/") or ".." in path_parts or not path_parts:
        raise HTTPException(status_code=404, detail="HLS path not found")

    raw_base = str(getattr(request.app.state.settings, "streaming_hls_proxy_url", "") or "").strip()
    parsed = urlsplit(raw_base.rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"}:
        raise HTTPException(status_code=500, detail="HLS proxy is misconfigured")
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{path}", "", ""))


def _rewrite_location(location: str) -> str:
    parsed = urlsplit(location)
    path = parsed.path
    if path.startswith("/live/"):
        path = f"/streaming/hls{path}"
    elif not path.startswith("/streaming/hls/"):
        return location
    return urlunsplit(("", "", path, parsed.query, parsed.fragment))


def _set_cookie_value(headers: httpx.Headers, name: str) -> str:
    for value in headers.get_list("set-cookie"):
        first = value.split(";", 1)[0]
        key, separator, cookie_value = first.partition("=")
        if separator and key.strip() == name:
            return cookie_value.strip()
    return ""


def _append_session(uri: str, session: str) -> str:
    parsed = urlsplit(uri.strip())
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if not any(key == "session" for key, _ in query):
        query.append(("session", session))
    path = parsed.path
    if parsed.scheme in {"http", "https"} and path.startswith("/live/"):
        path = f"/streaming/hls{path}"
        return urlunsplit(("", "", path, urlencode(query), parsed.fragment))
    return urlunsplit((parsed.scheme, parsed.netloc, path, urlencode(query), parsed.fragment))


def _rewrite_playlist(content: bytes, session: str) -> bytes:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return content
    lines: list[str] = []
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped and not stripped.startswith("#"):
            newline = ""
            body = line
            if body.endswith("\n"):
                body, newline = body[:-1], "\n"
                if body.endswith("\r"):
                    body, newline = body[:-1], "\r\n"
            line = f"{_append_session(body, session)}{newline}"
        elif session and stripped.startswith("#"):
            # Low-Latency HLS carries media URIs inside comment tags such as
            # EXT-X-PART and EXT-X-PRELOAD-HINT. They still need the same
            # MediaMTX session query as ordinary segment lines.
            line = _URI_ATTRIBUTE_RE.sub(
                lambda match: (
                    f"{match.group(1)}{match.group(2)}"
                    f"{_append_session(match.group(3), session)}{match.group(4)}"
                ),
                line,
            )
        lines.append(line)
    return "".join(lines).encode("utf-8")


@router.get("/hls/{hls_path:path}", response_model=None)
async def proxy_hls(hls_path: str, request: Request) -> Response:
    upstream_url = _hls_upstream_url(request, hls_path)
    request_headers = {
        name: value
        for name in _FORWARDED_REQUEST_HEADERS
        if (value := request.headers.get(name))
    }
    session = request.query_params.get("session", "").strip()
    if session and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", session):
        raise HTTPException(status_code=400, detail="invalid HLS session")
    # MediaMTX requires the cookie-check query and cookie together. Keep this
    # state inside the server-side request; the browser does not need to carry
    # an HttpOnly/Secure cookie between the master and child playlists.
    request_headers["cookie"] = "cookieCheck=1" + (f"; hlsSession={session}" if session else "")
    upstream_params = [
        (key, value)
        for key, value in request.query_params.multi_items()
        if key not in {"cookieCheck", "session"}
    ]
    upstream_params.append(("cookieCheck", "1"))
    timeout = httpx.Timeout(connect=3.0, read=15.0, write=5.0, pool=3.0)
    client = httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False)
    try:
        upstream = await client.send(
            client.build_request(
                "GET",
                upstream_url,
                params=httpx.QueryParams(tuple(upstream_params)),
                headers=request_headers,
            ),
            stream=True,
        )
    except httpx.RequestError as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail="HLS upstream unavailable") from exc

    response_headers: dict[str, str] = {}
    for name in _FORWARDED_RESPONSE_HEADERS:
        value = upstream.headers.get(name)
        if value:
            response_headers[name] = value
    location = upstream.headers.get("location")
    if location:
        response_headers["location"] = _rewrite_location(location)

    is_playlist = hls_path.lower().endswith(".m3u8") or "mpegurl" in upstream.headers.get("content-type", "").lower()
    if is_playlist and upstream.status_code == 200:
        try:
            content = await upstream.aread()
        finally:
            await upstream.aclose()
            await client.aclose()
        playlist_session = session or _set_cookie_value(upstream.headers, "hlsSession")
        if playlist_session:
            content = _rewrite_playlist(content, playlist_session)
        response_headers["content-length"] = str(len(content))
        response_headers.pop("location", None)
        return Response(content=content, status_code=upstream.status_code, headers=response_headers)

    async def body():
        try:
            async for chunk in upstream.aiter_raw():
                if chunk:
                    yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        body(),
        status_code=upstream.status_code,
        headers=response_headers,
    )
