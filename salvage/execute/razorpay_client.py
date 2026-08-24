"""Razorpay REST client.

docs/02_TECHNICAL_ARCHITECTURE.md section 8:

  httpx with basic auth from the test key pair, 10 second timeout, three attempts with exponential
  backoff and jitter on 429, 5xx and timeouts, no retry on 4xx other than 429. Idempotency: the
  Payment Link reference_id is the recovery case id, so a retried create after a lost response
  fails on duplicate reference and the client then fetches by reference instead of creating again.
  Every request and response id is written to actions and the ledger.

Direct httpx, not the `razorpay` Python SDK. That was Architecture section 17's open item and the
answer is recorded in docs/BUILD_LOG.md: Payment Links plus reference_id idempotency plus retry
classification plus request-id logging all need explicit status-code control, and the SDK hides
the status code behind an exception type.

Request and response shapes were checked against Razorpay's own documentation on 25 August 2026:
  https://razorpay.com/docs/api/payments/payment-links/          endpoints
  https://razorpay.com/docs/api/payments/payment-links/create-standard/   create body and response
  https://razorpay.com/docs/api/payments/payment-links/customise-payment-methods/  options.checkout
  https://razorpay.com/docs/api/orders/                          orders
Every field this client sends appears in that create-standard request body. Nothing is invented.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from salvage.config import Settings, get_settings

BASE_URL = "https://api.razorpay.com/v1"
TIMEOUT_SECONDS = 10.0
MAX_ATTEMPTS = 3

# Razorpay returns its request id in this header. It is logged; request and response bodies with
# customer contact details are not (docs/03_SECURITY_AND_ACCESS.md section 3).
REQUEST_ID_HEADER = "x-razorpay-request-id"


class RazorpayError(RuntimeError):
    """A call failed in a way the executor has to record rather than retry."""

    def __init__(self, message: str, *, status: int | None = None, request_id: str | None = None):
        super().__init__(message)
        self.status = status
        self.request_id = request_id


class DuplicateReference(RazorpayError):
    """A Payment Link with this reference_id already exists.

    This is the idempotency signal. It means a previous create succeeded and its response was
    lost, so the correct move is to fetch by reference rather than create again.
    """


@dataclass
class RazorpayResponse:
    status: int
    body: dict[str, Any]
    request_id: str | None = None
    attempts: int = 1


@dataclass
class RazorpayClient:
    settings: Settings = field(default_factory=get_settings)
    client: httpx.Client | None = None
    base_url: str = BASE_URL
    sleeper: Any = time.sleep

    def __post_init__(self) -> None:
        self.settings.require_razorpay_credentials()
        if self.client is None:
            self.client = httpx.Client(
                timeout=TIMEOUT_SECONDS,
                auth=(self.settings.razorpay_key_id, self.settings.razorpay_key_secret),
            )
            self._owns_client = True
        else:
            self._owns_client = False

    def close(self) -> None:
        if self._owns_client and self.client is not None:
            self.client.close()

    # -- transport ---------------------------------------------------------

    def request(self, method: str, path: str, json_body: dict[str, Any] | None = None):
        """One call, with the documented retry policy and nothing else.

        Retries on 429, 5xx and timeouts. Never retries any other 4xx: a bad request will be bad
        again, and a duplicate reference_id is information rather than a fault.
        """
        assert self.client is not None
        url = f"{self.base_url}{path}"
        last: RazorpayError | None = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self.client.request(method, url, json=json_body)
            except httpx.TimeoutException as exc:
                last = RazorpayError(f"timeout calling {method} {path}: {exc}")
                self._backoff(attempt)
                continue
            except httpx.HTTPError as exc:
                last = RazorpayError(f"transport error calling {method} {path}: {exc}")
                self._backoff(attempt)
                continue

            request_id = response.headers.get(REQUEST_ID_HEADER)
            body = _safe_json(response)

            if response.status_code == 429:
                last = RazorpayError("rate limited", status=429, request_id=request_id)
                self._backoff(attempt)
                continue
            if response.status_code >= 500:
                last = RazorpayError(
                    f"server error {response.status_code}",
                    status=response.status_code,
                    request_id=request_id,
                )
                self._backoff(attempt)
                continue
            if response.status_code >= 400:
                description = _error_description(body)
                if _is_duplicate_reference(body):
                    raise DuplicateReference(
                        description, status=response.status_code, request_id=request_id
                    )
                raise RazorpayError(
                    f"{response.status_code}: {description}",
                    status=response.status_code,
                    request_id=request_id,
                )

            return RazorpayResponse(
                status=response.status_code,
                body=body,
                request_id=request_id,
                attempts=attempt,
            )

        assert last is not None
        raise RazorpayError(
            f"{method} {path} failed after {MAX_ATTEMPTS} attempts: {last}",
            status=last.status,
            request_id=last.request_id,
        )

    def _backoff(self, attempt: int) -> None:
        """Exponential backoff with jitter. Same policy as the LLM client."""
        if attempt >= MAX_ATTEMPTS:
            return
        delay = (2 ** (attempt - 1)) * 0.5
        self.sleeper(delay + random.uniform(0, delay / 2))

    # -- orders ------------------------------------------------------------

    def fetch_order(self, order_id: str) -> RazorpayResponse:
        """https://razorpay.com/docs/api/orders/ . The unpaid check before every action."""
        return self.request("GET", f"/orders/{order_id}")

    def create_order(
        self,
        *,
        amount: int,
        receipt: str,
        currency: str = "INR",
        notes: dict[str, str] | None = None,
    ) -> RazorpayResponse:
        return self.request(
            "POST",
            "/orders",
            {
                "amount": int(amount),
                "currency": currency,
                "receipt": receipt[:40],
                "notes": notes or {},
            },
        )

    # -- payment links -----------------------------------------------------

    def create_payment_link(
        self,
        *,
        amount: int,
        reference_id: str,
        expire_by: int,
        description: str,
        callback_url: str | None = None,
        checkout_display: dict[str, Any] | None = None,
        notes: dict[str, str] | None = None,
    ) -> RazorpayResponse:
        """Create a Payment Link for exactly `amount` paise.

        `amount` comes from the order row, never from model output; see
        docs/03_SECURITY_AND_ACCESS.md section 6 and the structural tests in
        tests/property/test_policy_invariants.py.

        `reference_id` is the recovery case id, which is what makes a retried create idempotent:
        Razorpay rejects a duplicate reference_id, and the caller then fetches by reference.

        notify.sms and notify.email are false in every environment (Architecture section 12).
        Razorpay never contacts the customer on Salvage's behalf; the simulated channel does.
        """
        body: dict[str, Any] = {
            "amount": int(amount),
            "currency": "INR",
            "accept_partial": False,
            "reference_id": reference_id[:40],
            "description": description[:255],
            "expire_by": int(expire_by),
            "notify": {"sms": False, "email": False},
            "reminder_enable": False,
            "notes": notes or {},
        }
        if callback_url:
            body["callback_url"] = callback_url
            body["callback_method"] = "get"
        if checkout_display:
            # https://razorpay.com/docs/api/payments/payment-links/customise-payment-methods/
            body["options"] = {"checkout": {"config": {"display": checkout_display}}}
        return self.request("POST", "/payment_links", body)

    def fetch_payment_link(self, link_id: str) -> RazorpayResponse:
        return self.request("GET", f"/payment_links/{link_id}")

    def fetch_payment_link_by_reference(self, reference_id: str) -> RazorpayResponse | None:
        """The idempotency fallback after a duplicate reference.

        Razorpay's list endpoint filters by reference_id, so a create whose response was lost can
        be recovered without creating a second link for the same order.
        """
        response = self.request("GET", f"/payment_links?reference_id={reference_id[:40]}")
        items = response.body.get("payment_links") or []
        if not items:
            return None
        return RazorpayResponse(
            status=response.status,
            body=items[0],
            request_id=response.request_id,
            attempts=response.attempts,
        )

    def cancel_payment_link(self, link_id: str) -> RazorpayResponse:
        return self.request("POST", f"/payment_links/{link_id}/cancel")


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {"raw": response.text[:500]}
    return body if isinstance(body, dict) else {"body": body}


def _error_description(body: dict[str, Any]) -> str:
    error = body.get("error")
    if isinstance(error, dict):
        return str(error.get("description") or error.get("code") or body)[:300]
    return str(body)[:300]


def _is_duplicate_reference(body: dict[str, Any]) -> bool:
    """Whether a 4xx is Razorpay rejecting a repeated reference_id.

    Razorpay does not publish a machine-readable code for this case, only a description, so the
    detection is a substring match. That is the one assumption in this client and it is isolated
    here: if the wording changes, only this function is wrong, and the failure mode is a refused
    create rather than a duplicate link, which is the safe direction.
    """
    description = _error_description(body).lower()
    return "reference_id" in description and (
        "already" in description or "duplicate" in description or "unique" in description
    )
