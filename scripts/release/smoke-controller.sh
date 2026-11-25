#!/usr/bin/env bash
set -euo pipefail

image=$1
version=$2

test "$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$image")" = linux/arm64
test "$(docker image inspect --format '{{json .Config.Cmd}}' "$image")" = '["boilerio-controller"]'
docker run --rm --network none --interactive --entrypoint python "$image" - "$version" <<'PY'
from importlib.metadata import distribution
from importlib.util import find_spec
import os
import sys
from zoneinfo import ZoneInfo

from boilerio.version import software_version

assert (os.getuid(), os.getgid()) == (10001, 10001)
assert os.access("/var/lib/boilerio", os.W_OK)
assert software_version() == sys.argv[1], software_version()
assert find_spec("flask") is None
assert find_spec("psycopg2") is None
assert ZoneInfo("Europe/London").key == "Europe/London"
entry_points = distribution("boilerio").entry_points
assert callable(entry_points["boilerio-controller"].load())
assert callable(entry_points["boilerio-danfoss-bridge"].load())
PY
docker run --rm --network none "$image" boilerio-danfoss-bridge --help
