#include "MyLD2410.h"
#include <Arduino.h>


#define LD2410_BAUD_RATE 256000
#define SERIAL_BAUD_RATE 115200
#define RX_PIN 16
#define TX_PIN 17

MyLD2410 sensor(Serial2);
const unsigned long printEvery = 200; // 每 0.2 秒傳送一筆

void printCsvValue(const byte &val) {
  Serial.print(val);
  Serial.print(',');
}

void setup() {
  Serial.begin(SERIAL_BAUD_RATE);
  Serial2.begin(LD2410_BAUD_RATE, SERIAL_8N1, RX_PIN, TX_PIN);
  delay(2000);
  if (!sensor.begin()) {
    while (true) {
      Serial.println("-1");
      delay(1000);
    }
  }
  sensor.enhancedMode(); // 啟用工程加強模式
  delay(20);
}

void loop() {
  static unsigned long lastPrint = 0;
  MyLD2410::Response response = sensor.check();

  if ((response == MyLD2410::Response::DATA) &&
      (millis() - lastPrint >= printEvery)) {
    lastPrint = millis();
    
    if (sensor.inEnhancedMode()) {
      sensor.getMovingSignals().forEach(printCsvValue);
      sensor.getStationarySignals().forEach(printCsvValue);
      Serial.print("END");
      Serial.println();
    }
  }
}
