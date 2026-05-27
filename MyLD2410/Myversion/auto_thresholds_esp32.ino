/*
  HLK-LD2410 自動門檻校正 (Auto Thresholds) - ESP32 直連專用版
  此版本已移除對 board_select.h 的依賴，直接指定腳位與 Serial2。
*/

#include <Arduino.h>
#include "MyLD2410.h"

// ===== 硬體與通訊定義 =====
#define LD2410_BAUD_RATE 256000  // 雷達通訊鮑率
#define SERIAL_BAUD_RATE 115200  // 電腦監控器鮑率
#define RX_PIN 16                // ESP32 RX 接雷達 TX
#define TX_PIN 17                // ESP32 TX 接雷達 RX

// 使用 Serial2 與雷達通訊
MyLD2410 sensor(Serial2);

// 輔助列印函數
void printValue(const byte &val) {
  Serial.print(' ');
  Serial.print(val);
}

// 列印當前雷達參數
void printParameters() {
  sensor.configMode();
  sensor.requestParameters();
  Serial.print("韌體版本: ");
  String fw(sensor.getFirmware());
  Serial.println(fw);
  
  if (!fw.startsWith(LD2410_LATEST_FIRMWARE)) {
    Serial.print("提示: 若要使用最新功能，請升級韌體至 ");
    Serial.println(LD2410_LATEST_FIRMWARE);
  }
  
  const MyLD2410::ValuesArray &mThr = sensor.getMovingThresholds();
  const MyLD2410::ValuesArray &sThr = sensor.getStationaryThresholds();

  Serial.printf("解析度: %d cm | 最大範圍: %d cm\n", sensor.getResolution(), sensor.getRange_cm());
  
  Serial.print("🏃 動態門檻 [0,");
  Serial.print(mThr.N);
  Serial.print("]:");
  mThr.forEach(printValue);
  
  Serial.print("\n🧍 靜態門檻 [0,");
  Serial.print(sThr.N);
  Serial.print("]:");
  sThr.forEach(printValue);
  
  Serial.print("\n⏳ 無人延遲時間: ");
  Serial.print(sensor.getNoOneWindow());
  Serial.println(" 秒");

  sensor.configMode(false);
}

void setup() {
  Serial.begin(SERIAL_BAUD_RATE);
  Serial2.begin(LD2410_BAUD_RATE, SERIAL_8N1, RX_PIN, TX_PIN);
  
  delay(2000);
  Serial.println("\n>>> HLK-LD2410 自動門檻校正系統啟動 <<<");
  
  if (!sensor.begin()) {
    Serial.println("❌ 無法與雷達通訊，請檢查接線與供電！");
    while (true) {}
  }

  Serial.println("\n【目前的感測器參數】\n-------------------------");
  printParameters();
  
  // 啟動自動門檻校正
  if (sensor.autoThresholds()) {
    Serial.println("\n************************************************");
    Serial.println("⚠️ 警告: 您有 10 秒鐘的時間離開房間！");
    Serial.println("請確保房間淨空，避免任何人為移動干擾校正！");
    Serial.println("************************************************");
    delay(10000);
    
    Serial.print("正在掃描環境背景雜訊 ");
    while (true) {
      switch (sensor.getAutoStatus()) {
        case AutoStatus::IN_PROGRESS:
          Serial.print('.');
          delay(2000);
          break;
          
        case AutoStatus::COMPLETED:
          Serial.println("\n\n🎉 校正成功！！！");
          Serial.println("【最新的最佳化參數如下】\n-----------------------");
          printParameters();
          Serial.println("您可以關閉此程式並開始正常使用雷達了。");
          return;
          
        case AutoStatus::NOT_IN_PROGRESS:
          Serial.println("\n\n❌ 校正中斷。是否有人移動了？");
          printParameters();
          Serial.print("為避免門檻錯亂，正在執行恢復原廠設定... ");
          delay(2000);
          if (sensor.requestReset()) Serial.println("恢復成功！");
          else Serial.println("恢復失敗...");
          printParameters();
          return;
          
        default:
          break;
      }
    }
  } else {
    Serial.println("\n❌ 自動門檻設定啟動失敗...");
    Serial.println("請確認您的雷達韌體版本是否為 2.44 (含) 以上？");
    sensor.requestReboot();
    printParameters();
  }
}

void loop() {
  // 不做任何事
}
