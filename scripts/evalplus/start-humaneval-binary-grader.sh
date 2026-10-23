#!/bin/sh
set -eu
# Keep the restored dependencies outside /tmp. Preserve the original worker's path.
mkdir -p /tmp/objrun-evalplus-20261012
if [ ! -e /tmp/objrun-evalplus-20261012/venv ]; then
    ln -s /opt/objrun-humaneval-binary-20261015/venv /tmp/objrun-evalplus-20261012/venv
fi
exec /tmp/objrun-evalplus-20261012/venv/bin/python \
    /mnt/f/git/TgEngin-handoff-2026-10-07/TgEngin/scripts/evalplus/grader_service.py \
    --dataset humaneval --port 17963 \
    --output /mnt/f/git/TgEngin-handoff-2026-10-07/TgEngin/docs/evalplus-20261012/humaneval/binary-v1/grader
