"""HTTP API wrapper around the MarkItDown conversion engine.

Exposes document-to-Markdown conversion over HTTP so that frontends and other
services can call MarkItDown without shelling out to the CLI. Lives entirely
under `api/` so that syncing this fork with upstream microsoft/markitdown
never touches it (see api/README.md for details).
"""

import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from markitdown import MarkItDown, StreamInfo, __version__ as markitdown_version
from markitdown._exceptions import FileConversionException, UnsupportedFormatException

API_KEY = os.environ.get("API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL") or None
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
CORS_ALLOW_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ALLOW_ORIGINS", "").split(",")
    if origin.strip()
]

_state: dict = {}


def _build_markitdown() -> MarkItDown:
    """Construct a MarkItDown instance, wiring in an LLM client for image/audio
    descriptions when OPENAI_API_KEY is configured."""
    kwargs: dict = {}
    if OPENAI_API_KEY:
        from openai import OpenAI

        client_kwargs: dict = {"api_key": OPENAI_API_KEY}
        if OPENAI_BASE_URL:
            client_kwargs["base_url"] = OPENAI_BASE_URL
        kwargs["llm_client"] = OpenAI(**client_kwargs)
        kwargs["llm_model"] = OPENAI_MODEL

    return MarkItDown(enable_plugins=False, **kwargs)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _state["markitdown"] = _build_markitdown()
    yield
    _state.clear()


app = FastAPI(
    title="MarkItDown API",
    description=(
        "HTTP API for converting documents (PDF, Office, images, audio, HTML, "
        "and more) to Markdown using Microsoft's MarkItDown library."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

if CORS_ALLOW_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ALLOW_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def require_api_key(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> None:
    """Validate the X-API-Key header against the configured API_KEY.

    When API_KEY is unset, authentication is skipped (local/dev mode).
    """
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key. Provide it via the X-API-Key header.",
        )


class ConvertUrlRequest(BaseModel):
    url: str = Field(..., description="URL of the document or webpage to convert")


class ConvertResponse(BaseModel):
    markdown: str
    title: Optional[str] = None
    source: Optional[str] = None


def _result_to_response(result, *, source: Optional[str] = None) -> ConvertResponse:
    return ConvertResponse(markdown=result.markdown, title=result.title, source=source)


def _raise_for_conversion_error(exc: Exception) -> None:
    if isinstance(exc, UnsupportedFormatException):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
        )
    if isinstance(exc, FileConversionException):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@app.get("/health", tags=["meta"])
def health() -> dict:
    """Liveness/readiness probe — does not require authentication."""
    return {"status": "ok"}


@app.get("/info", tags=["meta"])
def info() -> dict:
    """Basic information about this API instance and its capabilities."""
    return {
        "name": "markitdown-api",
        "markitdown_version": markitdown_version,
        "llm_image_descriptions_enabled": bool(OPENAI_API_KEY),
        "llm_model": OPENAI_MODEL if OPENAI_API_KEY else None,
        "auth_required": bool(API_KEY),
        "max_upload_bytes": MAX_UPLOAD_BYTES,
    }


@app.post(
    "/convert/file",
    response_model=ConvertResponse,
    tags=["convert"],
    dependencies=[Depends(require_api_key)],
)
async def convert_file(file: UploadFile = File(...)) -> ConvertResponse:
    """Convert an uploaded file to Markdown."""
    suffix = Path(file.filename or "").suffix

    size = 0
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File exceeds the {MAX_UPLOAD_BYTES} byte upload limit.",
                )
            tmp.write(chunk)
        tmp.flush()

        stream_info = StreamInfo(filename=file.filename, mimetype=file.content_type)
        try:
            result = _state["markitdown"].convert_local(tmp.name, stream_info=stream_info)
        except (UnsupportedFormatException, FileConversionException) as exc:
            _raise_for_conversion_error(exc)

    return _result_to_response(result, source=file.filename)


@app.post(
    "/convert/url",
    response_model=ConvertResponse,
    tags=["convert"],
    dependencies=[Depends(require_api_key)],
)
def convert_url(payload: ConvertUrlRequest) -> ConvertResponse:
    """Fetch a URL (webpage or remote document) and convert it to Markdown."""
    try:
        result = _state["markitdown"].convert_url(payload.url)
    except (UnsupportedFormatException, FileConversionException) as exc:
        _raise_for_conversion_error(exc)

    return _result_to_response(result, source=payload.url)


# Mounted last so it never shadows the API routes above: Starlette matches
# routes in registration order, and StaticFiles(html=True) serves index.html
# at "/" plus any other files in api/static/ (the sassy little frontend).
app.mount(
    "/",
    StaticFiles(directory=Path(__file__).parent / "static", html=True),
    name="static",
)
