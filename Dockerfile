# syntax=docker/dockerfile:1
FROM python:3.14-slim-trixie@sha256:22eafb370920ad8b429e0aec3fff433e0669968519f5d60469d83729c138b28b AS python-base

FROM python-base AS dependencies
RUN python -m pip install --no-cache-dir uv==0.13.10
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
RUN uv sync --locked --no-dev --no-default-groups --no-install-project

FROM python-base AS runtime
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends -y tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 boilerio \
    && useradd --uid 10001 --gid boilerio --home-dir /app --no-create-home boilerio \
    && mkdir -p /var/lib/boilerio \
    && chown boilerio:boilerio /var/lib/boilerio
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001:10001

# --- Wheel path: release image built from a prebuilt wheel ---

# Requires --build-context wheel-input=<directory containing boilerio-*.whl>.
FROM scratch AS wheel-input

# Venv with third-party deps plus the wheel (intermediate).
FROM dependencies AS venv-wheel
COPY --from=wheel-input /boilerio-*.whl /wheels/
RUN uv pip install --no-deps --no-index /wheels/boilerio-*.whl && uv pip check

# Release image.
FROM runtime AS image-wheel
COPY --from=venv-wheel /app/.venv /app/.venv
CMD ["boilerio-controller"]

# --- Source path: image built from the checkout ---

# Venv with third-party deps plus the project installed from source (intermediate).
FROM dependencies AS venv-source
COPY boilerio ./boilerio
RUN uv sync --locked --no-dev --no-default-groups --no-editable

# Checkout-based image. Must remain the LAST stage: it is the default
# target for a bare `docker build`.
FROM runtime AS image-source
COPY --from=venv-source /app/.venv /app/.venv
CMD ["boilerio-controller"]