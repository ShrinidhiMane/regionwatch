"""Run with:  python -m regionwatch --config config/targets.local.yaml"""

from __future__ import annotations

import argparse
import logging

import uvicorn

from .api import create_app
from .config import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="RegionWatch multi-region health monitor")
    parser.add_argument("--config", default="config/targets.local.yaml")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per probe is too noisy
    settings = load_settings(args.config)
    uvicorn.run(create_app(settings), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
