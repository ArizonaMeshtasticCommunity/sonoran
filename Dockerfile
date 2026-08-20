# syntax=docker/dockerfile:1
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Install uv for fast, locked dependency installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml ./
COPY README.md ./
COPY alembic.ini ./
COPY docs ./docs
# The radio overrides name the antenna and the mast of a node. The
# coverage prediction reads them, so they must be in the image.
COPY config ./config
COPY src ./src
RUN uv pip install --system --no-cache .

# Non-root user for security.
RUN useradd --create-home --uid 10001 azmsh
RUN chown -R azmsh:azmsh /app

# The caches for the coverage planner and the coverage map.
#
# This directory must exist in the image and must belong to the
# application user. Docker gives a new named volume the owner of the
# directory it covers, so without this the volume belongs to root and
# the process cannot write a single page.
RUN mkdir -p /var/lib/sonoran/terrain /var/lib/sonoran/landcover /var/lib/sonoran/coverage \
    && chown -R azmsh:azmsh /var/lib/sonoran

USER azmsh

EXPOSE 8000

# Default process: the API. The compose file overrides the command
# for the ingest and jobs services.
CMD ["sonoran-api"]
