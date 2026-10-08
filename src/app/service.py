"""Serve a local prepared-feature form and forward requests to the existing API."""

import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse

HERE = Path(__file__).resolve().parent
MAX_BODY_BYTES = 16384
STATIC_FILES = {"app.js": "text/javascript", "styles.css": "text/css"}


def create_app(example_path=None, transport=None, api_url="http://api:8000"):
    example = Path(example_path) if example_path is not None else HERE / "example_features.json"

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(
            base_url=api_url, timeout=httpx.Timeout(30, connect=5),
            follow_redirects=False, trust_env=False, transport=transport,
        ) as client:
            app.state.client = client
            yield

    app = FastAPI(title="Road Accident Local Application", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def response_headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        return response

    async def forward(request, path, body=None):
        headers = {"Content-Type": "application/json"} if body is not None else None
        try:
            upstream = await request.app.state.client.request(
                "POST" if body is not None else "GET", path, content=body, headers=headers,
            )
        except httpx.RequestError:
            raise HTTPException(503, "Prediction API is unavailable. Check the local services.") from None
        if upstream.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
            raise HTTPException(502, "Unexpected response from the prediction API.")
        return Response(upstream.content, status_code=upstream.status_code, media_type="application/json")

    @app.get("/")
    def index():
        return FileResponse(HERE / "index.html", media_type="text/html")

    @app.get("/static/{name}")
    def static_file(name: str):
        if name not in STATIC_FILES:
            raise HTTPException(404, "File not found.")
        return FileResponse(HERE / name, media_type=STATIC_FILES[name])

    @app.get("/api/example")
    def reference_example():
        return {"features": json.loads(example.read_text(encoding="utf-8"))}

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    @app.get("/api/health/ready")
    async def ready(request: Request):
        return await forward(request, "/health/ready")

    @app.post("/api/predict")
    async def predict(request: Request):
        if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
            raise HTTPException(415, "Content-Type application/json is required.")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BODY_BYTES:
                raise HTTPException(413, "Request body exceeds 16384 bytes.")
        # Preserve bytes so the API can reject duplicates, malformed JSON and invalid values.
        return await forward(request, "/predict", bytes(body))

    return app


app = create_app()
