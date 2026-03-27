"""
service/authorize_service.py
─────────────────────────────
Calls the Authorize.net getTransactionDetails API for a given transId
and returns the transactionStatus string.

API docs:
    https://developer.authorize.net/api/reference/#transaction-reporting-get-transaction-details
"""

import httpx

from common.logger import get_logger
from config.settings import settings

logger = get_logger(__name__)

# Timeout config (seconds)
_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)


def _build_payload(trans_id: str) -> dict:
    return {
        "getTransactionDetailsRequest": {
            "merchantAuthentication": {
                "name": settings.AUTHORIZE_NET_API_LOGIN_ID,
                "transactionKey": settings.AUTHORIZE_NET_TRANSACTION_KEY,
            },
            "transId": str(trans_id),
        }
    }


def get_transaction_status(trans_id: str) -> str:
    """
    Fetches the transactionStatus for a given Authorize.net transaction ID.

    Returns the status string (e.g. 'settledSuccessfully', 'voided', etc.)
    or 'FETCH_ERROR' / 'NOT_FOUND' on failure so the report row is never
    blocked by a single bad call.
    """
    if not trans_id:
        logger.warning("Empty trans_id supplied — skipping Authorize.net call.")
        return "N/A"

    payload = _build_payload(trans_id)
    logger.debug("Calling Authorize.net for transId=%s", trans_id)

    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            response = client.post(
                settings.AUTHORIZE_NET_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()

        data: dict = response.json()

        # Authorize.net wraps the response in a messages + transaction block
        messages = data.get("messages", {})
        result_code = messages.get("resultCode", "")

        if result_code != "Ok":
            error_text = (
                messages.get("message", [{}])[0].get("text", "Unknown error")
            )
            logger.error(
                "Authorize.net error for transId=%s: %s", trans_id, error_text
            )
            return "FETCH_ERROR"

        transaction = data.get("transaction", {})
        status = transaction.get("transactionStatus", "NOT_FOUND")
        logger.debug("transId=%s → status=%s", trans_id, status)
        return status

    except httpx.HTTPStatusError as exc:
        logger.error(
            "HTTP %s from Authorize.net for transId=%s: %s",
            exc.response.status_code,
            trans_id,
            exc,
        )
        return "FETCH_ERROR"

    except httpx.RequestError as exc:
        logger.error(
            "Network error calling Authorize.net for transId=%s: %s",
            trans_id,
            exc,
        )
        return "FETCH_ERROR"

    except Exception as exc:
        logger.exception(
            "Unexpected error fetching Authorize.net status for transId=%s: %s",
            trans_id,
            exc,
        )
        return "FETCH_ERROR"
