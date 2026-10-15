#!/usr/bin/env bash
# 一键构建：章节 HTML → Wiki 站点
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
bash "$DIR/build-html.sh"
python3 "$DIR/gen-index.py"
python3 "$DIR/build-wiki.py"
