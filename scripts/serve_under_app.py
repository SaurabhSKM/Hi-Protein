"""Serve the API and the built frontend under the /app prefix on port 8081.

The workshop container runs an nginx in front of this process whose only two routes
are `/` -> the code editor on 8080 and `/app` -> this app on 8081, with the `/app`
prefix forwarded intact rather than stripped. Running uvicorn on some other port and
reaching it at `/ports/<n>/` does not work: that path matches nginx's `location /`,
so it lands on the code editor, which rejects it with a 400.

Mounting the real app under `/app` makes Starlette strip the prefix before routing, so
`backend/app/main.py` keeps its own paths (`/api/v1/...`, `/health`, the static SPA)
unchanged and stays correct when served from the domain root as well.

    .venv/bin/python scripts/serve_under_app.py

Then open https://<distribution>.cloudfront.net/app/ (the trailing slash matters: the
frontend resolves its asset and API URLs relative to the directory it was loaded from).
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

import uvicorn  # noqa: E402
from app.main import app as inner  # noqa: E402
from fastapi import FastAPI  # noqa: E402

MOUNT = "/app"
PORT = 8081

outer = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
# Mount, not include_router: a mount strips MOUNT from the path before handing the
# request down, which is what lets the inner app keep its root-relative routes.
outer.mount(MOUNT, inner)


@outer.get("/", include_in_schema=False)
def _root() -> dict:
    return {"message": f"Hi-Protein is served under {MOUNT}/", "open": f"{MOUNT}/"}


if __name__ == "__main__":
    uvicorn.run(outer, host="0.0.0.0", port=PORT, log_level="info")
