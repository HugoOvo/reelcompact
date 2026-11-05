from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import shrink_core


class ShrinkCoreTests(unittest.TestCase):
    def test_target_bitrate_accounts_for_audio(self) -> None:
        with_audio = shrink_core.target_video_bps(60, 96_000)
        without_audio = shrink_core.target_video_bps(60, 0)
        self.assertGreater(with_audio, 0)
        self.assertGreater(without_audio, with_audio)
        self.assertLess(without_audio - with_audio, 100_000)

    def test_portrait_dimensions_preserve_even_size(self) -> None:
        source = shrink_core.SourceInfo(
            Path("portrait.mov"), 10, 1080, 1920, 30, "30", True, 96_000, False
        )
        width, height = shrink_core.dimensions_for_short_edge(source, 720)
        self.assertEqual(width, 720)
        self.assertEqual(height, 1280)
        self.assertEqual(width % 2, 0)
        self.assertEqual(height % 2, 0)

    def test_landscape_dimensions_do_not_upscale(self) -> None:
        source = shrink_core.SourceInfo(
            Path("wide.mp4"), 10, 1280, 720, 30, "30", False, None, False
        )
        width, height = shrink_core.dimensions_for_short_edge(source, 1080)
        self.assertEqual((width, height), (1280, 720))

    def test_unique_output_adds_suffixes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / "广告 片.mov"
            source.touch()
            first = shrink_core.unique_output(source, "h264")
            self.assertEqual(first.name, "广告 片_20MB_H264.mp4")
            first.touch()
            second = shrink_core.unique_output(source, "h264")
            self.assertEqual(second.name, "广告 片_20MB_H264_2.mp4")
            second.touch()
            third = shrink_core.unique_output(source, "h264")
            self.assertEqual(third.name, "广告 片_20MB_H264_3.mp4")

    def test_fps_reduction_is_only_for_difficult_low_bandwidth_video(self) -> None:
        self.assertEqual(shrink_core.fps_cap_for(1080, 500_000, 60), 60)
        self.assertEqual(shrink_core.fps_cap_for(720, 500_000, 60), 60)
        self.assertEqual(shrink_core.fps_cap_for(480, 500_000, 60), 30)
        self.assertEqual(shrink_core.fps_cap_for(240, 300_000, 60), 15)


if __name__ == "__main__":
    unittest.main()
