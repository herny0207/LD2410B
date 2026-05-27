import serial
import joblib
import numpy as np
import time
import os

# ================= 設定區 =================
COM_PORT = 'COM3'  # 👈 請修改為你的 COM 埠
BAUD_RATE = 115200

# 動態取得腳本所在目錄，確保無論從何處執行都能正確讀取同目錄下的模型
script_dir = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(script_dir, 'radar_model.pkl')
# ==========================================

# 載入模型
try:
    model = joblib.load(MODEL_PATH)
    print(f"✅ 成功載入 AI 模型: {MODEL_PATH}")
except FileNotFoundError:
    print(f"❌ 找不到模型檔案 '{MODEL_PATH}'，請先執行 train_radar_model.py 進行訓練！")
    exit()

# 開啟序列埠
try:
    ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=0.1)
    print(f"🔌 成功連線至 {COM_PORT}，開始進行即時預測...\n")
except Exception as e:
    print(f"❌ 無法開啟序列埠 {COM_PORT}: {e}")
    exit()

classes = ["無人 (Idle)", "近距離 (Close)", "遠距離 (Far)"]

def draw_bar(prob, length=20):
    filled = int(prob * length)
    return "█" * filled + "░" * (length - filled)

try:
    ser.reset_input_buffer()
    while True:
        if ser.in_waiting:
            try:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line == "-1":
                    continue
                parts = line.split(',')
                if len(parts) >= 19 and parts[-1] == "END":
                    # 提取 18 個特徵值
                    features = np.array([[int(x) for x in parts[0:18]]])
                    
                    # 進行預測
                    pred_class = model.predict(features)[0]
                    probabilities = model.predict_proba(features)[0]
                    
                    # 清除終端機畫面以呈現流暢動態效果
                    os.system('cls' if os.name == 'nt' else 'clear')
                    
                    print("=" * 50)
                    print("        HLK-LD2410B AI 即時距離類別預測")
                    print("=" * 50)
                    print(f"當前預測結果: \033[1;36m{classes[pred_class]}\033[0m")
                    print("-" * 50)
                    
                    # 畫出機率分布條
                    for idx, (label, prob) in enumerate(zip(classes, probabilities)):
                        bar = draw_bar(prob)
                        color_code = "1;32" if idx == pred_class else "0;37"
                        print(f"\033[{color_code}m{label:<15} : [{bar}] {prob*100:6.1f}%\033[0m")
                    
                    print("=" * 50)
                    print("提示: 按 Ctrl+C 可以安全結束預測")
                    
            except Exception as e:
                pass
        time.sleep(0.05)
except KeyboardInterrupt:
    print("\n👋 已停止即時預測。")
finally:
    ser.close()
    print("🔌 序列埠已安全關閉。")
