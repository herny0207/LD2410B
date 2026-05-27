#include <Arduino.h>

// 定義與 LD2410B 連接的腳位
// 請根據您的 ESP32 接線進行修改，這裡預設使用 GPIO 16 (RX) 和 GPIO 17 (TX)
#define LD2410B_RX_PIN 16
#define LD2410B_TX_PIN 17

// 使用 ESP32 的 HardwareSerial 1
HardwareSerial LD2410(1);

// 定義緩衝區，LD2410B 基礎模式資料長度大約是 23 bytes
byte buffer[32];
int bufferIndex = 0;

void setup() {
  // 與電腦終端機的通訊 (USB)
  Serial.begin(115200);

  // 與 LD2410B 的通訊 (預設鮑率為 256000)
  LD2410.begin(256000, SERIAL_8N1, LD2410B_RX_PIN, LD2410B_TX_PIN);

  Serial.println("ESP32 LD2410B 準備就緒！");
  Serial.println("正在等待雷達資料...");
}

void parseLD2410B(byte *frame) {
  // byte 8: 目標狀態
  byte targetStateByte = frame[8];
  String targetState = "unknown";
  if (targetStateByte == 0x00)
    targetState = "no_target";
  else if (targetStateByte == 0x01)
    targetState = "moving_target";
  else if (targetStateByte == 0x02)
    targetState = "static_target";
  else if (targetStateByte == 0x03)
    targetState = "both_targets";

  // 解析距離與能量 (使用 & 0x7FFF 來過濾掉原 Python 程式提到的異常最高位元)
  // byte 9-10: 運動目標距離 (little endian)
  uint16_t movingDist = (frame[9] | (frame[10] << 8)) & 0x7FFF;

  // byte 11: 運動目標能量
  uint8_t movingEnergy = frame[11] & 0x7F;

  // byte 12-13: 靜止目標距離 (little endian)
  uint16_t staticDist = (frame[12] | (frame[13] << 8)) & 0x7FFF;

  // byte 14: 靜止目標能量
  uint8_t staticEnergy = frame[14] & 0x7F;

  // byte 15-16: 偵測距離 (little endian)
  uint16_t distance = (frame[15] | (frame[16] << 8)) & 0x7FFF;

  // 為了配合 Arduino Serial Plotter (序列埠繪圖家) 的格式
  // 輸出格式為 "名稱:數值,名稱2:數值2\n"
  
  Serial.print("Moving_Energy:");
  Serial.print(movingEnergy);
  Serial.print(",");
  
  Serial.print("Static_Energy:");
  Serial.print(staticEnergy);
  Serial.print(",");
  
  // 因為距離(cm)的數值可能高達幾百，會讓 0~100 的能量線條被壓縮
  // 這裡我們將距離除以 10 (例如 250cm 顯示為 25.0)，讓圖表更美觀好讀
  Serial.print("Distance(x10_cm):");
  Serial.println(distance / 10.0);
}

unsigned long lastPrintTime = 0;

void loop() {
  // 持續讀取雷達資料
  while (LD2410.available()) {
    byte b = LD2410.read();

    // 將新資料放入 buffer，如果滿了就把前面的資料擠掉
    if (bufferIndex < sizeof(buffer)) {
      buffer[bufferIndex++] = b;
    } else {
      for (int i = 0; i < sizeof(buffer) - 1; i++) {
        buffer[i] = buffer[i + 1];
      }
      buffer[sizeof(buffer) - 1] = b;
    }

    // 檢查結尾是否為 F8 F7 F6 F5
    if (bufferIndex >= 4 && buffer[bufferIndex - 4] == 0xF8 &&
        buffer[bufferIndex - 3] == 0xF7 && buffer[bufferIndex - 2] == 0xF6 &&
        buffer[bufferIndex - 1] == 0xF5) {

      // 在 buffer 中往前找開頭 F4 F3 F2 F1
      int frameStart = -1;
      for (int i = 0; i <= bufferIndex - 23; i++) {
        if (buffer[i] == 0xF4 && buffer[i + 1] == 0xF3 &&
            buffer[i + 2] == 0xF2 && buffer[i + 3] == 0xF1) {
          frameStart = i;
          break;
        }
      }

      // 如果找到完整的 Frame (大於等於 23 bytes)，就進行解析
      if (frameStart >= 0 && (bufferIndex - frameStart) >= 23) {
        // 為了讓繪圖家線條更順暢，將限制時間改為 50 毫秒 (每秒更新 20 次)
        if (millis() - lastPrintTime >= 50) {
          parseLD2410B(&buffer[frameStart]);
          lastPrintTime = millis();
        }
      }

      // 解析完畢或長度不夠，清空 buffer 準備接下一筆
      bufferIndex = 0;
    }
  }
}
