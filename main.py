# Copyright (c) Microsoft. All rights reserved.
"""Entry point running the A2A agent service with uvicorn."""

from __future__ import annotations

import uvicorn

from agent.settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
