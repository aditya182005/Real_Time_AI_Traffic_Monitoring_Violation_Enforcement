import unittest
from io import StringIO
from contextlib import redirect_stdout, redirect_stderr
from unittest import mock

from app.hardware import arduino
from app.signals import adaptive


class FakeSerial:
    def __init__(self, port, baud, timeout=None):
        self.port, self.baud, self.written, self.closed = port, baud, [], False

    def write(self, data):
        self.written.append(data)

    def close(self):
        self.closed = True


class ArduinoTests(unittest.TestCase):
    def board(self):
        return arduino.ArduinoSignal("COM3", opener=FakeSerial, settle=0)

    def test_sends_only_on_change(self):
        board = self.board()

        self.assertTrue(board.send("RED"))
        self.assertFalse(board.send("RED"))
        self.assertTrue(board.send("green"))
        self.assertTrue(board.send("AMBER"))
        self.assertEqual(board.link.written, [b"R\n", b"G\n", b"Y\n"])

    def test_unknown_state_is_ignored(self):
        board = self.board()

        self.assertFalse(board.send("PURPLE"))
        self.assertEqual(board.link.written, [])

    def test_open_and_write_failures_are_clear(self):
        def broken(*a, **k):
            raise OSError("no such port")

        with self.assertRaisesRegex(arduino.ArduinoError, "Could not open"):
            arduino.ArduinoSignal("COM9", opener=broken, settle=0)

        board = self.board()
        board.link.write = mock.Mock(side_effect=OSError("unplugged"))

        with self.assertRaisesRegex(arduino.ArduinoError, "Lost the board"):
            board.send("RED")

    def test_cli(self):
        with redirect_stdout(StringIO()) as out:
            self.assertEqual(arduino.main(["--port", "COM3"], opener=FakeSerial), 0)

        self.assertIn("GREEN", out.getvalue())

        with redirect_stderr(StringIO()):
            self.assertEqual(arduino.main(
                ["--port", "x"], opener=mock.Mock(side_effect=OSError("no"))), 1)

    def test_processor_survives_a_dead_board(self):
        import tempfile
        from pathlib import Path

        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest("OpenCV not installed")

        from app.video_processor import TrafficVideoProcessor

        class Empty:
            def update(self, d):
                from types import SimpleNamespace
                return SimpleNamespace(xyxy=np.empty((0, 4)),
                                       tracker_id=np.empty((0,), int),
                                       class_id=np.empty((0,), int))

        with tempfile.TemporaryDirectory() as d:
            video = Path(d) / "v.mp4"
            writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"),
                                     10, (64, 64))

            if not writer.isOpened():
                self.skipTest("cannot write mp4v")

            for _ in range(4):
                writer.write(np.zeros((64, 64, 3), np.uint8))

            writer.release()
            output = mock.Mock()
            output.send.side_effect = arduino.ArduinoError("unplugged")
            processor = TrafficVideoProcessor(
                detector=mock.Mock(detect=lambda f: []), tracker=Empty(),
                signal_output=output, evidence_dir=Path(d) / "ev")
            processor.process(video, Path(d) / "o.mp4", show=False,
                              save_to_db=False)

        output.send.assert_called_once()     # dropped after the first failure


class AdaptiveTests(unittest.TestCase):
    plan = adaptive.Plan()

    def test_green_time_follows_queue_within_limits(self):
        self.assertEqual(adaptive.green_time(0, self.plan), 10)
        self.assertEqual(adaptive.green_time(8, self.plan), 16)
        self.assertEqual(adaptive.green_time(500, self.plan), 60)

    def test_longest_queue_goes_next_but_not_twice_running(self):
        self.assertEqual(adaptive.next_approach([2, 9, 4, 1], [0] * 4, self.plan), 1)
        self.assertEqual(adaptive.next_approach([2, 9, 4, 1], [0] * 4, self.plan,
                                                current=1), 2)

    def test_starving_approach_is_served_first(self):
        waited = [0, 0, 0, 130]

        self.assertEqual(adaptive.next_approach([9, 9, 9, 1], waited, self.plan), 3)

    def test_empty_junction_rotates(self):
        self.assertEqual(adaptive.next_approach([0] * 4, [0] * 4, self.plan, 3), 0)
        self.assertEqual(adaptive.next_approach([0] * 4, [0] * 4, self.plan), 0)

    def test_same_traffic_for_both_and_adaptive_waits_less_when_uneven(self):
        fixed, smart = adaptive.compare([0.12, 0.03, 0.10, 0.04], 1800, seed=1)

        self.assertEqual(fixed.arrived, smart.arrived)
        self.assertLess(smart.average_wait, fixed.average_wait)
        self.assertGreaterEqual(smart.served, fixed.served)

    def test_deterministic(self):
        a = adaptive.compare([0.1] * 4, 600, seed=5)
        b = adaptive.compare([0.1] * 4, 600, seed=5)

        self.assertEqual(a, b)

    def test_cli(self):
        with redirect_stdout(StringIO()) as out:
            self.assertEqual(adaptive.main(["--seconds", "300"]), 0)

        self.assertIn("simulation", out.getvalue())

        with self.assertRaises(SystemExit), redirect_stderr(StringIO()):
            adaptive.main(["--rates", "1,2"])


if __name__ == "__main__":
    unittest.main()
