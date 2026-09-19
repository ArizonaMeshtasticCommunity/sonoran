# syntax=docker/dockerfile:1
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# uv, named by version and resolved by digest.
#
# `ghcr.io/astral-sh/uv:latest` is a moving target. The tool that
# resolves and installs every dependency in this image was whatever had
# been pushed at the moment of the build, and nothing recorded which one
# ran. The version is written out so a reader knows what this is, and
# the digest is what Docker actually pulls, so the tag cannot be moved
# underneath us. 0.10.1 is the uv that wrote `uv.lock`.
#
# To update: change both halves together, in their own commit.
COPY --from=ghcr.io/astral-sh/uv:0.10.1@sha256:452e02b117acd2d4eb3ba81a607bed9733b101b6c49492e352b1973463389012 /uv /usr/local/bin/uv

# The lockfile decides what ships.
#
# `uv pip install --system .` reads the `>=` floors out of
# pyproject.toml and resolves them again on every build, so two builds
# of the same commit can install different versions of every
# dependency. `uv.lock` was not even in the image, which means no
# dependency audit, SBOM or CVE report describes what actually runs
# here: it describes whatever PyPI was serving that day.
#
# So the lock is exported to a fully pinned, hash-checked requirements
# file and installed from that. `--require-hashes` makes a substituted
# artefact a build failure rather than a silent install, and `--frozen`
# makes a lock that has drifted from pyproject.toml a build failure
# rather than a quiet re-resolution.
#
# This layer is cached on the two files that decide its result, so it
# is rebuilt when the dependencies change and not when the source does.
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project --format requirements-txt \
        -o /tmp/requirements.txt \
    && uv pip install --system --no-cache --require-hashes -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY README.md ./
COPY alembic.ini ./
COPY docs ./docs
# The radio overrides name the antenna and the mast of a node. The
# coverage prediction reads them, so they must be in the image.
COPY config ./config
COPY src ./src

# The project itself, and nothing else.
#
# `--no-deps` is what keeps the install above authoritative: without it
# this step would resolve the `>=` floors a second time and could pull a
# different version over a pinned one, which is the defect this file is
# fixing.
RUN uv pip install --system --no-cache --no-deps .

# Non-root user for security.
RUN useradd --create-home --uid 10001 azmsh
RUN chown -R azmsh:azmsh /app

# The caches for the coverage planner and the coverage map.
#
# Each directory must exist in the image and must belong to the
# application user. Docker gives a new named volume the owner of the
# directory it covers, so without this the volume belongs to root and
# the process cannot write a single page or a single tile.
RUN mkdir -p /var/lib/sonoran/terrain /var/lib/sonoran/landcover /var/lib/sonoran/coverage \
    && chown -R azmsh:azmsh /var/lib/sonoran

USER azmsh

EXPOSE 8000

# Default process: the API. The compose file overrides the command
# for the ingest and jobs services.
CMD ["sonoran-api"]
