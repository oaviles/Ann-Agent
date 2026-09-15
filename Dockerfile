# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Build stage: install dependencies into an isolated virtual environment.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Runtime stage: minimal image running as a non-root user.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    HOST=0.0.0.0 \
    PORT=8000

RUN groupadd --system --gid 1001 agent \
    && useradd --system --uid 1001 --gid agent --create-home agent

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=agent:agent agent ./agent
COPY --chown=agent:agent app.py main.py ./

USER agent

EXPOSE 8000

CMD ["python", "main.py"]
