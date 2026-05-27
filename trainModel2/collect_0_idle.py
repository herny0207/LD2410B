import serial
import csv
import time

COM_PORT = 'COM3'  # 👈 請改為你們的 COM 埠
BAUD_RATE = 115200
FILENAME = 'data_0_idle.csv'
LABEL = 0

ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=0.1)
print("=== 類別 0：【無人狀態】數據收集系統 ===")
print("請確保雷達前方完全空無一物...")

# 前 10 秒不偵測倒數
for i in range(10, 0, -1):
    print(f"⏳ 系統初始化中，剩餘 {i} 秒開始記錄...")
    time.sleep(1)

print("\n🚀 開始記錄數據！請維持空房 120 秒...")
ser.reset_input_buffer()

data_list = []
while len(data_list) < 600:
    if ser.in_waiting:
        try:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line == "-1":
                continue
            parts = line.split(',')
            if len(parts) >= 19 and parts[-1] == "END":
                gate_values = [int(x) for x in parts[0:18]]
                gate_values.append(LABEL)
                data_list.append(gate_values)
                if len(data_list) % 10 == 0:
                    print(f"已收集: {len(data_list)}/600 筆")
        except Exception:
            pass

# 寫入 CSV
header = [
    'g0_m', 'g1_m', 'g2_m', 'g3_m', 'g4_m', 'g5_m', 'g6_m', 'g7_m', 'g8_m',
    'g0_s', 'g1_s', 'g2_s', 'g3_s', 'g4_s', 'g5_s', 'g6_s', 'g7_s', 'g8_s',
    'label'
]
with open(FILENAME, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(header)
    writer.writerows(data_list)

print(f"💾 收集完成！檔案已儲存為: {FILENAME}\n")
ser.close()
