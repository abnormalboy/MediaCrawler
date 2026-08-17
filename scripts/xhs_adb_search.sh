#!/usr/bin/env bash
# 小红书 App ADB 标准流程
# 用法：./scripts/xhs_adb_search.sh [关键词] [打开条数] [滑动屏数]
# 例：  ./scripts/xhs_adb_search.sh 吧唧 5 1
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

KEYWORD="${1:-吧唧}"
OPEN="${2:-5}"
PAGES="${3:-1}"

if ! command -v adb >/dev/null 2>&1 && [[ ! -x "$HOME/Library/Android/sdk/platform-tools/adb" ]]; then
  echo "找不到 adb，请先安装 Android platform-tools" >&2
  exit 1
fi

ADB_BIN="${ADB_BIN:-$(command -v adb || true)}"
if [[ -z "$ADB_BIN" ]]; then
  ADB_BIN="$HOME/Library/Android/sdk/platform-tools/adb"
fi

if ! "$ADB_BIN" devices | awk 'NR>1 && $2=="device" { found=1 } END { exit !found }'; then
  echo "没有已连接的 adb 设备。请先：adb devices" >&2
  exit 1
fi

echo "标准流程：关键词=${KEYWORD} 打开=${OPEN} 滑动=${PAGES}"
exec uv run python tools/xhs_adb.py search -k "$KEYWORD" -p "$PAGES" --open "$OPEN"
