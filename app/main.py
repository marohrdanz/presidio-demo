"""FastAPI service that rejects uploaded files containing suspected PHI."""

from collections import Counter
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.columns import check_columns
from app.config import get_settings
from app.extract import ExtractionError, UnsupportedFileType, extract
from app.scanner import PhiScanner


class FindingOut(BaseModel):
    entity_type: str
    score: float
    # Character offsets for text findings; None for column-heading findings.
    start: int | None = None
    end: int | None = None
    # The offending heading, for PHI_COLUMN findings. Headings are labels
    # like "dob", not values, so echoing them doesn't leak PHI.
    column: str | None = None


class ScanResponse(BaseModel):
    filename: str
    status: str  # "accepted" | "rejected"
    contains_phi: bool
    entity_counts: dict[str, int]
    # Matched text is never echoed back, only its type and location, so the
    # response itself doesn't leak PHI into client logs.
    findings: list[FindingOut]


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.scanner = PhiScanner(settings)  # loads the spaCy model once
    yield


app = FastAPI(
    title="PHI Upload Scanner",
    description="Scans uploaded files with Microsoft Presidio and rejects any that contain suspected PHI.",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/scan",
    response_model=ScanResponse,
    responses={
        422: {"model": ScanResponse, "description": "File rejected: suspected PHI found"},
        413: {"description": "File too large"},
        415: {"description": "Unsupported file type"},
        400: {"description": "File could not be read"},
    },
)
async def scan_file(request: Request, file: UploadFile = File(...)):
    settings = request.app.state.settings
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            413,
            f"File exceeds the {settings.max_upload_bytes}-byte limit",
        )

    filename = file.filename or ""
    try:
        extracted = await run_in_threadpool(extract, filename, data)
    except UnsupportedFileType as exc:
        raise HTTPException(415, str(exc)) from exc
    except ExtractionError as exc:
        raise HTTPException(400, str(exc)) from exc

    result = await run_in_threadpool(request.app.state.scanner.scan, extracted.text)
    findings = [FindingOut(**vars(f)) for f in result.findings]
    if settings.check_columns:
        findings += [
            FindingOut(entity_type="PHI_COLUMN", score=1.0 if c.strength == "strong" else 0.8, column=c.column)
            for c in check_columns(extracted.columns)
        ]
    contains_phi = bool(findings)
    body = ScanResponse(
        filename=filename,
        status="rejected" if contains_phi else "accepted",
        contains_phi=contains_phi,
        entity_counts=dict(Counter(f.entity_type for f in findings)),
        findings=findings,
    )
    code = 422 if contains_phi else 200
    return JSONResponse(status_code=code, content=body.model_dump())
