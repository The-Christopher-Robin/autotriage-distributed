"""HTTP client with tracing, retries, and structured logging for cross-service calls.

Wraps ``requests`` with:
  - Automatic retries with exponential backoff (configurable)
  - Per-request timeout
  - OpenTelemetry trace-context propagation (via RequestsInstrumentor, already
    wired in ``instrumentation.py``)
  - Structured logging of request/response metadata
  - Error classification (transient vs permanent)
"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


class TransientError(Exception):
    """Raised for errors that are likely to succeed on retry."""


class PermanentError(Exception):
    """Raised for errors that will not benefit from retrying."""


def classify_error(exc: Exception | None = None, status_code: int | None = None) -> str:
    """Return ``'transient'`` or ``'permanent'`` for a given exception or HTTP status."""
    if status_code is not None and status_code in TRANSIENT_STATUS_CODES:
        return "transient"
    if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return "transient"
    if isinstance(exc, requests.exceptions.HTTPError):
        resp = getattr(exc, "response", None)
        if resp is not None and resp.status_code in TRANSIENT_STATUS_CODES:
            return "transient"
    return "permanent"


def _build_session(
    retries: int = 3,
    backoff_factor: float = 0.5,
    status_forcelist: tuple[int, ...] | None = None,
) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=list(status_forcelist or TRANSIENT_STATUS_CODES),
        allowed_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


_default_session: requests.Session | None = None


def _session() -> requests.Session:
    global _default_session
    if _default_session is None:
        _default_session = _build_session()
    return _default_session


def request(
    method: str,
    url: str,
    *,
    timeout: int = 10,
    retries: int | None = None,
    json: Any | None = None,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> requests.Response:
    """Make an HTTP request with retries, logging, and error classification.

    Parameters
    ----------
    method : str
        HTTP method (GET, POST, etc.)
    url : str
        Full URL.
    timeout : int
        Per-attempt timeout in seconds.
    retries : int | None
        Override default retry count (None = use session default).
    json, headers, **kwargs
        Forwarded to ``requests.Session.request``.

    Returns
    -------
    requests.Response
        The response object (caller should check ``.ok`` / ``.status_code``).

    Raises
    ------
    TransientError
        After exhausting retries on a transient failure.
    PermanentError
        On a non-retryable failure (e.g. 4xx).
    """
    sess = _build_session(retries=retries) if retries is not None else _session()
    merged_headers = {"Content-Type": "application/json"}
    if headers:
        merged_headers.update(headers)

    start = time.monotonic()
    try:
        resp = sess.request(
            method, url, json=json, headers=merged_headers, timeout=timeout, **kwargs
        )
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            "HTTP %s %s -> %d (%.1f ms)",
            method.upper(),
            url,
            resp.status_code,
            elapsed_ms,
        )
        if not resp.ok:
            kind = classify_error(status_code=resp.status_code)
            logger.warning(
                "HTTP error %d on %s %s [%s]: %s",
                resp.status_code,
                method.upper(),
                url,
                kind,
                resp.text[:300],
            )
        return resp
    except requests.exceptions.RequestException as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        kind = classify_error(exc=exc)
        logger.error(
            "HTTP %s %s failed after %.1f ms [%s]: %s",
            method.upper(),
            url,
            elapsed_ms,
            kind,
            exc,
        )
        if kind == "transient":
            raise TransientError(str(exc)) from exc
        raise PermanentError(str(exc)) from exc


def get(url: str, **kwargs: Any) -> requests.Response:
    return request("GET", url, **kwargs)


def post(url: str, **kwargs: Any) -> requests.Response:
    return request("POST", url, **kwargs)
