import functools
import os
import subprocess
from importlib.metadata import version as _package_version, PackageNotFoundError

from flask import g, current_app, request
from http import HTTPStatus

from . import model


def _git_revision():
    """Return the short git commit, with a trailing '+' if the working tree has
    local modifications, or None if git/the repo are unavailable (e.g. when
    running from an installed wheel)."""
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_dir, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    try:
        dirty = bool(subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_dir, capture_output=True, text=True, check=True
        ).stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        dirty = False
    return commit + ("+" if dirty else "")


def software_version():
    """Return the running software version.

    The package version, optionally suffixed with the git commit it was built
    from (e.g. "0.1.0+ab12cd3").  A trailing '+' on the commit indicates the
    working tree had uncommitted local modifications.
    """
    try:
        ver = _package_version("boilerio")
    except PackageNotFoundError:
        ver = "unknown"
    revision = _git_revision()
    if revision:
        return "%s+%s" % (ver, revision)
    return ver


def get_db():
    if not hasattr(g, 'db'):
        g.db = model.db_connect(
            current_app.config.get('DB_HOST'),
            current_app.config.get('DB_USER'),
            current_app.config.get('DB_NAME'),
            current_app.config.get('DB_PASSWORD'))
    return g.db


# Decorator to add CSRF protection to any mutating function.
#
# Adding this header to the client forces the browser to first do an OPTIONS
# call, determine that the origin is not allowed, and block the subsequent
# call. (Ordinarily, the call is made but the result not made available to
# the client if the origin is not allowed, but the damage is already done.)
# Checking for the presence of this header on the server side prevents
# clients from bypassing this check.
#
# Add this decorator to all mutating operations.
def csrf_protection(fn):
    """Require that the X-Requested-With header is present."""
    @functools.wraps(fn)
    def protected(*args, **kwargs):
        if 'X-Requested-With' in request.headers:
            return fn(*args, **kwargs)
        else:
            return "X-Requested-With header missing", HTTPStatus.FORBIDDEN
    return protected
