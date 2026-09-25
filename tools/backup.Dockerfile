# The image of the `backup` service.
#
# It is the database image with one script added. The same image gives
# pg_dump the same major version as the server, which pg_dump requires.
# See tools/db_backup_scheduled.sh.
FROM timescale/timescaledb-ha:pg17

COPY --chmod=755 tools/db_backup_scheduled.sh /usr/local/bin/sonoran-backup

ENTRYPOINT ["/usr/local/bin/sonoran-backup"]
CMD ["loop"]
