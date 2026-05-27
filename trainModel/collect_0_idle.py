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