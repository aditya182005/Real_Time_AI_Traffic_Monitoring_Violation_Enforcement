// Three-LED signal for the Traffic Agent demo (Arduino Uno / Nano).
//
// Wiring: each LED anode -> 220 ohm resistor -> pin, cathode -> GND.
//   red LED   -> pin 8
//   amber LED -> pin 9
//   green LED -> pin 10
//
// The computer sends one letter per change: R, Y or G (then a newline).
// If nothing arrives for 5 seconds (cable out, program stopped) the amber
// LED flashes so nobody mistakes a stale colour for the live state.
//
// A desk model only. Never connect this to a real road signal.

const int RED_PIN = 8;
const int AMBER_PIN = 9;
const int GREEN_PIN = 10;
const unsigned long TIMEOUT_MS = 5000;

unsigned long lastByteAt = 0;
bool everHeard = false;

void show(char code) {
  digitalWrite(RED_PIN, code == 'R');
  digitalWrite(AMBER_PIN, code == 'Y');
  digitalWrite(GREEN_PIN, code == 'G');
}

void setup() {
  pinMode(RED_PIN, OUTPUT);
  pinMode(AMBER_PIN, OUTPUT);
  pinMode(GREEN_PIN, OUTPUT);
  Serial.begin(9600);
  show('R');              // safe start: red until told otherwise
}

void loop() {
  while (Serial.available() > 0) {
    char c = Serial.read();

    if (c == 'R' || c == 'Y' || c == 'G') {
      show(c);
      lastByteAt = millis();
      everHeard = true;
    }
  }

  if (everHeard && millis() - lastByteAt > TIMEOUT_MS) {
    // link lost: flash amber
    bool on = (millis() / 500) % 2 == 0;
    digitalWrite(RED_PIN, LOW);
    digitalWrite(GREEN_PIN, LOW);
    digitalWrite(AMBER_PIN, on);
  }
}
