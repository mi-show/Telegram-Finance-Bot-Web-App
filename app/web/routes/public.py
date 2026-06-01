from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR.parent / "static"


def _no_cache_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }


router = APIRouter()


@router.get("/", include_in_schema=False)
async def root_redirect():
    return RedirectResponse(url="/webapp", status_code=307)


@router.get("/webapp", include_in_schema=False)
async def webapp_index():
    return FileResponse(STATIC_DIR / "index.html", headers=_no_cache_headers())


@router.get("/webapp/", include_in_schema=False)
async def webapp_index_slash():
    return FileResponse(STATIC_DIR / "index.html", headers=_no_cache_headers())


@router.get("/api/webapp/health")
async def webapp_health():
    return {"ok": True, "service": "webapp"}


__all__ = ("router",)
