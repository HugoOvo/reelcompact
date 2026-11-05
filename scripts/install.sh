#!/bin/zsh
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
"$root/scripts/install_ffmpeg.sh"
"$root/scripts/build.sh"
python3 "$root/scripts/make_workflows.py"

mkdir -p "$HOME/Applications"
export REELCOMPACT_ROOT="$root"
python3 - <<'PY'
import os
import shutil
from pathlib import Path
source = Path(os.environ["REELCOMPACT_ROOT"]) / "build/ReelCompact.app"
destination = Path.home() / "Applications/ReelCompact.app"
if destination.exists():
    shutil.rmtree(destination)
shutil.copytree(source, destination, symlinks=True)
legacy = Path.home() / "Applications/Antigravity20MB.app"
if legacy.exists():
    shutil.rmtree(legacy, ignore_errors=True)
PY
codesign --force --deep --sign - "$HOME/Applications/ReelCompact.app" >/dev/null

for workflow in "$HOME"/Library/Services/压缩到20MB（*.workflow; do
  /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$workflow" >/dev/null 2>&1 || true
done
/System/Library/CoreServices/pbs -update >/dev/null 2>&1 || true
killall Finder >/dev/null 2>&1 || true
echo "Installed: $HOME/Applications/ReelCompact.app"
echo "Finder actions: 压缩到20MB（H.264 兼容）, 压缩到20MB（H.265 高画质）"
