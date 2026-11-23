"""Build release artifacts from the checked-out commit (discarding local changes).

Should be run from within the repository."""

import argparse
import io
import os
from email.parser import BytesParser
from hashlib import file_digest
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from zipfile import ZipFile


def git(*args):
    return subprocess.check_output(["git", *args]).decode().strip()


def distribution_versions(wheel: Path, sdist: Path) -> tuple[str, str]:
    """Extract the version from the wheel and sdist artifacts."""
    with ZipFile(wheel) as archive:
        metadata, = (name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        wheel_version = BytesParser().parsebytes(archive.read(metadata))["Version"]
    with tarfile.open(sdist) as archive:
        metadata = archive.extractfile(f"{sdist.name.removesuffix('.tar.gz')}/PKG-INFO")
        source_version = BytesParser().parse(metadata)["Version"]
    return wheel_version, source_version


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the wheel and sdist from the exact checked-out commit, "
            "verify their versions, and write SHA256SUMS next to them."
        ),
        epilog=(
            "When run by GitHub Actions on a push, the tag and default-branch "
            "checks are enforced. Expects DEFAULT_BRANCH in the environment "
            "for those checks."
        ),
    )
    parser.add_argument(
        "dist",
        type=Path,
        metavar="DIST_DIR",
        help="output directory for the artifacts; created if missing, must be empty",
    )
    return parser.parse_args(argv)


def main():
    args = parse_args()
    dist = args.dist.resolve()
    dist.mkdir(parents=True, exist_ok=True)
    if any(dist.iterdir()):
        sys.exit(f"Build destination must be empty: {dist}")

    # Check tag matches version in pyproject.toml:
    revision = git("rev-parse", "HEAD")
    version = tomllib.loads(git("show", "HEAD:pyproject.toml"))["project"]["version"]
    tag = f"v{version}"
    if os.environ.get("GITHUB_EVENT_NAME") == "push":
        if os.environ["GITHUB_REF"] != f"refs/tags/{tag}" or not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
            sys.exit(f"Expected a release tag matching the package version ({tag})")
        default_branch = os.environ["DEFAULT_BRANCH"]
        if subprocess.run(
            ["git", "merge-base", "--is-ancestor", revision, f"origin/{default_branch}"],
            check=False,
        ).returncode:
            sys.exit(f"Release commit must be on the default branch ({default_branch})")

    # Build the wheel and sdist
    with tempfile.TemporaryDirectory() as source_dir:
        # Get a clean tree at the tag:
        source = Path(source_dir)
        archive = subprocess.check_output(["git", "archive", revision])
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(source, filter="data")
        (source / "boilerio" / "_build_revision.py").write_text(
            f'REVISION = "{revision}"\n', encoding="utf-8",
        )
        subprocess.run(["uv", "lock", "--check"], cwd=source, check=True)
        subprocess.run(
            ["uv", "build", "--python", sys.executable, "--out-dir", str(dist)],
            cwd=source,
            check=True,
            env={**os.environ, "SOURCE_DATE_EPOCH": git("show", "-s", "--format=%ct", revision)},
        )

    # Validate the output and write sha256 digests:
    wheel, = dist.glob("boilerio-*.whl")
    sdist, = dist.glob("boilerio-*.tar.gz")
    if distribution_versions(wheel, sdist) != (version, version):
        sys.exit(f"Expected the wheel and sdist to both have version {version}")

    with (dist / "SHA256SUMS").open("w", encoding="utf-8") as output:
        for artifact in (wheel, sdist):
            with artifact.open("rb") as data:
                checksum = file_digest(data, "sha256").hexdigest()
            print(f"{checksum}  {artifact.name}", file=output)

    # If run from the GitHub Action, write output variable to the specified location:
    if output_path := os.environ.get("GITHUB_OUTPUT"):
        with Path(output_path).open("a", encoding="utf-8") as output:
            print(f"tag={tag}\nversion={version}\nrevision={revision}", file=output)


if __name__ == "__main__":
    main()
