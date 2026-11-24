# Release process

This is for maintainers.

The **Release** workflow can be run manually from a branch to build the
wheel and source archive, run the Python test matrix, and smoke-test the Pi
image. Download the distributions and checksums from the workflow's
`python-distributions` artifact.

For a release, update the version in `pyproject.toml` and run `uv lock`, and
update the pinned version in the backend install step in `docs/SETUP.md`
(`pip install 'boilerio[web]==<version>'`).
Push the release commit to the default branch, then push an annotated tag
matching the package version, such as `v0.5.0`. The tag run tests the Pi image
by its GHCR digest, then prepares a draft GitHub Release with a digest-pinned
pull command, the wheel, the source archive, and `SHA256SUMS`. Review the
draft before publishing it in GitHub. The image job uses the repository's
`GITHUB_TOKEN` to push to GHCR.

The first time an image is pushed under a new package name, GHCR makes the
package private. Make it public in the package's settings on GitHub, or
nobody else can pull it.

After publishing the GitHub Release, publish the same distributions to PyPI.
Download them from the release, check them against its `SHA256SUMS`, and
upload them with [uv](https://docs.astral.sh/uv/), using a PyPI API token
scoped to the `boilerio` project (uv reads it from `UV_PUBLISH_TOKEN`, or
prompts for it):

```sh
mkdir release-v0.5.0 && cd release-v0.5.0
gh release download v0.5.0 --repo adpeace/boilerio
shasum -a 256 -c SHA256SUMS
uv publish boilerio-0.5.0-py3-none-any.whl boilerio-0.5.0.tar.gz
```

Then check that `pip install 'boilerio[web]==0.5.0'` installs the new version.

If draft preparation fails, choose **Re-run failed jobs** on the original
Actions run so it reuses the tested image and distribution files. If an
interrupted upload left an incomplete asset in the draft, remove that asset
before retrying.

The Pi image runs on `linux/arm64` and installs the release wheel. Use the
digest-pinned image reference from the release notes. For a local wheel-based
build, place one BoilerIO wheel in a directory and build with:

```sh
docker buildx build --target image-wheel \
  --build-context wheel-input=./path/to/wheel-directory --load -t boilerio:dev .
```
