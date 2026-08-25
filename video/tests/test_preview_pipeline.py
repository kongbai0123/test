"""Low-latency parallel preview pipeline tests."""

import threading
import unittest
from unittest.mock import patch

import numpy as np

from src.engine.preview import LatestFrameProcessor


class TestLatestFrameProcessor(unittest.TestCase):
    def test_prepares_rgb_bytes_and_preserves_source_dimensions(self):
        processor = LatestFrameProcessor(max_width=2, max_height=2)
        frame = np.zeros((4, 6, 3), dtype=np.uint8)
        frame[:, :, 0] = 255  # BGR blue becomes RGB (0, 0, 255)

        prepared = processor._prepare(7, frame, 28.5, 30.0)

        self.assertEqual(prepared.sequence, 7)
        self.assertEqual((prepared.source_width, prepared.source_height), (6, 4))
        self.assertEqual((prepared.width, prepared.height), (2, 1))
        self.assertEqual(prepared.data[:3], bytes((0, 0, 255)))
        self.assertEqual((prepared.measured_fps, prepared.configured_fps), (28.5, 30.0))

    def test_replaces_pending_frame_instead_of_queueing_backlog(self):
        processor = LatestFrameProcessor()
        first_started = threading.Event()
        release_first = threading.Event()
        original_prepare = processor._prepare

        def slow_prepare(sequence, *args):
            if sequence == 1:
                first_started.set()
                release_first.wait(timeout=1.0)
            return original_prepare(sequence, *args)

        frame = np.zeros((2, 2, 3), dtype=np.uint8)
        with patch.object(processor, "_prepare", side_effect=slow_prepare):
            processor.start()
            self.assertTrue(processor.submit(1, frame))
            self.assertTrue(first_started.wait(timeout=1.0))
            self.assertTrue(processor.submit(2, frame))
            self.assertTrue(processor.submit(3, frame))
            release_first.set()

            for _ in range(100):
                latest = processor.get_latest()
                if latest is not None and latest.sequence == 3:
                    break
                threading.Event().wait(0.01)
            processor.stop()

        self.assertIsNotNone(latest)
        self.assertEqual(latest.sequence, 3)
        self.assertIsNone(processor.get_latest(after_sequence=3))


if __name__ == "__main__":
    unittest.main()
