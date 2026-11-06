#!/bin/zsh
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
if [[ -n "${REELCOMPACT_FFMPEG_DIR:-}" ]]; then
  support="$REELCOMPACT_FFMPEG_DIR"
elif [[ -x "$HOME/Applications/ReelCompact.app/Contents/Resources/bin/ffmpeg" ]]; then
  support="$HOME/Applications/ReelCompact.app/Contents/Resources/bin"
elif [[ -x /Applications/ReelCompact.app/Contents/Resources/bin/ffmpeg ]]; then
  support=/Applications/ReelCompact.app/Contents/Resources/bin
else
  "$root/scripts/install_ffmpeg.sh" >/dev/null
  support="$HOME/Library/Application Support/ReelCompact/bin"
fi

export FFMPEG="$support/ffmpeg"
export FFPROBE="$support/ffprobe"

tmp=$(mktemp -d /tmp/reelcompact-integration.XXXXXX)
trap 'python3 -c "import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "$tmp"' EXIT
source="$tmp/合成 广告 测试.mp4"

"$support/ffmpeg" -hide_banner -loglevel error -y \
  -f lavfi -i 'testsrc2=size=1920x1080:rate=30' \
  -f lavfi -i 'sine=frequency=440:sample_rate=48000' \
  -t 12 -c:v libx264 -preset veryfast -b:v 24M -pix_fmt yuv420p \
  -c:a aac -b:a 192k "$source"

python3 "$root/src/shrink_core.py" --codec h264 "$source" > "$tmp/events.jsonl"
output="$tmp/合成 广告 测试_20MB_H264.mp4"
[[ -f "$output" ]]

export FFPROBE_PATH="$support/ffprobe"
python3 - <<'PY' "$output"
import json
import os
import subprocess
import sys
from pathlib import Path
path = Path(sys.argv[1])
limit = int(19.5 * 1024 * 1024)
assert path.stat().st_size <= limit, (path.stat().st_size, limit)
data = json.loads(subprocess.check_output([
    os.environ["FFPROBE_PATH"], "-v", "error", "-show_entries",
    "format=duration", "-of", "json", str(path)
]))
duration = float(data["format"]["duration"])
assert abs(duration - 12.0) < 0.1, duration
print(f"integration ok: {path.stat().st_size} bytes, {duration:.3f}s")
PY

python3 "$root/src/shrink_core.py" --codec h264 "$output" | grep '"type": "skipped"' >/dev/null
