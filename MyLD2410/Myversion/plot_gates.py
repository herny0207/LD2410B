import serial
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import numpy as np

# ================= 設定區 =================
# !!! 請務必確認 COM 號碼是否與你的 Arduino IDE 相同
COM_PORT = 'COM3' 
BAUD_RATE = 115200
# ==========================================

# 建立序列埠連線
try:
    ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=0.01)
    print(f"成功連線到 {COM_PORT}！")
    print("正在解碼原生 API 18 閘數據，請揮動雙手測試... (關閉視窗即可結束)")
except Exception as e:
    print(f"❌ 無法開啟序列埠 {COM_PORT}。請檢查：\n1. Port 號是否正確？\n2. Arduino IDE 的序列監視器有沒有關閉？\n錯誤訊息: {e}")
    exit()

# 建立 9 個距離閘的標籤（Gate 0 ~ Gate 8，每閘約 75 公分）
gates_label = [f'G{i}\n({i*0.75:.1f}m)' for i in range(9)]

# 初始化畫布 (左子圖：移動能量、右子圖：靜止能量)
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
fig.canvas.manager.set_window_title('HLK-LD2410 18-Channel Real-time Energy Monitor')

# 建立初始長條圖 (預設高度全為 0)
bars_moving = ax1.bar(gates_label, np.zeros(9), color='salmon', edgecolor='black')
bars_static = ax2.bar(gates_label, np.zeros(9), color='skyblue', edgecolor='black')

# 美化圖表外觀
for ax, title, color in [(ax1, 'Moving Targets Energy', 'darkred'), (ax2, 'Stationary Targets Energy', 'darkblue')]:
    ax.set_ylim(0, 100) # 雷達能量範圍固定在 0 ~ 100
    ax.set_ylabel('Energy Value')
    ax.set_xlabel('Distance Gates')
    ax.set_title(title, color=color, fontsize=13, fontweight='bold')
    ax.grid(axis='y', linestyle='--', alpha=0.5)

plt.tight_layout()

# 動態更新函式 (每 50 毫秒會被自動觸發一次)
def update(frame):
    # 一次讀完快取區內的所有行，只留下最後（最新）的一行，拋棄舊資料防止延遲
    lines = ser.readlines() 
    if not lines:
        return bars_moving + bars_static # 沒收到新資料就維持現狀
        
    try:
        # 解碼最新的一行文字
        latest_line = lines[-1].decode('utf-8', errors='ignore').strip()
        
        # 排除 Arduino 噴出的初始化失敗訊號
        if latest_line == "-1":
            return bars_moving + bars_static

        # 使用逗號切割字串
        data = latest_line.split(',')
        
        # 關鍵點：因為末尾有 END 標記，切割後的陣列長度會大於 18 且最後一個元素是 END
        if len(data) >= 19 and data[-1] == "END":
            # 精準切片：唯獨取出前 18 個元素並轉換為整數
            energies = [int(val) for val in data[0:18]]
            
            moving_data = energies[0:9]   # 前 9 個是移動能量 (G0~G8)
            static_data = energies[9:18]  # 後 9 個是靜止能量 (G0~G8)
            
            # 刷新移動能量長條圖高度
            for bar, val in zip(bars_moving, moving_data):
                bar.set_height(val)
                
            # 刷新靜止能量長條圖高度
            for bar, val in zip(bars_static, static_data):
                bar.set_height(val)
                
    except Exception:
        pass # 遇到不完整的髒資料直接忽略，防止程式崩潰

    return bars_moving + bars_static

# 啟動動畫 (interval=50 代表每秒刷新 20 次，cache_frame_data=False 消除快取警告)
ani = FuncAnimation(fig, update, interval=50, blit=True, cache_frame_data=False)

try:
    plt.show() # 彈出圖表視窗
finally:
    ser.close()
    print("\n序列埠已安全關閉。")