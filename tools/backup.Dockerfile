# The image of the `backup` service.
#
# It is the database image with one script added. The same image gives
# pg_dump the same major version as the server, which pg_dump requires.
# See tools/db_backup_scheduled.sh.
#
# Pinned by digest, the same digest as the `timescaledb` service in
# docker-compose.yml and the CI database (.github/workflows/ci.yml,
# tests/integration/conftest.py). `pg17` is a moving tag. The digest is
# the multi-arch index (amd64 and arm64). Update all of them together,
# in their own commit. test_ci_database_image.py holds them to one value.
FROM timescale/timescaledb-ha:pg17@sha256:e77fc7a0395b63a89d27b8b5043abcc7e8120576429ea9a470977d4bed3d0261

COPY --chmod=755 tools/db_backup_scheduled.sh /usr/local/bin/sonoran-backup

ENTRYPOINT ["/usr/local/bin/sonoran-backup"]
CMD ["loop"]
