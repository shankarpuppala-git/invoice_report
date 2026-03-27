"""
main.py
────────
FastAPI application entry point for the Betts Invoice Report service.

Start locally:
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload

Swagger UI (dev):
    http://localhost:8000/docs
"""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from common.logger import get_logger
from config.settings import settings
from controller.report_controller import router as report_router
from db.db_pool import close_pool, init_pool

logger = get_logger(__name__)


# ─── Lifespan (startup / shutdown) ───────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs once at startup and once at shutdown.
    Manages the PostgreSQL connection pool lifecycle.
    """
    logger.info("=== Betts Report Service starting up (env=%s) ===", settings.APP_ENV)
    init_pool()
    yield
    logger.info("=== Betts Report Service shutting down ===")
    close_pool()


# ─── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Betts Truck Parts — Invoice Report API",
    description=(
        "Generates Excel invoice reports for Betts Truck Parts by fetching "
        "credit-card orders from the database and enriching them with "
        "Authorize.net transaction statuses."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS (adjust origins for production) ─────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(report_router, prefix="/api/v1")


# ─── Root ─────────────────────────────────────────────────────────────────────

@app.get("/", tags=["Root"])
def root():
    return {
        "service": "Betts Invoice Report API",
        "version": "1.0.0",
        "docs": "/docs",
    }


# ─── Dev runner ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=(settings.APP_ENV != "production"),
        log_level=settings.LOG_LEVEL.lower(),
    )
