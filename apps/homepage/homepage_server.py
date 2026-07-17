from urllib.error import HTTPError, URLError

from fastapi import FastAPI, HTTPException, Request as FastAPIRequest
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from server.analytics_store import record_analytics_event as record_analytics_event_handler
from server.config import DIST_DIR, GITHUB_API_URL, GITHUB_REPO_NAME, GITHUB_REPO_OWNER
from server.github_stats import fetch_github_json
from server.traffic_dashboard import render_traffic_dashboard


app = FastAPI(docs_url=None, redoc_url=None)

if not DIST_DIR.exists():
    raise RuntimeError(f"Homepage dist not found: {DIST_DIR}")

assets_dir = DIST_DIR / "assets"
images_dir = DIST_DIR / "images"

if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

if images_dir.exists():
    app.mount("/images", StaticFiles(directory=images_dir), name="images")


@app.get("/health")
def health():
    return PlainTextResponse("ok")


@app.post("/analytics/event")
async def record_analytics_event(request: FastAPIRequest):
    return await record_analytics_event_handler(request)


@app.get("/traffic")
def traffic_dashboard_zh():
    return render_traffic_dashboard("zh")


@app.get("/en/traffic")
def traffic_dashboard_en():
    return render_traffic_dashboard("en")


@app.get("/github-api/repos/{owner}/{repo}")
def github_repo_stats(owner: str, repo: str):
    if owner != GITHUB_REPO_OWNER or repo != GITHUB_REPO_NAME:
        raise HTTPException(status_code=404, detail="GitHub repo proxy not found")

    try:
        repo_data, _ = fetch_github_json(GITHUB_API_URL)
        return JSONResponse(
            content=repo_data,
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )
    except HTTPError as error:
        raise HTTPException(status_code=error.code, detail="GitHub API request failed") from error
    except URLError as error:
        raise HTTPException(status_code=502, detail=f"GitHub API unavailable: {error.reason}") from error


@app.get("/{path:path}")
def serve_spa(path: str):
    target = DIST_DIR / path

    if target.is_file():
        return FileResponse(target)

    return FileResponse(DIST_DIR / "index.html")
