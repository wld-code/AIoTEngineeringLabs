// Lab 7 — Arduino Nano 33 BLE Sense: onboard MP34DT05 PDM microphone,
// captured on command and streamed over USB serial as plain decimal lines.
//
// Board:   Arduino Nano 33 BLE Sense (arduino:mbed_nano:nano33ble)
// Library: PDM (bundled with the arduino:mbed_nano core, no install needed)
//
// Wiring: none. The microphone is onboard. Connect only the USB data cable.
//
// Protocol, all over the same 115200-baud serial line Node-RED already uses
// in Lab 6:
//   - Node-RED sends one byte, 'R', to start a recording.
//   - The board waits RECORD_DELAY_MS, so a sound source triggered at the
//     same time as 'R' (this lab plays one from the host machine) has
//     started before capture begins.
//   - The board then records NUM_SAMPLES samples at SAMPLE_RATE_HZ and
//     prints them as plain text: one line "REC_START", one decimal integer
//     per line, one line "REC_END". No JSON, no framing overhead — Node-RED
//     just watches for the two marker lines.
//
// Printing ~9600 lines at 115200 baud takes a few seconds. That is fine:
// this is a one-shot capture-then-dump exchange, not a real-time stream —
// unlike Lab 6's continuous IMU stream, nothing here needs to keep up with
// the sensor while it is still producing data, because it already has.

#include <PDM.h>

const int SAMPLE_RATE_HZ = 16000;
const int DURATION_MS = 600;
const int NUM_SAMPLES = (SAMPLE_RATE_HZ * DURATION_MS) / 1000;  // 9600
const int RECORD_DELAY_MS = 200;  // lets a host-side sound source start first
const int MIC_GAIN = 40;          // 0-80 on the Nano 33 BLE Sense

static int16_t recordBuffer[NUM_SAMPLES];
static short pdmBuffer[512];
volatile int recordIndex = 0;
volatile bool recording = false;
volatile bool captureDone = false;

void onPDMdata() {
  int bytesAvailable = PDM.available();
  PDM.read(pdmBuffer, bytesAvailable);
  int samplesIn = bytesAvailable / 2;

  if (!recording) return;

  for (int i = 0; i < samplesIn && recordIndex < NUM_SAMPLES; i++) {
    recordBuffer[recordIndex++] = pdmBuffer[i];
  }
  if (recordIndex >= NUM_SAMPLES) {
    recording = false;
    captureDone = true;
  }
}

void setup() {
  Serial.begin(115200);
  while (!Serial) { }  // wait for the USB CDC port to enumerate

  PDM.onReceive(onPDMdata);
  PDM.setGain(MIC_GAIN);

  if (!PDM.begin(1, SAMPLE_RATE_HZ)) {
    Serial.println("{\"error\":\"PDM init failed\"}");
    while (1) { delay(1000); }
  }

  Serial.print("{\"status\":\"ready\",\"sample_rate_hz\":");
  Serial.print(SAMPLE_RATE_HZ);
  Serial.print(",\"num_samples\":");
  Serial.print(NUM_SAMPLES);
  Serial.println("}");
}

void loop() {
  if (Serial.available() && !recording) {
    char c = Serial.read();
    if (c == 'R') {
      delay(RECORD_DELAY_MS);
      recordIndex = 0;
      captureDone = false;
      recording = true;
    }
  }

  if (captureDone) {
    captureDone = false;
    Serial.println("REC_START");
    for (int i = 0; i < NUM_SAMPLES; i++) {
      Serial.println(recordBuffer[i]);
    }
    Serial.println("REC_END");
  }
}
