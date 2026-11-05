#!/bin/zsh
set -euo pipefail

support="$HOME/Library/Application Support/ReelCompact"
bin="$support/bin"
legacy="$HOME/Library/Application Support/Antigravity20MB/bin"
mkdir -p "$bin"
if [[ ! -x "$bin/ffmpeg" && -x "$legacy/ffmpeg" && -x "$legacy/ffprobe" ]]; then
  cp "$legacy/ffmpeg" "$bin/ffmpeg"
  cp "$legacy/ffprobe" "$bin/ffprobe"
  chmod 755 "$bin/ffmpeg" "$bin/ffprobe"
fi

if [[ -x "$bin/ffmpeg" && -x "$bin/ffprobe" ]]; then
  encoders=$("$bin/ffmpeg" -hide_banner -encoders 2>/dev/null)
  filters=$("$bin/ffmpeg" -hide_banner -filters 2>/dev/null)
  if [[ "$encoders" == *libx264* && "$encoders" == *libx265* && "$filters" == *libvmaf* ]]; then
    echo "FFmpeg already installed in $bin"
    exit 0
  fi
fi

base='https://ffmpeg.martin-riedl.de/download/macos/arm64/1789931890_9.0.2'
tmp=$(mktemp -d /tmp/reelcompact-ffmpeg.XXXXXX)
trap 'python3 -c "import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "$tmp"' EXIT
curl -fsSL "$base/ffmpeg.zip" -o "$tmp/ffmpeg.zip"
curl -fsSL "$base/ffmpeg.zip.sha256" -o "$tmp/ffmpeg.zip.sha256"
curl -fsSL "$base/ffprobe.zip" -o "$tmp/ffprobe.zip"
curl -fsSL "$base/ffprobe.zip.sha256" -o "$tmp/ffprobe.zip.sha256"
(cd "$tmp" && shasum -a 256 -c ffmpeg.zip.sha256 && shasum -a 256 -c ffprobe.zip.sha256)
unzip -q "$tmp/ffmpeg.zip" -d "$tmp"
unzip -q "$tmp/ffprobe.zip" -d "$tmp"
install -m 755 "$tmp/ffmpeg" "$bin/ffmpeg"
install -m 755 "$tmp/ffprobe" "$bin/ffprobe"
echo "Installed FFmpeg 9.0.2 in $bin"
