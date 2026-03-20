"""Distributed leader election using PostgreSQL advisory locks (shared DB on VM2)."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Distinct lock key for this project (avoid collisions with other apps)
ADVISORY_LOCK_KEY = 558_558_001


def _leader_election_enabled() -> bool:
    return os.environ.get("LEADER_ELECTION", "").lower() in ("1", "true", "yes")


class LeaderSession:
    """Holds a DB connection for the duration of a leader cycle."""

    def __init__(self) -> None:
        self._conn = None

    def acquire(self) -> bool:
        if not _leader_election_enabled():
            return True

        dsn = os.environ.get("DATABASE_URL", "").strip()
        if not dsn:
            logger.warning(
                "LEADER_ELECTION enabled but DATABASE_URL empty; standing by (not leader)"
            )
            return False

        force = os.environ.get("FORCE_LEADER", "").lower()
        if force in ("0", "false", "no"):
            return False
        if force in ("1", "true", "yes"):
            logger.warning("FORCE_LEADER enabled; running as leader without DB lock (demo only)")
            return True

        try:
            import psycopg2
        except ImportError:
            logger.error("psycopg2 not installed; cannot run leader election")
            return False

        try:
            conn = psycopg2.connect(dsn, connect_timeout=5)
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("SELECT pg_try_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
            ok = bool(cur.fetchone()[0])
            if not ok:
                conn.close()
                return False
            self._conn = conn
            return True
        except Exception as e:
            logger.warning("Leader election DB error (standing by): %s", e)
            return False

    def release(self) -> None:
        if not self._conn:
            return
        try:
            cur = self._conn.cursor()
            cur.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))
        except Exception as e:
            logger.warning("Leader unlock error: %s", e)
        try:
            self._conn.close()
        finally:
            self._conn = None
