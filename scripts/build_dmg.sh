#!/bin/zsh
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
"$root/scripts/install_ffmpeg.sh"
"$root/scripts/build.sh"

stage=$(mktemp -d /tmp/reelcompact-dmg.XXXXXX)
trap 'python3 -c "import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "$stage"' EXIT
ditto "$root/build/ReelCompact.app" "$stage/ReelCompact.app"
ln -s /Applications "$stage/Applications"
cat > "$stage/安装说明.txt" <<'TXT'
轻帧 ReelCompact 1.0

安装：
1. 把 ReelCompact.app 拖到 Applications（应用程序）文件夹。
2. 打开 App。它会自动安装两个 Finder 快速操作。
3. 第一次使用时，到“系统设置 → 访达”打开两个“压缩到20MB”开关，只需一次。
4. 在 Finder 中选中视频，右键 →“快速操作”：
   - 压缩到20MB（H.264 兼容）
   - 压缩到20MB（H.265 高画质）

输出保存在原视频旁边：
原名_20MB_H264.mp4 或 原名_20MB_H265.mp4

原视频不会被修改或删除。此安装包内含 FFmpeg、libx264、libx265 和 libvmaf，无需另装 Homebrew。
TXT
mkdir -p "$root/outputs"
output="$root/outputs/ReelCompact-1.0.0-arm64.dmg"
export DMG_OUTPUT="$output"
python3 - <<'PY'
import os
from pathlib import Path
path = Path(os.environ["DMG_OUTPUT"])
if path.exists():
    path.unlink()
PY
hdiutil create -quiet -volname 'ReelCompact 1.0' -srcfolder "$stage" -format UDZO -fs HFS+ "$output"
codesign --force --sign - "$output" >/dev/null
hdiutil verify -quiet "$output"
echo "$output"
