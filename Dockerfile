# Build the installed application environment.
FROM python:3.14-slim-trixie@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS builder

RUN python -m pip install --no-cache-dir uv==0.11.14
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY boilerio ./boilerio
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
RUN uv sync --locked --no-dev --no-default-groups --no-editable

# Runtime image.
FROM python:3.14-slim-trixie@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends -y tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 boilerio \
    && useradd --uid 10001 --gid boilerio --home-dir /app --no-create-home boilerio \
    && mkdir -p /var/lib/boilerio \
    && chown boilerio:boilerio /var/lib/boilerio
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001:10001

CMD ["scheduler"]
