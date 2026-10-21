#!/bin/sh
# Dev image entrypoint: install the bind-mounted workspace packages (the service and libs/py)
# editable into /opt/venv, then run the container's command. Third-party dependencies are
# already in the image (the deps/dev layers), so this only links the workspace sources.
# --inexact keeps what the image installed; --locked fails fast if uv.lock is stale.
set -eu
: "${SERVICE:?SERVICE must be set to the service package name}"
uv sync --locked --package "$SERVICE" --inexact --quiet
exec "$@"
