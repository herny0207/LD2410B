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

WINDOW_SIZE = 5
frame_buffer = []
data_list = []

while len(data_list) < 600:
    if ser.in_waiting:
        try:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line == "-1":
                continue
            parts = line.split(',')
            if len(parts) >= 19 and parts[-1] == "END":
                current_frame = [int(x) for x in parts[0:18]]
                frame_buffer.append(current_frame)
                
                if len(frame_buffer) > WINDOW_SIZE:
                    frame_buffer.pop(0)
                    
                if len(frame_buffer) == WINDOW_SIZE:
                    # 攤平 5 幀的所有特徵為 90 維向量
                    flattened = [val for frame in frame_buffer for val in frame]
                    flattened.append(LABEL)
                    data_list.append(flattened)
                    if len(data_list) % 10 == 0:
                        print(f"已收集: {len(data_list)}/600 筆")
        except Exception:
            pass

# 動態生成 90 個特徵欄位名稱 (gX_m_tY / gX_s_tY)
header = []
for t in range(WINDOW_SIZE):
    for g in range(9):
        header.append(f"g{g}_m_t{t}")
    for g in range(9):
        header.append(f"g{g}_s_t{t}")
header.append("label")

with open(FILENAME, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(header)
    writer.writerows(data_list)

print(f"💾 收集完成！檔案已儲存為: {FILENAME}\n")
ser.close()