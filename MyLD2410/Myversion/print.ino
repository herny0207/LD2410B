/*
  HLK-LD2410 工程模式 - 全距離閘能量輸出程式 (Python 繪圖專用版)
  完全採用原廠函式庫提供之 .forEach() 介面進行 CSV 輸出。
*/
#if defined(ARDUINO_SAMD_NANO_33_IOT) || defined(ARDUINO_AVR_LEONARDO)
// ARDUINO_SAMD_NANO_33_IOT RX_PIN is D1, TX_PIN is D0
// ARDUINO_AVR_LEONARDO RX_PIN(RXI) is D0, TX_PIN(TXO) is D1
#define sensorSerial Serial1
#elif defined(ARDUINO_XIAO_ESP32C3) || defined(ARDUINO_XIAO_ESP32C6)
// RX_PIN is D7, TX_PIN is D6
#define sensorSerial Serial0
#elif defined(ESP32)
// Other ESP32 device - choose available GPIO pins
#define sensorSerial Serial1
#if defined(ARDUINO_ESP32S3_DEV)
#define RX_PIN 18
#define TX_PIN 17
#else
#define RX_PIN 16
#define TX_PIN 17
#endif
#elif defined(ARDUINO_AVR_NANO) || defined(ARDUINO_AVR_UNO)
// You may use SoftwareSerial, but at a lower baud rate (38400 works well)
#include <SoftwareSerial.h>
SoftwareSerial sSerial(10, 11); // RX, TX
#define sensorSerial sSerial
// This baud rate must be explicitly set once by running the "set_baud_rate.ino"
// example on a board with a hardware UART
#define LD2410_BAUD_RATE 38400
#else
#error                                                                         \
    "This sketch only works on ESP32, Arduino Nano 33IoT, Arduino Nano/Uno, and Arduino Leonardo (Pro-Micro)"
#endif
// Change the communication baud rate here, if previously configured
// #define LD2410_BAUD_RATE 256000
#include "MyLD2410.h"

// User defines
// #define DEBUG_MODE
#define ENHANCED_MODE
#define SERIAL_BAUD_RATE 115200

#ifdef DEBUG_MODE
MyLD2410 sensor(sensorSerial, true);
#else
MyLD2410 sensor(sensorSerial);
#endif

// 將數據刷新時間改為 100 毫秒，維持 Python 繪圖流暢度
const unsigned long plotEvery = 100;

// 專門用於 Python CSV 格式的走訪函式 (印出數值並帶有逗號)
void printCsvValue(const byte &val) {
  Serial.print(val);
  Serial.print(',');
}

// 專門用於最後一個數值的走訪函式 (印出數值，不帶逗號，留給後續換行)
void printCsvValueLast(const byte &val) { Serial.print(val); }

void printRadarPlotData() {
  if (sensor.inEnhancedMode()) {
    // 1. 利用函式庫自帶的 .forEach() 印出 9 個移動目標能量 (帶逗號)
    sensor.getMovingSignals().forEach(printCsvValue);

    // 2. 利用函式庫自帶的 .forEach() 印出前 8 個靜止目標能量 (帶逗號)
    // 註：因為原 library 的 forEach 會走訪全部，為了符合標準 CSV 結尾，
    // 我們可以將最後一筆的處理留給換行。這裡直接走訪輸出即可。
    sensor.getStationarySignals().forEach(printCsvValueLast);

    // 但因為最後一個數值後面不能有逗號，原 library 沒有提供只走訪到前 8
    // 個的方法。 為了讓 Python 的 split(',') 能夠完美運作，最安全的做法是
    // 讓所有數據後面都帶逗號，並在最後直接換行。
    // 我們將 Python 解析端修正為適應最後帶有逗號的格式。
  }
}

void setup() {
  Serial.begin(SERIAL_BAUD_RATE);
#if defined(ARDUINO_XIAO_ESP32C3) || defined(ARDUINO_XIAO_ESP32C6) ||          \
    defined(ARDUINO_SAMD_NANO_33_IOT) || defined(ARDUINO_AVR_LEONARDO) ||      \
    defined(ARDUINO_AVR_NANO) || defined(ARDUINO_AVR_UNO)
  sensorSerial.begin(LD2410_BAUD_RATE);
#else
  sensorSerial.begin(LD2410_BAUD_RATE, SERIAL_8N1, RX_PIN, TX_PIN);
#endif
  delay(2000);
  Serial.println(__FILE__);
  if (!sensor.begin()) {
    // 失敗時持續噴出 -1 告知 Python 繪圖端
    while (true) {
      Serial.println("-1");
      delay(500);
    }
  }

#ifdef ENHANCED_MODE
  sensor.enhancedMode();
#else
  sensor.enhancedMode(false);
#endif

  delay(20);
}

void loop() {
  static unsigned long lastPrint = 0;
  if ((sensor.check() == MyLD2410::Response::DATA) &&
      (millis() - lastPrint >= plotEvery)) {
    lastPrint = millis();

    // 執行符合原生 API 設計的 CSV 資料輸出
    if (sensor.inEnhancedMode()) {
      sensor.getMovingSignals().forEach(printCsvValue);
      sensor.getStationarySignals().forEach(printCsvValue);
      Serial.print("END"); // 加上結束標記，避免行尾有多餘逗號造成的混淆
      Serial.println();
    }
  }
}