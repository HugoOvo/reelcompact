#!/bin/zsh
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
export REELCOMPACT_ROOT="$root"
python3 - <<'PY'
import os
import shutil
from pathlib import Path
path = Path(os.environ["REELCOMPACT_ROOT"]) / "build/ReelCompact.app"
if path.exists():
    shutil.rmtree(path)
PY
app="$root/build/ReelCompact.app"
contents="$app/Contents"
mkdir -p "$contents/MacOS" "$contents/Resources"
swiftc -parse-as-library "$root/src/ReelCompact.swift" \
  -o "$contents/MacOS/ReelCompact" \
  -framework SwiftUI -framework AppKit -framework Foundation
cp "$root/build/Info.plist" "$contents/Info.plist"
install -m 755 "$root/src/shrink_core.py" "$contents/Resources/shrink_core.py"
install -m 755 "$root/scripts/make_workflows.py" "$contents/Resources/make_workflows.py"
install -m 644 "$root/assets/ReelCompact.icns" "$contents/Resources/ReelCompact.icns"
mkdir -p "$contents/Resources/bin"
install -m 755 "$HOME/Library/Application Support/ReelCompact/bin/ffmpeg" "$contents/Resources/bin/ffmpeg"
install -m 755 "$HOME/Library/Application Support/ReelCompact/bin/ffprobe" "$contents/Resources/bin/ffprobe"
chmod 755 "$contents/MacOS/ReelCompact"
codesign --force --deep --sign - "$app" >/dev/null
echo "Built $app"
