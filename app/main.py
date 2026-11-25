"""HTTP API and static UI for the Receipt & UPI Expense Analyzer.

Privacy: uploaded images are read into memory, sent to Gemini, and discarded.
Nothing is written to disk or a database, and image/amount data is never logged.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .budget import analyze
from .categorizer import CATEGORIES, categorize
from .config import get_settings
from .extractor import ExtractionError, extract_receipt
from .security import SECURITY_HEADERS, RateLimiter, UploadError, sanitize_text, validate_upload

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
MAX_AMOUNT = 10_000_000

# docs/openapi are switched off: fewer public endpoints to expose.
app = FastAPI(title="Receipt & UPI Expense Analyzer", docs_url=None, redoc_url=None, openapi_url=None)
# Extraction costs money (AI calls), so it has a tight limit; analysis is cheap.
_extract_limiter = RateLimiter(get_settings().rate_limit_per_minute)
_analyze_limiter = RateLimiter(120)


# ------------------------------------------------------------ middleware


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def _client_key(request: Request) -> str:
    # Cloud Run appends the real client IP as the LAST X-Forwarded-For entry;
    # earlier entries can be forged by the client.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _check_rate_limit(request: Request, limiter: RateLimiter) -> None:
    if not limiter.allow(_client_key(request)):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a minute.")


# ------------------------------------------------------------ schemas


class ExpenseIn(BaseModel):
    vendor: str = Field(min_length=1, max_length=80)
    amount: float = Field(gt=0, le=MAX_AMOUNT)
    category: str
    date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")

    @field_validator("vendor")
    @classmethod
    def clean_vendor(cls, value: str) -> str:
        cleaned = sanitize_text(value, 80)
        if not cleaned:
            raise ValueError("vendor is empty")
        return cleaned

    @field_validator("category")
    @classmethod
    def known_category(cls, value: str) -> str:
        if value not in CATEGORIES:
            raise ValueError("unknown category")
        return value

    @field_validator("date")
    @classmethod
    def real_date(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            date.fromisoformat(value)  # raises ValueError for e.g. 2026-02-31
        return value


class AnalyzeIn(BaseModel):
    expenses: List[ExpenseIn] = Field(max_length=500)
    budgets: Dict[str, float] = Field(default_factory=dict, max_length=len(CATEGORIES))
    month: Optional[str] = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")

    @field_validator("budgets")
    @classmethod
    def valid_budgets(cls, value: Dict[str, float]) -> Dict[str, float]:
        for category, amount in value.items():
            if category not in CATEGORIES:
                raise ValueError("unknown category in budgets")
            if not 0 <= amount <= MAX_AMOUNT:
                raise ValueError("budget out of range")
        return value


# ------------------------------------------------------------ routes


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/config")
def public_config() -> dict:
    """Lets the UI know whether receipt reading is available and its limits."""
    settings = get_settings()
    return {
        "categories": list(CATEGORIES),
        "extraction_enabled": bool(settings.gemini_api_key),
        "max_files": settings.max_files,
        "max_upload_mb": settings.max_upload_bytes // (1024 * 1024),
    }


@app.get("/api/categorize")
def categorize_vendor(request: Request, vendor: str = Query(min_length=1, max_length=80)) -> dict:
    """Rule-based category for a vendor typed by hand (no AI call, no cost)."""
    _check_rate_limit(request, _analyze_limiter)
    return {"category": categorize(sanitize_text(vendor, 80))}


@app.post("/api/extract")
async def extract(request: Request, files: List[UploadFile] = File(...)) -> JSONResponse:
    _check_rate_limit(request, _extract_limiter)
    settings = get_settings()

    if not settings.gemini_api_key:
        raise HTTPException(status_code=503, detail="Receipt reading is not configured. Add expenses manually instead.")
    if len(files) > settings.max_files:
        raise HTTPException(status_code=400, detail=f"Upload at most {settings.max_files} images at a time.")

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.max_files * settings.max_upload_bytes + 1_000_000:
        raise HTTPException(status_code=413, detail="The upload is too large.")

    async def process(index: int, upload: UploadFile) -> dict:
        try:
            data = await upload.read(settings.max_upload_bytes + 1)  # bounded read
            mime = validate_upload(data, settings.max_upload_bytes)
            expense = await run_in_threadpool(extract_receipt, data, mime, settings)
            return {"index": index, "ok": True, "expense": expense}
        except (UploadError, ExtractionError) as err:
            return {"index": index, "ok": False, "error": str(err)}
        except Exception:  # noqa: BLE001 - never leak internals to the client
            logging.getLogger("analyzer").exception("Unexpected extraction failure")
            return {"index": index, "ok": False, "error": "Something went wrong reading this image."}
        finally:
            await upload.close()

    results = await asyncio.gather(*(process(i, f) for i, f in enumerate(files)))
    return JSONResponse({"results": results})


@app.post("/api/analyze")
def analyze_budget(payload: AnalyzeIn, request: Request) -> dict:
    _check_rate_limit(request, _analyze_limiter)
    expenses = [e.model_dump() for e in payload.expenses]
    return analyze(expenses, payload.budgets, payload.month)


# ------------------------------------------------------------ static UI


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
