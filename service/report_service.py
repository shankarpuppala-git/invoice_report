"""
service/report_service.py
──────────────────────────
Pipeline:
    1.  Resolve application name → tenant_id  (1 DB query)
    2.  Fetch credit-card orders               (1 DB query, payment_type from .env)
    3.  Bulk-resolve ext_user_id → user_id     (1 DB query for all rows at once)
    4.  Parallel Authorize.net lookups         (ThreadPoolExecutor, not sequential)
    5.  Build Excel in memory and return BytesIO

Performance notes
─────────────────
• Steps 1-3 are all single DB round-trips (no N+1 queries).
• Step 4 runs all Authorize.net calls concurrently up to AUTHORIZE_MAX_WORKERS
  (Authorize.net has no batch API, but parallel HTTP slashes wall-clock time).
• Nothing is written to disk.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime
from io import BytesIO
from typing import Optional

from common.logger import get_logger
from config.settings import settings
from db.db_pool import get_connection
from service.authorize_service import get_transaction_status
from sheets.excel_generator import generate_excel

logger = get_logger(__name__)


# ─── Data model ──────────────────────────────────────────────────────────────

@dataclass
class OrderRow:
    ext_order_number: str
    ordered_date: Optional[datetime]
    order_total: Optional[float]
    invoiced_amount: Optional[float]
    payment_reference_no: Optional[str]
    payment_status: Optional[str]
    transaction_status: str = ""
    invoice_number: Optional[str] = None
    invoiced_date: Optional[datetime] = None
    customer_number: Optional[str] = None
    # Populated via bulk auth_users lookup (ext_user_id → user_id)
    email: Optional[str] = None


@dataclass
class ReportResult:
    application: str
    start_date: date
    end_date: date
    tenant_id: int
    tenant_name: str
    orders: list[OrderRow] = field(default_factory=list)

    @property
    def total_credit_card_orders(self) -> int:
        return len(self.orders)

    @property
    def total_invoiced(self) -> int:
        return sum(1 for o in self.orders if o.invoice_number)

    @property
    def total_settled(self) -> int:
        return sum(
            1 for o in self.orders
            if o.transaction_status.lower() == "settledsuccessfully"
        )

    @property
    def total_voided(self) -> int:
        return sum(
            1 for o in self.orders
            if o.transaction_status.lower() == "voided"
        )

    @property
    def total_pending(self) -> int:
        # Counts orders with transaction statuses that indicate pending settlement
        return sum(
            1 for o in self.orders
            if o.transaction_status.lower() == "capturedpendingsettlement"
        )


# ─── DB helpers ──────────────────────────────────────────────────────────────

def _get_tenant_id(application_name: str) -> int:
    """Single query: application name → tenant id."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tenant FROM pzv_aftermarket.application WHERE name = %s LIMIT 1;",
                (application_name,),
            )
            row = cur.fetchone()

    if not row:
        raise ValueError(f"Application '{application_name}' not found.")

    tenant_id = int(row["tenant"])
    logger.info("Resolved application='%s' → tenant_id=%d", application_name, tenant_id)
    return tenant_id


def _get_tenant_name(tenant_id: int) -> str:
    """Single query: tenant id → tenant display_name."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT display_name FROM pzv_aftermarket.tenant WHERE id = %s LIMIT 1;",
                (tenant_id,),
            )
            row = cur.fetchone()

    if not row:
        raise ValueError(f"Tenant '{tenant_id}' not found.")

    tenant_name = str(row["display_name"])
    logger.info("Resolved tenant_id=%d → tenant_name='%s'", tenant_id, tenant_name)
    return tenant_name


def _fetch_orders(
    tenant_id: int,
    start_date: date,
    end_date: date,
    payment_types: list[str],
) -> list[dict]:
    """
    Single query: fetch invoiced orders filtered by configurable payment types.
    payment_types comes from PAYMENT_TYPES in .env — never hardcoded.
    """
    # Build a dynamic IN clause — safe because values come from our own .env
    placeholders = ", ".join(["%s"] * len(payment_types))
    sql = f"""
        SELECT
            pso.ext_order_number,
            pso.user_id_order_initiated,
            pso.customer_number,
            pso.order_total,
            pso.invoiced_amount,
            pso.created_on,
            pso.order_date,
            pso.invoiced_date,
            pso.payment_reference_no,
            pso.payment_status,
            pso.invoice_number
        FROM pzv_aftermarket.pzv_sales_order pso
        WHERE pso.tenant = %s
          AND pso.invoiced_date >= %s
          AND pso.invoiced_date <  %s + INTERVAL '1 day'
          AND pso.payment_type IN ({placeholders})
          AND pso.invoice_number IS NOT NULL
        ORDER BY pso.invoiced_date ASC, pso.ext_order_number ASC;
    """
    params = [tenant_id, start_date, end_date] + payment_types

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    logger.info(
        "Fetched %d order(s) | tenant=%d | %s → %s | payment_types=%s",
        len(rows), tenant_id, start_date, end_date, payment_types,
    )
    return [dict(r) for r in rows]


def _bulk_fetch_user_emails(ext_user_ids: list[str]) -> dict[str, str]:
    """
    Single query: ext_user_id list → {ext_user_id: user_id} map.

    auth_users.user_id stores the actual email (e.g. sacramentoibs@genpt.com).
    We fetch all at once — never row-by-row.
    """
    if not ext_user_ids:
        return {}

    unique_ids = list(set(ext_user_ids))
    placeholders = ", ".join(["%s"] * len(unique_ids))

    sql = f"""
        SELECT ext_user_id, user_id
        FROM pzv_aftermarket.auth_users
        WHERE ext_user_id IN ({placeholders});
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, unique_ids)
            rows = cur.fetchall()

    mapping = {row["ext_user_id"]: row["user_id"] for row in rows}
    logger.info(
        "Bulk user lookup | requested=%d unique | resolved=%d",
        len(unique_ids), len(mapping),
    )
    return mapping


# ─── Authorize.net parallel fetcher ──────────────────────────────────────────

def _fetch_transaction_statuses_parallel(
    trans_ids: list[str],
) -> dict[str, str]:
    """
    Fetches Authorize.net transaction statuses concurrently.

    Authorize.net has no batch API — each transId needs its own HTTP call.
    Running them in a thread pool cuts wall-clock time from N×latency to
    roughly max_latency (typically 1-2 s instead of N×2 s).
    """
    max_workers = min(settings.AUTHORIZE_MAX_WORKERS, len(trans_ids))
    results: dict[str, str] = {}

    logger.info(
        "Fetching %d Authorize.net statuses | workers=%d",
        len(trans_ids), max_workers,
    )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_id = {
            pool.submit(get_transaction_status, tid): tid
            for tid in trans_ids
        }
        for future in as_completed(future_to_id):
            tid = future_to_id[future]
            try:
                results[tid] = future.result()
                logger.debug("transId=%s → %s", tid, results[tid])
            except Exception as exc:
                logger.error("Authorize.net error for transId=%s: %s", tid, exc)
                results[tid] = "FETCH_ERROR"

    logger.info("Authorize.net lookups complete | %d statuses fetched", len(results))
    return results


# ─── Main orchestrator ───────────────────────────────────────────────────────

def generate_report(
    application: str,
    start_date: date,
    end_date: date,
) -> BytesIO:
    """
    Runs the full pipeline and returns a BytesIO Excel workbook.
    Nothing is saved to disk.
    """
    logger.info("=" * 60)
    logger.info(
        "REPORT REQUEST | application=%s | %s → %s",
        application, start_date, end_date,
    )
    logger.info("=" * 60)

    # ── Step 1: Resolve tenant ────────────────────────────────────
    tenant_id = _get_tenant_id(application)
    tenant_name = _get_tenant_name(tenant_id)

    # ── Step 2: Fetch orders (payment types from .env) ────────────
    payment_types = _parse_payment_types()
    logger.info("Payment types filter: %s", payment_types)
    raw_orders = _fetch_orders(tenant_id, start_date, end_date, payment_types)

    if not raw_orders:
        raise ValueError(
            f"No orders found for application='{application}' "
            f"between {start_date} and {end_date} "
            f"with payment_types={payment_types}."
        )

    # ── Step 3: Bulk ext_user_id → user_id lookup (single query) ─
    ext_user_ids = [
        r["user_id_order_initiated"]
        for r in raw_orders
        if r.get("user_id_order_initiated")
    ]
    user_email_map = _bulk_fetch_user_emails(ext_user_ids)

    # ── Step 4: Parallel Authorize.net lookups ────────────────────
    trans_ids = [
        str(r.get("payment_reference_no") or "")
        for r in raw_orders
    ]
    # Deduplicate for the API calls, then re-expand per order
    unique_trans_ids = list({tid for tid in trans_ids if tid})
    status_map = _fetch_transaction_statuses_parallel(unique_trans_ids)

    # ── Step 5: Assemble OrderRow list ────────────────────────────
    order_rows: list[OrderRow] = []
    for raw in raw_orders:
        tid = str(raw.get("payment_reference_no") or "")
        ext_uid = raw.get("user_id_order_initiated") or ""

        order_rows.append(OrderRow(
            ext_order_number=str(raw.get("ext_order_number", "")),
            ordered_date=raw.get("order_date") or raw.get("created_on"),
            order_total=_to_float(raw.get("order_total")),
            invoiced_amount=_to_float(raw.get("invoiced_amount")),
            payment_reference_no=tid,
            payment_status=str(raw.get("payment_status", "")),
            transaction_status=status_map.get(tid, "N/A"),
            invoice_number=raw.get("invoice_number"),
            invoiced_date=raw.get("invoiced_date"),
            customer_number=raw.get("customer_number"),
            # Mapped from auth_users; falls back to ext_user_id if not found
            email=user_email_map.get(ext_uid) or ext_uid or "",
        ))

    result = ReportResult(
        application=application,
        start_date=start_date,
        end_date=end_date,
        tenant_id=tenant_id,
        tenant_name=tenant_name,
        orders=order_rows,
    )

    # ── Step 6: Build Excel in memory ─────────────────────────────
    excel_io: BytesIO = generate_excel(result)

    logger.info("=" * 60)
    logger.info(
        "REPORT COMPLETE | orders=%d | settled=%d | pending=%d | voided=%d",
        result.total_credit_card_orders,
        result.total_settled,
        result.total_pending,
        result.total_voided,
    )
    logger.info("=" * 60)

    return excel_io


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _parse_payment_types() -> list[str]:
    """Reads PAYMENT_TYPES from .env. Returns a non-empty list."""
    raw = getattr(settings, "PAYMENT_TYPES", "credit-card") or "credit-card"
    types = [t.strip() for t in raw.split(",") if t.strip()]
    return types if types else ["credit-card"]


def _to_float(value) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None