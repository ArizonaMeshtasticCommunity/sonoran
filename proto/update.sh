#!/usr/bin/env bash
# Regenerate Python protobuf modules from the pinned upstream commit.
# See docs/QA.md section 6.
set -euo pipefail

REV="$(cat proto/UPSTREAM_REV.txt)"
SOURCE_ROOT="$(mktemp -d)"
ARCHIVE="${SOURCE_ROOT}/protobufs.tar.gz"
EXTRACT_ROOT="${SOURCE_ROOT}/protobufs"
OUTPUT_DIR="src/sonoran/meshtastic"

cleanup() {
    rm -rf "${SOURCE_ROOT}"
}
trap cleanup EXIT

curl --fail --location --silent --show-error \
    "https://codeload.github.com/meshtastic/protobufs/tar.gz/${REV}" \
    --output "${ARCHIVE}"
mkdir -p "${EXTRACT_ROOT}"
tar --extract --gzip --file "${ARCHIVE}" --directory "${EXTRACT_ROOT}" --strip-components=1

rm -rf "${OUTPUT_DIR}"
mkdir -p "${OUTPUT_DIR}"
uvx --from grpcio-tools==1.76.0 python -m grpc_tools.protoc \
    --proto_path="${EXTRACT_ROOT}" \
    --python_out="src/sonoran" \
    "${EXTRACT_ROOT}"/meshtastic/*.proto

find "${OUTPUT_DIR}" -type f -name '*_pb2.py' \
    -exec sed -i 's/from meshtastic/from sonoran.meshtastic/' {} +
touch "${OUTPUT_DIR}/__init__.py"
echo "Generated Meshtastic protobuf modules at ${REV}."
