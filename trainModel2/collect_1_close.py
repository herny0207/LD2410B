import serial
import csv
import time

COM_PORT = 'COM3'  # 👈 請改為你們的 COM 埠
BAUD_RATE = 115200
FILENAME = 'data_1_close.csv'
LABEL = 1

ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=0.1)
print("=== 類別 1：【近距離動態 (Gate 0~2)】數據收集系统 ===")

for i in range(10, 0, -1):
    print(f"⏳ 請測試人員就位【近距離範圍】，剩餘 {i} 秒開始記錄...")
    time.sleep(1)

print("\n🚀 開始記錄數據！請在近距離範圍內持續做微幅動態動作...")
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
