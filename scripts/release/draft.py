"""Assemble an unpublished GitHub Release with the tested Pi image digest."""

from hashlib import file_digest
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def run(*command):
    return subprocess.check_output(command, text=True).strip()


def checksum(path):
    with path.open("rb") as file:
        return "sha256:" + file_digest(file, "sha256").hexdigest()


def main():
    dist = Path(sys.argv[1])
    repo = os.environ["GITHUB_REPOSITORY"]
    tag = os.environ["RELEASE_TAG"]
    workflow_url = f"{os.environ['GITHUB_SERVER_URL']}/{repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    image = os.environ["RELEASE_IMAGE"]
    if not re.fullmatch(r"ghcr\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}", image):
        sys.exit("Expected the tested image reference (repository@sha256:...)")

    wheel, = dist.glob("boilerio-*.whl")
    sdist, = dist.glob("boilerio-*.tar.gz")
    files = (wheel, sdist, dist / "SHA256SUMS")
    pages = json.loads(run("gh", "api", "--paginate", "--slurp", f"repos/{repo}/releases?per_page=100"))
    existing = next((release for page in pages for release in page if release["tag_name"] == tag), None)
    if existing and image not in (existing["body"] or ""):
        sys.exit(f"The existing {tag} release does not reference the tested controller image {image}")

    assets = {asset["name"]: asset["digest"] for asset in existing["assets"]} if existing else {}
    missing = []
    for file in files:
        if file.name not in assets:
            missing.append(file)
        elif assets[file.name] != checksum(file):
            sys.exit(f"The existing {tag} asset {file.name} has a different checksum")

    if existing and not existing["draft"]:
        if missing:
            sys.exit(f"The published release {tag} is missing distribution assets")
        print(f"{tag} is already published with these artifacts")
        return

    if not existing:
        notes = [
            f"Built from `{os.environ['RELEASE_REVISION']}` and verified in the [release workflow]({workflow_url}).",
            "",
            "Raspberry Pi (linux/arm64)",
            f"`docker pull {image}`",
        ]
        run("gh", "release", "create", tag, "--repo", repo, "--verify-tag", "--draft",
            "--title", f"BoilerIO {tag}", "--notes", "\n".join(notes))
    if missing:
        run("gh", "release", "upload", tag, "--repo", repo, *(str(file) for file in missing))
    print(f"Draft release ready to review in {repo}: {tag}")


if __name__ == "__main__":
    main()
