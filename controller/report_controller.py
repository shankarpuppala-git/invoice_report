"""
controller/report_controller.py
────────────────────────────────
POST /invoice/reports/generate
    Body: { "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD", "application": "btp-NA" }
    Returns the Excel file directly — Postman Send & Download triggers Save File dialog.
"""

from __future__ import annotations

from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, field_validator

from common.logger import get_logger
from service.report_service import generate_report

logger = get_logger(__name__)
router = APIRouter(prefix="/invoice/reports", tags=["Reports"])


# ─── Request schema ───────────────────────────────────────────────────────────

class GenerateReportRequest(BaseModel):
    start_date: date
    end_date: date
    application: str

    @field_validator("end_date")
    @classmethod
    def end_must_be_after_start(cls, end: date, info) -> date:
        start = info.data.get("start_date")
        if start and end < start:
            raise ValueError("end_date must be on or after start_date")
        return end

    @field_validator("application")
    @classmethod
    def application_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("application field must not be empty")
        return v.strip()


# ─── Endpoint ─────────────────────────────────────────────────────────────────

@router.post(
    "/generate",
    summary="Generate Invoice Report",
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}
            },
            "description": "Excel file download",
        }
    },
)
def generate_report_endpoint(request: GenerateReportRequest) -> Response:
    logger.info(
        "POST /invoice/reports/generate | application=%s | %s → %s",
        request.application,
        request.start_date,
        request.end_date,
    )

    try:
        excel_io = generate_report(
            application=request.application,
            start_date=request.start_date,
            end_date=request.end_date,
        )
    except ValueError as exc:
        logger.warning("Bad request: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error. Check logs.")

    filename = "invoiced-orders-by-daterange.xlsx"
    content = excel_io.getvalue()

    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{quote(filename)}"',
            "Content-Length": str(len(content)),
        },
    )


# ─── Health ───────────────────────────────────────────────────────────────────

@router.get("/health", summary="Health Check", tags=["Health"])
def health() -> dict:
    return {"status": "ok", "service": "betts-report"}