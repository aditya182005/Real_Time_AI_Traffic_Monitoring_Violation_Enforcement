"""Show the signal state on three LEDs driven by an Arduino.

The computer sends one letter per change over USB serial: ``R`` red,
``Y`` amber, ``G`` green. ``hardware/arduino_signal/arduino_signal.ino`` is
the matching sketch. Needs the optional ``pyserial`` package.

    python -m app.hardware.arduino --list           # find the port name
    python -m app.hardware.arduino --port COM3      # cycle the lamps once

This is a teaching/demo output for a model junction on a desk. It must never
drive a real road signal.
"""

import argparse
import sys
import time

CODES = {"RED": b"R", "AMBER": b"Y", "YELLOW": b"Y", "GREEN": b"G"}
BAUD = 9600


class ArduinoError(RuntimeError):
    """The board could not be reached."""


def _serial_module():
    try:
        import serial
    except ImportError as exc:
        raise ArduinoError("pyserial is not installed (pip install pyserial).") from exc

    return serial


def list_ports():
    try:
        from serial.tools import list_ports as lp
    except ImportError as exc:
        raise ArduinoError("pyserial is not installed (pip install pyserial).") from exc

    return [(p.device, p.description) for p in lp.comports()]


class ArduinoSignal:
    """Sends the state when it changes. ``opener`` is a test hook."""

    def __init__(self, port, baud=BAUD, opener=None, settle=2.0):
        try:
            opener = opener or _serial_module().Serial
            self.link = opener(port, baud, timeout=1)
        except ArduinoError:
            raise
        except Exception as exc:
            raise ArduinoError(f"Could not open {port}: {exc}") from exc

        self.port = port
        self.last = None
        time.sleep(settle)          # most boards reset when the port opens

    def send(self, state):
        """Send ``state`` ("RED"/"AMBER"/"GREEN") if it differs from last time."""

        code = CODES.get(str(state).upper())

        if code is None or code == self.last:
            return False

        try:
            self.link.write(code + b"\n")
        except Exception as exc:
            raise ArduinoError(f"Lost the board on {self.port}: {exc}") from exc

        self.last = code

        return True

    def close(self):
        try:
            self.link.close()
        except Exception:
            pass


def main(argv=None, opener=None):
    parser = argparse.ArgumentParser(
        prog="python -m app.hardware.arduino", description=__doc__.split("\n")[0])
    parser.add_argument("--list", action="store_true", help="list serial ports")
    parser.add_argument("--port", help="e.g. COM3 or /dev/ttyACM0")
    args = parser.parse_args(argv)

    try:
        if args.list:
            ports = list_ports()

            for device, text in ports:
                print(f"{device}  {text}")

            if not ports:
                print("No serial ports found.")

            return 0

        if not args.port:
            parser.error("give --port (or --list to find it)")

        board = ArduinoSignal(args.port, opener=opener,
                              settle=0 if opener else 2.0)

        for state in ("RED", "AMBER", "GREEN", "AMBER", "RED"):
            board.send(state)
            print(state)
            time.sleep(0 if opener else 1.5)

        board.close()
    except ArduinoError as exc:
        print(exc, file=sys.stderr)

        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
