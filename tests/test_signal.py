import unittest

from app.violation.signal import SignalSimulator


class SignalSimulatorTests(unittest.TestCase):

    def test_fixed(self):
        signal = SignalSimulator.fixed("GREEN")
        self.assertEqual(signal.state_at(1, 30), "GREEN")
        self.assertEqual(signal.state_at(9999, 30), "GREEN")

    def test_cycle_starts_red_then_green_then_repeats(self):
        signal = SignalSimulator.cycle(red_seconds=2, green_seconds=3)
        fps = 10

        self.assertEqual(signal.state_at(1, fps), "RED")      # t = 0.0 s
        self.assertEqual(signal.state_at(20, fps), "RED")     # t = 1.9 s
        self.assertEqual(signal.state_at(21, fps), "GREEN")   # t = 2.0 s
        self.assertEqual(signal.state_at(50, fps), "GREEN")   # t = 4.9 s
        self.assertEqual(signal.state_at(51, fps), "RED")     # t = 5.0 s, next cycle

    def test_cycle_can_start_green(self):
        signal = SignalSimulator.cycle(2, 3, start="GREEN")
        self.assertEqual(signal.state_at(1, 10), "GREEN")
        self.assertEqual(signal.state_at(31, 10), "RED")

    def test_validation(self):
        with self.assertRaises(ValueError):
            SignalSimulator.fixed("AMBER")
        with self.assertRaises(ValueError):
            SignalSimulator.cycle(0, 5)
        with self.assertRaises(ValueError):
            SignalSimulator(red_seconds=None, green_seconds=5)

    def test_describe(self):
        self.assertEqual(SignalSimulator.fixed("RED").describe(), "Always RED")
        self.assertIn("10s red", SignalSimulator.cycle(10, 20).describe())


if __name__ == "__main__":
    unittest.main()
