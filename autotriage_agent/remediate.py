"""Apply automated remediation actions based on structured diagnoses."""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)


def maybe_remediate(diagnosis: dict[str, Any]) -> None:
    if diagnosis.get("severity") in ("ok", "low"):
        return

    admin_base = os.environ.get("PAYMENTS_ADMIN_URL", "").rstrip("/")
    token = os.environ.get("ADMIN_TOKEN", "")

    for action in diagnosis.get("actions", []):
        if action.get("type") != "reset_payments_simulation":
            continue
        if not admin_base or not token:
            logger.warning("Remediation skipped: PAYMENTS_ADMIN_URL or ADMIN_TOKEN not set")
            continue
        url = f"{admin_base}/admin/reset"
        try:
            r = requests.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if r.ok:
                logger.info("Remediation: payments /admin/reset succeeded (%s)", r.status_code)
            else:
                logger.warning("Remediation failed: %s %s", r.status_code, r.text[:200])
        except Exception as e:
            logger.warning("Remediation request error: %s", e)
