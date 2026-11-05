#!/usr/bin/env python3
"""Target-size video compressor for the Antigravity 20 MB Finder workflow."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

TARGET_BYTES = int(19.5 * 1024 * 1024)
TARGET_LABEL = "19.5 MiB"
CODECS = {
    "h264": {"encoder": "libx264", "tag": "avc1", "suffix": "H264"},
    "h265": {"encoder": "libx265", "tag": "hvc1", "suffix": "H265"},
}
SHORT_EDGES = (2160, 1440, 1080, 900, 720, 576, 480, 360, 240, 144)
HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}
AUDIO_PROFILES = ((96000, 2), (64000, 2), (48000, 2), (48000, 1), (32000, 1))
SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv", ".mpeg", ".mpg", ".wmv", ".flv", ".3gp"}

CURRENT_PROCESS: Optional[subprocess.Popen[str]] = None
CANCELLED = False


class ShrinkError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceInfo:
    path: Path
    duration: float
    width: int
    height: int
    fps: float
    display_fps: str
    has_audio: bool
    source_audio_bps: Optional[int]
    is_hdr: bool


@dataclass(frozen=True)
class Candidate:
    width: int
    height: int
    short_edge: int
    fps: float
    video_bps: int
    bpp: float
    label: str


def emit(event_type: str, **payload: Any) -> None:
    print(json.dumps({"type": event_type, **payload}, ensure_ascii=False), flush=True)


def cancel_process(signum: int, _frame: Any) -> None:
    global CANCELLED
    CANCELLED = True
    if CURRENT_PROCESS and CURRENT_PROCESS.poll() is None:
        CURRENT_PROCESS.terminate()
    emit("cancelled", message="正在取消并清理临时文件")


def binary_path(name: str) -> str:
    env_name = name.upper()
    if os.environ.get(env_name):
        return os.environ[env_name]
    bundled = Path(__file__).resolve().parent / "bin" / name
    if bundled.is_file() and os.access(bundled, os.X_OK):
        return str(bundled)
    support = Path.home() / "Library/Application Support/ReelCompact/bin" / name
    legacy = Path.home() / "Library/Application Support/Antigravity20MB/bin" / name
    for candidate in (support, legacy):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise ShrinkError(f"找不到 {name}。请重新运行安装器。")


def parse_fraction(value: Optional[str]) -> float:
    if not value or value in {"0/0", "N/A"}:
        return 0.0
    try:
        if "/" in value:
            left, right = value.split("/", 1)
            denominator = float(right)
            return float(left) / denominator if denominator else 0.0
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def probe_source(path: Path) -> SourceInfo:
    ffprobe = binary_path("ffprobe")
    command = [
        ffprobe,
        "-v", "error",
        "-show_streams",
        "-show_format",
        "-of", "json",
        str(path),
    ]
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise ShrinkError(f"无法读取视频信息：{result.stderr.strip() or path.name}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ShrinkError("ffprobe 返回了无效数据") from exc

    streams = data.get("streams") or []
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if not video:
        raise ShrinkError("文件中没有视频轨道")

    duration = parse_fraction((data.get("format") or {}).get("duration"))
    if duration <= 0:
        duration = parse_fraction(video.get("duration"))
    if duration <= 0:
        raise ShrinkError("无法确定视频时长")

    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    rotation = 0
    tags = video.get("tags") or {}
    rotation = int(parse_fraction(tags.get("rotate", "0")) or 0)
    for side_data in video.get("side_data_list") or []:
        if "rotation" in side_data:
            rotation = int(parse_fraction(str(side_data["rotation"])) or 0)
    if abs(rotation) % 180 == 90:
        width, height = height, width
    if width <= 0 or height <= 0:
        raise ShrinkError("视频分辨率无效")

    fps = parse_fraction(video.get("r_frame_rate")) or parse_fraction(video.get("avg_frame_rate"))
    if fps <= 0:
        fps = 30.0
    fps = min(fps, 120.0)
    display_fps = f"{fps:.3f}".rstrip("0").rstrip(".")

    audio_bps: Optional[int] = None
    if audio:
        audio_bps = int(parse_fraction(audio.get("bit_rate"))) or None
    is_hdr = str(video.get("color_transfer") or "").lower() in HDR_TRANSFERS

    return SourceInfo(
        path=path,
        duration=duration,
        width=width,
        height=height,
        fps=fps,
        display_fps=display_fps,
        has_audio=audio is not None,
        source_audio_bps=audio_bps,
        is_hdr=is_hdr,
    )


def even(value: float) -> int:
    rounded = max(2, int(round(value)))
    return rounded if rounded % 2 == 0 else rounded - 1


def dimensions_for_short_edge(source: SourceInfo, short_edge: int) -> tuple[int, int]:
    if source.width >= source.height:
        height = min(short_edge, source.height)
        width = even(height * source.width / source.height)
        height = even(height)
    else:
        width = min(short_edge, source.width)
        height = even(width * source.height / source.width)
        width = even(width)
    return width, height


def target_video_bps(duration: float, audio_bps: int, target_bytes: int = TARGET_BYTES) -> int:
    overhead = max(64 * 1024, int(target_bytes * 0.012))
    available_bytes = target_bytes - overhead
    audio_bytes = audio_bps * duration / 8
    video_bytes = available_bytes - audio_bytes
    return max(0, math.floor(video_bytes * 8 / duration))


def quality_thresholds(codec: str) -> tuple[float, float]:
    if codec == "h265":
        return 0.055, 0.030
    return 0.080, 0.045


def fps_cap_for(candidate_short_edge: int, video_bps: int, source_fps: float) -> float:
    cap = source_fps
    if candidate_short_edge < 720:
        if video_bps < 1_500_000:
            cap = min(cap, 30.0)
        if candidate_short_edge < 480 and video_bps < 800_000:
            cap = min(cap, 24.0)
        if candidate_short_edge < 360 and video_bps < 450_000:
            cap = min(cap, 15.0)
    return cap


def build_candidates(source: SourceInfo, video_bps: int, codec: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen: set[tuple[int, int]] = set()
    source_short = min(source.width, source.height)
    edges = []
    if source_short <= SHORT_EDGES[0]:
        edges.append(source_short)
    for edge in SHORT_EDGES:
        if edge < source_short and edge not in edges:
            edges.append(edge)
    if not edges:
        edges = [SHORT_EDGES[0]]

    high, acceptable = quality_thresholds(codec)
    for index, edge in enumerate(edges):
        width, height = dimensions_for_short_edge(source, edge)
        key = (width, height)
        if key in seen:
            continue
        seen.add(key)
        fps = fps_cap_for(edge, video_bps, source.fps)
        bpp = video_bps / max(1, width * height * fps)
        label = "原分辨率" if index == 0 and edge == source_short else f"{min(width, height)}p"
        candidates.append(Candidate(width, height, min(width, height), fps, video_bps, bpp, label))

    if not candidates:
        return []

    source_candidate = candidates[0]
    if source_candidate.bpp >= high:
        return [source_candidate]

    acceptable_candidates = [candidate for candidate in candidates if candidate.bpp >= acceptable]
    if acceptable_candidates:
        acceptable_candidates.sort(key=lambda candidate: (candidate.short_edge, candidate.bpp), reverse=True)
        shortlist = acceptable_candidates[:3]
    else:
        shortlist = candidates[:3]

    if source_candidate not in shortlist:
        shortlist.insert(0, source_candidate)
    unique: list[Candidate] = []
    for candidate in shortlist:
        if candidate not in unique:
            unique.append(candidate)
    return unique[:3]


def run_quick(command: list[str]) -> tuple[int, str]:
    """Run a short child process while keeping SIGTERM cancellation responsive."""
    global CURRENT_PROCESS
    if CANCELLED:
        raise KeyboardInterrupt
    process = subprocess.Popen(
        command,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    CURRENT_PROCESS = process
    try:
        _, stderr = process.communicate()
        if CANCELLED:
            raise KeyboardInterrupt
        return process.returncode, stderr or ""
    finally:
        CURRENT_PROCESS = None


def has_filter(name: str) -> bool:
    ffmpeg = binary_path("ffmpeg")
    result = subprocess.run([ffmpeg, "-hide_banner", "-filters"], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return re.search(rf"\b{re.escape(name)}\b", result.stdout) is not None


def tone_map_filter() -> str:
    return (
        "zscale=t=linear:npl=203,format=gbrpf32le,"
        "zscale=p=bt709,tonemap=mobius:desat=0,"
        "zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
    )


def video_filter(source: SourceInfo, candidate: Candidate) -> str:
    filters: list[str] = []
    if source.is_hdr:
        filters.append(tone_map_filter())
    filters.append(f"scale={candidate.width}:{candidate.height}:flags=lanczos")
    filters.append("setsar=1")
    if abs(candidate.fps - source.fps) > 0.01:
        filters.append(f"fps={candidate.fps:.3f}")
    return ",".join(filters)


def run_process(command: list[str], phase_start: float, phase_end: float, phase_label: str, duration: float) -> None:
    global CURRENT_PROCESS, CANCELLED
    if CANCELLED:
        raise KeyboardInterrupt
    emit("progress", percent=phase_start, phase=phase_label)
    stderr_file = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
    try:
        process = subprocess.Popen(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            bufsize=1,
        )
        CURRENT_PROCESS = process
        assert process.stdout is not None
        for line in process.stdout:
            if CANCELLED:
                process.terminate()
                break
            key, separator, value = line.partition("=")
            if separator and key in {"out_time_us", "out_time_ms"}:
                try:
                    seconds = int(value) / 1_000_000
                    fraction = min(1.0, max(0.0, seconds / max(duration, 0.001)))
                    percent = phase_start + (phase_end - phase_start) * fraction
                    emit("progress", percent=round(percent, 1), phase=phase_label)
                except ValueError:
                    pass
        return_code = process.wait()
        if CANCELLED or return_code in {-15, 143}:
            raise KeyboardInterrupt
        if return_code != 0:
            stderr_file.seek(0)
            detail = stderr_file.read()[-4000:].strip()
            raise ShrinkError(f"{phase_label}失败：{detail or f'ffmpeg 退出码 {return_code}'}")
    finally:
        CURRENT_PROCESS = None
        stderr_file.close()


def ffmpeg_base() -> list[str]:
    return [binary_path("ffmpeg"), "-hide_banner", "-y", "-progress", "pipe:1", "-nostats"]


def sample_score(source: SourceInfo, candidate: Candidate, codec: str, workdir: Path) -> Optional[float]:
    if not has_filter("libvmaf") or source.duration < 2.0:
        return None

    points = [0.20, 0.50, 0.80] if source.duration >= 6 else [0.50]
    window = min(1.5, max(0.7, source.duration / 20))
    scores: list[float] = []
    ffmpeg = binary_path("ffmpeg")
    for index, fraction in enumerate(points):
        if CANCELLED:
            raise KeyboardInterrupt
        start = max(0.0, source.duration * fraction - window / 2)
        encoded = workdir / f"sample_{candidate.short_edge}_{index}.mp4"
        reference = workdir / f"reference_{candidate.short_edge}_{index}.mp4"
        vmaf_log = workdir / f"vmaf_{candidate.short_edge}_{index}.json"
        encode_command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{start:.3f}", "-t", f"{window:.3f}", "-i", str(source.path),
            "-an", "-sn", "-dn",
            "-vf", video_filter(source, candidate),
            "-c:v", CODECS[codec]["encoder"],
            "-preset", "veryfast",
            "-b:v", str(max(64_000, candidate.video_bps)),
            "-maxrate", str(max(80_000, int(candidate.video_bps * 1.25))),
            "-bufsize", str(max(160_000, candidate.video_bps * 2)),
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(encoded),
        ]
        reference_command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{start:.3f}", "-t", f"{window:.3f}", "-i", str(source.path),
            "-an", "-sn", "-dn",
            "-vf", video_filter(source, candidate),
            "-c:v", "libx264", "-preset", "ultrafast", "-qp", "0",
            "-pix_fmt", "yuv420p", str(reference),
        ]
        try:
            encoded_code, _ = run_quick(encode_command)
            reference_code, _ = run_quick(reference_command)
            if encoded_code != 0 or reference_code != 0:
                return None
            if not encoded.exists() or not reference.exists():
                return None
            compare_command = [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(encoded), "-i", str(reference),
                "-lavfi", f"[0:v][1:v]libvmaf=log_fmt=json:log_path={vmaf_log}:n_threads=4",
                "-an", "-f", "null", "-",
            ]
            compared_code, _ = run_quick(compare_command)
            if compared_code != 0 or not vmaf_log.exists():
                return None
            payload = json.loads(vmaf_log.read_text())
            score = float(payload["pooled_metrics"]["vmaf"]["mean"])
            scores.append(score)
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return None
        finally:
            for artifact in (encoded, reference, vmaf_log):
                try:
                    artifact.unlink()
                except FileNotFoundError:
                    pass
    return sum(scores) / len(scores) if scores else None


def choose_candidate(source: SourceInfo, candidates: list[Candidate], codec: str, workdir: Path) -> Candidate:
    if len(candidates) == 1:
        return candidates[0]
    emit("progress", percent=6, phase="比较候选画质")
    scored: list[tuple[float, Candidate]] = []
    for candidate in candidates:
        if CANCELLED:
            raise KeyboardInterrupt
        score = sample_score(source, candidate, codec, workdir)
        if score is not None:
            scored.append((score, candidate))
            emit("log", message=f"{candidate.label} VMAF {score:.2f}")
    if scored:
        scored.sort(key=lambda pair: (pair[0], pair[1].short_edge), reverse=True)
        return scored[0][1]
    return max(candidates, key=lambda candidate: (candidate.short_edge, candidate.bpp))


def unique_output(source: Path, codec: str) -> Path:
    suffix = CODECS[codec]["suffix"]
    base = source.with_name(f"{source.stem}_20MB_{suffix}.mp4")
    if not base.exists():
        return base
    index = 2
    while True:
        candidate = source.with_name(f"{source.stem}_20MB_{suffix}_{index}.mp4")
        if not candidate.exists():
            return candidate
        index += 1


def pass_commands(
    source: SourceInfo,
    candidate: Candidate,
    codec: str,
    video_bps: int,
    audio_bps: int,
    audio_channels: int,
    passlog: Path,
    output: Path,
) -> tuple[list[str], list[str]]:
    base = ffmpeg_base()
    vf = video_filter(source, candidate)
    encoder = CODECS[codec]["encoder"]
    maxrate = max(64_000, int(video_bps * 1.25))
    bufsize = max(128_000, video_bps * 2)
    common = [
        "-i", str(source.path),
        "-map", "0:v:0",
        "-vf", vf,
        "-c:v", encoder,
        "-preset", "medium",
        "-pix_fmt", "yuv420p",
        "-b:v", str(video_bps),
        "-maxrate", str(maxrate),
        "-bufsize", str(bufsize),
    ]
    audio_args = []
    if source.has_audio:
        audio_args = ["-map", "0:a:0?", "-c:a", "aac", "-b:a", str(audio_bps), "-ac", str(audio_channels)]
    if codec == "h265":
        stats = str(passlog) + "_x265_2pass.log"
        pass1 = base + common + [
            "-x265-params", f"pass=1:stats={stats}",
            "-an", "-sn", "-dn", "-f", "null", os.devnull,
        ]
        pass2 = base + common + [
            "-x265-params", f"pass=2:stats={stats}",
            *audio_args,
            "-tag:v", CODECS[codec]["tag"],
            "-movflags", "+faststart",
            "-map_metadata", "-1",
            "-sn", "-dn",
            "-f", "mp4", str(output),
        ]
    else:
        pass1 = base + common + [
            "-pass", "1", "-passlogfile", str(passlog),
            "-an", "-sn", "-dn", "-f", "null", os.devnull,
        ]
        pass2 = base + common + [
            "-pass", "2", "-passlogfile", str(passlog),
            *audio_args,
            "-tag:v", CODECS[codec]["tag"],
            "-movflags", "+faststart",
            "-map_metadata", "-1",
            "-sn", "-dn",
            "-f", "mp4", str(output),
        ]
    return pass1, pass2


def clean_passlogs(passlog: Path) -> None:
    parent = passlog.parent
    prefix = passlog.name
    for path in parent.glob(prefix + "*"):
        try:
            path.unlink()
        except OSError:
            pass


def encode_attempt(
    source: SourceInfo,
    candidate: Candidate,
    codec: str,
    video_bps: int,
    audio_bps: int,
    audio_channels: int,
    output: Path,
    workdir: Path,
) -> None:
    passlog = workdir / "ffmpeg2pass"
    pass1, pass2 = pass_commands(source, candidate, codec, video_bps, audio_bps, audio_channels, passlog, output)
    run_process(pass1, 22, 48, "第一轮编码", source.duration)
    run_process(pass2, 48, 88, "第二轮编码", source.duration)
    clean_passlogs(passlog)


def validate_output(source: SourceInfo, output: Path) -> float:
    emit("progress", percent=92, phase="校验文件")
    if not output.exists() or output.stat().st_size == 0:
        raise ShrinkError("编码没有生成有效文件")
    if output.stat().st_size > TARGET_BYTES:
        raise ShrinkError(f"输出仍超过 {TARGET_LABEL}")
    try:
        output_info = probe_source(output)
    except ShrinkError as exc:
        raise ShrinkError(f"输出文件无法读取：{exc}") from exc
    if abs(output_info.duration - source.duration) > max(0.75, 2 / source.fps):
        raise ShrinkError("输出时长与原视频不一致")
    return output_info.duration


def compress_file(path: Path, codec: str, target_bytes: int = TARGET_BYTES) -> Path:
    if not path.is_file():
        raise ShrinkError("文件不存在")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ShrinkError(f"暂不支持 {path.suffix or '无扩展名'} 格式")
    original_size = path.stat().st_size
    if original_size <= target_bytes:
        emit("skipped", input=str(path), output=str(path), message=f"原文件已经不超过 {TARGET_LABEL}")
        return path

    emit("file_start", input=str(path), size=original_size)
    emit("progress", percent=1, phase="读取视频信息")
    source = probe_source(path)
    emit(
        "log",
        message=f"{path.name}: {source.width}×{source.height}, {source.display_fps} fps, {source.duration:.1f}s"
        + ("，HDR→SDR" if source.is_hdr else ""),
    )

    audio_profiles = AUDIO_PROFILES if source.has_audio else ((0, 0),)
    audio_bps, audio_channels = audio_profiles[0]
    output = unique_output(path, codec)
    final_temp = output.with_name(f".{output.stem}.{uuid.uuid4().hex}.part.mp4")

    with tempfile.TemporaryDirectory(prefix="antigravity-shrink-") as temp_directory:
        workdir = Path(temp_directory)
        try:
            attempts = 0
            profile_index = 0
            current_candidates = build_candidates(source, target_video_bps(source.duration, audio_bps, target_bytes), codec)
            if not current_candidates:
                raise ShrinkError("没有可用的缩放方案")
            candidate = choose_candidate(source, current_candidates, codec, workdir)
            video_bps = target_video_bps(source.duration, audio_bps, target_bytes)
            if video_bps < 32_000:
                raise ShrinkError(f"视频太长，即使最低音质也无法在 {TARGET_LABEL} 内保留完整音轨")

            while attempts < 8:
                attempts += 1
                emit(
                    "log",
                    message=f"编码 {candidate.label} {candidate.width}×{candidate.height} @ {candidate.fps:g} fps，"
                    f"视频 {video_bps / 1000:.0f} kbps，音频 {audio_bps / 1000:.0f} kbps",
                )
                try:
                    encode_attempt(
                        source, candidate, codec, video_bps,
                        audio_bps, audio_channels, final_temp, workdir,
                    )
                    validate_output(source, final_temp)
                    os.replace(final_temp, output)
                    emit("done", input=str(path), output=str(output), size=output.stat().st_size)
                    emit("progress", percent=100, phase="完成")
                    return output
                except ShrinkError:
                    actual_size = final_temp.stat().st_size if final_temp.exists() else 0
                    if actual_size > target_bytes:
                        ratio = target_bytes / actual_size
                        video_bps = max(32_000, int(video_bps * min(0.98, ratio * 0.96)))
                        candidate = Candidate(
                            candidate.width,
                            candidate.height,
                            candidate.short_edge,
                            candidate.fps,
                            video_bps,
                            video_bps / max(1, candidate.width * candidate.height * candidate.fps),
                            candidate.label,
                        )
                        continue

                    profile_index += 1
                    if source.has_audio and profile_index < len(audio_profiles):
                        audio_bps, audio_channels = audio_profiles[profile_index]
                        video_bps = target_video_bps(source.duration, audio_bps, target_bytes)
                        attempts -= 1
                        continue

                    lower = [
                        item for item in build_candidates(source, video_bps, codec)
                        if item.short_edge < candidate.short_edge
                    ]
                    if lower:
                        candidate = lower[0]
                        attempts -= 1
                        continue
                    raise
            raise ShrinkError("多次重试后仍无法压到目标体积")
        finally:
            for temporary in (final_temp,):
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass


def human_size(size: int) -> str:
    return f"{size / (1024 ** 2):.2f} MiB"


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"把视频压缩到 {TARGET_LABEL} 以下")
    parser.add_argument("--codec", choices=tuple(CODECS), required=True)
    parser.add_argument("--target-bytes", type=int, default=TARGET_BYTES, help=argparse.SUPPRESS)
    parser.add_argument("files", nargs="+")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    signal.signal(signal.SIGTERM, cancel_process)
    signal.signal(signal.SIGINT, cancel_process)
    args = parse_args(argv)
    failures = 0
    completed = 0
    for raw in args.files:
        path = Path(raw).expanduser().resolve()
        try:
            result = compress_file(path, args.codec, args.target_bytes)
            if result != path:
                completed += 1
        except KeyboardInterrupt:
            emit("cancelled", message="已取消")
            return 130
        except Exception as exc:
            failures += 1
            emit("file_error", input=str(path), message=str(exc))
    emit("summary", completed=completed, failures=failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
