"""Logging setup.

This module configures structured logging for all processes.
Use get_logger in every other module.
"""

import logging
import sys

_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger.

    Call this once at process start.
    """
    logging.basicConfig(
        level=level.upper(),
        format=_FORMAT,
        stream=sys.stdout,
        force=True,
    )


def get_logger(name: str) -> logging.Logger:
    """Return a logger for the given module name."""
    return logging.getLogger(name)


# Where uvicorn's access record keeps the request line.
#
# It logs with `'%s - "%s %s HTTP/%s" %d'` and five positional
# arguments: the client address, the method, the path with its query, the
# HTTP version, and the status. The path is the third.
_ACCESS_PATH_ARGUMENT = 2


class RedactQueryFilter(logging.Filter):
    """Take the query string off the access log line for named paths.

    One endpoint on this API carries words a reader typed: the planner's
    address search (`api/routes/geocode.py`). The API is GET-only by
    architecture (`AGENTS.md` 4), so the address is in the request line,
    and uvicorn's access log writes the request line to stdout — which on
    a deployment is the container log, kept and shipped.

    So the query is removed before the record is formatted. A filter
    rather than a formatter: a formatter belongs to a handler and uvicorn
    replaces its handlers when it applies its own logging config, while a
    filter set on the logger survives that (`logging.config` clears a
    logger's handlers and leaves its filters alone).

    The path itself is kept. "GET /api/geocode?q=[removed]" still says an
    address was looked up, which is what an operator needs to see; it no
    longer says which one.

    A filter never drops the record. Returning False here would hide the
    request entirely, and a lookup that produced a 502 would then be
    invisible.
    """

    def __init__(self, paths: tuple[str, ...]) -> None:
        super().__init__()
        self.paths = paths

    def filter(self, record: logging.LogRecord) -> bool:
        arguments = record.args
        # Anything that is not the shape described above is left alone.
        # uvicorn is not the only thing that may log here, and a filter
        # that assumed the shape would throw inside logging — where the
        # exception surfaces as a mangled line and not as a traceback.
        if not isinstance(arguments, tuple) or len(arguments) <= _ACCESS_PATH_ARGUMENT:
            return True
        target = arguments[_ACCESS_PATH_ARGUMENT]
        if not isinstance(target, str) or "?" not in target:
            return True
        path = target.split("?", 1)[0]
        if not any(path == watched or path.startswith(f"{watched}/") for watched in self.paths):
            return True
        edited = list(arguments)
        edited[_ACCESS_PATH_ARGUMENT] = f"{path}?[removed]"
        record.args = tuple(edited)
        return True


def quieten_http_client() -> None:
    """Stop httpx logging the URL of every outbound request.

    **Measured, not assumed.** httpx logs `HTTP Request: GET <url> "200
    OK"` at INFO, not at DEBUG, so on a default deployment this line
    appeared for the planner's address search with the reader's typed
    address in the query string:

        INFO httpx HTTP Request: GET https://.../search?q=Flagstaff...

    The access log is redacted (`redact_access_query`) and this would
    have put the same words back one line below it. The comment in this
    module said DEBUG until the request was actually made and the log
    read.

    WARNING rather than a filter matching one host: every caller of httpx
    in this repository already logs its own outcome — the terrain store
    names the tile it downloaded, `routes/geocode.py` names the status it
    got, `routes/traceroutes.py` turns a failure into a 502 and says so —
    so nothing that matters is lost, and a filter would have to know
    which URLs are sensitive, which is the kind of allow list that goes
    stale silently.
    """
    logging.getLogger("httpx").setLevel(logging.WARNING)


def redact_access_query(*paths: str) -> RedactQueryFilter:
    """Stop the access log recording the query string of these paths.

    Idempotent: called twice with the same paths, the second filter is
    not added. The API factory runs once per process in production and
    once per case in the tests, and a filter per case would be a slow
    leak rather than a visible fault.
    """
    logger = logging.getLogger("uvicorn.access")
    for existing in logger.filters:
        if isinstance(existing, RedactQueryFilter) and existing.paths == paths:
            return existing
    made = RedactQueryFilter(paths)
    logger.addFilter(made)
    return made
