"""Report the running software version.

Kept free of any web-framework imports so the client-side daemons (scheduler,
monitor, boiler_to_mqtt) can log their version at startup as cheaply as the web
app reports it via /version.
"""
import os
import subprocess
from importlib.metadata import version as _package_version, PackageNotFoundError


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
