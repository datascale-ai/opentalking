import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles


ROOT = Path(__file__).resolve().parent
DIST_DIR = ROOT / "dist"
GITHUB_REPO_OWNER = "datascale-ai"
GITHUB_REPO_NAME = "opentalking"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}"

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


@app.get("/github-api/repos/{owner}/{repo}")
def github_repo_stats(owner: str, repo: str):
    if owner != GITHUB_REPO_OWNER or repo != GITHUB_REPO_NAME:
        raise HTTPException(status_code=404, detail="GitHub repo proxy not found")

    request = Request(
        GITHUB_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "opentalking-homepage",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    try:
        with urlopen(request, timeout=10) as response:
            return JSONResponse(
                content=json.loads(response.read().decode("utf-8")),
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
