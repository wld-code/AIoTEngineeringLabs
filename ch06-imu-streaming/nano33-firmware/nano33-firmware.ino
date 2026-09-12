// Lab 6 — Arduino Nano 33 BLE Sense: onboard LSM9DS1 accelerometer,
// streamed over USB serial as one JSON object per line.
//
// Board:   Arduino Nano 33 BLE Sense (arduino:mbed_nano:nano33ble)
// Library: Arduino_LSM9DS1 (Arduino Library Manager)
//
// Wiring: none. The LSM9DS1 is onboard. Connect only the USB data cable, it
// carries both power and the serial link Node-RED reads from.
//
// The Nano 33 BLE Sense has no Wi-Fi radio (that is the Nano 33 IoT, a
// different board). This is why this lab moved from MQTT-over-Wi-Fi to
// plain USB serial: it is the interface this board actually has.
//
// Output, one line per sample at 115200 baud:
//   {"device":"nano-01","t_ms":12345,"ax":0.0123,"ay":-0.9876,"az":0.0456}
//
// The LSM9DS1's own output data rate is fixed near 119 Hz and is not
// configurable on this library. This sketch reads whatever sample is ready
// and passes it straight through rather than resampling to a round number,
// see the lab README for why forcing a different rate here would just
// interpolate noise instead of measuring anything.

#include <Arduino_LSM9DS1.h>

const char* DEVICE_ID = "nano-01";

void setup() {
  Serial.begin(115200);
  while (!Serial) { }                 // wait for the USB CDC port to enumerate

  if (!IMU.begin()) {
    Serial.println("{\"error\":\"IMU init failed\"}");
    while (1) { delay(1000); }
  }

  Serial.print("{\"status\":\"ready\",\"device\":\"");
  Serial.print(DEVICE_ID);
  Serial.print("\",\"accel_odr_hz\":");
  Serial.print(IMU.accelerationSampleRate());
  Serial.println("}");
}

void loop() {
  float ax, ay, az;
  if (!IMU.accelerationAvailable()) return;
  IMU.readAcceleration(ax, ay, az);

  Serial.print("{\"device\":\"");
  Serial.print(DEVICE_ID);
  Serial.print("\",\"t_ms\":");
  Serial.print(millis());
  Serial.print(",\"ax\":");
  Serial.print(ax, 4);
  Serial.print(",\"ay\":");
  Serial.print(ay, 4);
  Serial.print(",\"az\":");
  Serial.print(az, 4);
  Serial.println("}");
}
