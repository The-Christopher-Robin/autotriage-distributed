"""Auto-triage agent: leader election, Prometheus/Jaeger diagnosis, optional remediation."""
from __future__ import annotations

import json
import logging
import os
import sys
import time

from diagnose import run_diagnosis
from leader import LeaderSession
from remediate import maybe_remediate

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("autotriage_agent")


def main() -> None:
    interval = int(os.environ.get("AGENT_INTERVAL_SEC", "30"))
    logger.info("autotriage_agent starting (interval=%ss)", interval)

    while True:
        session = LeaderSession()
        if session.acquire():
            try:
                diagnosis = run_diagnosis()
                logger.info("diagnosis: %s", json.dumps(diagnosis, default=str)[:2000])
                maybe_remediate(diagnosis)
            finally:
                session.release()
        else:
            logger.debug("Not leader this cycle; sleeping")

        time.sleep(interval)


if __name__ == "__main__":
    main()
