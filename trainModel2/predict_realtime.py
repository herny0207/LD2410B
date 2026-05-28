import serial
import joblib
import numpy as np
import time
import os

# ================= 設定區 =================
COM_PORT  = 'COM3'   # 👈 請修改為你的 COM 埠
BAUD_RATE = 115200

# 動態取得腳本所在目錄
script_dir   = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH   = os.path.join(script_dir, 'radar_model.pkl')
FEATURE_PATH = os.path.join(script_dir, 'feature_columns.pkl')
# ==========================================

# --- 前處理：原始特徵欄位定義 ---
MOTION_COLS = [f"g{i}_m" for i in range(9)]   # g0_m ~ g8_m
STATIC_COLS = [f"g{i}_s" for i in range(9)]   # g0_s ~ g8_s
BASE_COLS   = MOTION_COLS + STATIC_COLS        # 18 個原始特徵

# 平滑用的小型環形緩衝 (window=3)
SMOOTH_WINDOW = 3
smooth_buffer = []   # 存最近 SMOOTH_WINDOW 筆原始特徵（各 18 維）


def apply_statistical_features(raw_18: np.ndarray) -> np.ndarray:
    """
    輸入：長度 18 的 1D array（g0_m..g8_m, g0_s..g8_s）
    輸出：長度 24 的 1D array（原始 18 + 6 個統計特徵）
    """
    motion = raw_18[:9]
    static = raw_18[9:18]

    stats = np.array([
        motion.mean(),                     # motion_mean
        motion.std(),                      # motion_std
        motion.max() - motion.min(),       # motion_range
        static.mean(),                     # static_mean
        static.std(),                      # static_std
        static.max() - static.min(),       # static_range
    ])
    return np.concatenate([raw_18, stats])


# 載入模型與特徵欄位
try:
    model = joblib.load(MODEL_PATH)
    print(f"[OK] 成功載入 AI 模型: {MODEL_PATH}")
except FileNotFoundError:
    print(f"[Error] 找不到模型檔案 '{MODEL_PATH}'，請先執行 train_radar_model.py 進行訓練！")
    exit()

if os.path.exists(FEATURE_PATH):
    feature_columns = joblib.load(FEATURE_PATH)
    print(f"[OK] 特徵欄位已載入（{len(feature_columns)} 維）")
else:
    print("[Warning] 找不到 feature_columns.pkl，將直接使用 24 維特徵（請確認模型訓練版本）")
    feature_columns = None

# 開啟序列埠
try:
    ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=0.1)
    print(f"[Serial] 成功連線至 {COM_PORT}，開始進行即時預測...\n")
except Exception as e:
    print(f"[Error] 無法開啟序列埠 {COM_PORT}: {e}")
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
                    # 1) 提取原始 18 個特徵
                    raw_18 = np.array([int(x) for x in parts[0:18]], dtype=float)

                    # 2) 移動平均平滑（window=3）
                    smooth_buffer.append(raw_18)
                    if len(smooth_buffer) > SMOOTH_WINDOW:
                        smooth_buffer.pop(0)
                    smoothed_18 = np.mean(smooth_buffer, axis=0)

                    # 3) 加入統計特徵 (18 -> 24 維)
                    features_24 = apply_statistical_features(smoothed_18)
                    features = features_24.reshape(1, -1)

                    # 4) 進行預測
                    pred_class    = model.predict(features)[0]
                    probabilities = model.predict_proba(features)[0]

                    # 清除終端機畫面
                    os.system('cls' if os.name == 'nt' else 'clear')

                    print("=" * 50)
                    print("     HLK-LD2410B AI 即時距離類別預測（含前處理）")
                    print("=" * 50)
                    print(f"當前預測結果: \033[1;36m{classes[pred_class]}\033[0m")
                    print(f"特徵維度: 18 原始 + 6 統計 = 24 維 | 平滑窗口: {len(smooth_buffer)}/{SMOOTH_WINDOW}")
                    print("-" * 50)

                    for idx, (label, prob) in enumerate(zip(classes, probabilities)):
                        bar        = draw_bar(prob)
                        color_code = "1;32" if idx == pred_class else "0;37"
                        print(f"\033[{color_code}m{label:<15} : [{bar}] {prob*100:6.1f}%\033[0m")

                    print("=" * 50)
                    print("提示: 按 Ctrl+C 可以安全結束預測")

            except Exception as e:
                pass
        time.sleep(0.05)
except KeyboardInterrupt:
    print("\n[Info] 已停止即時預測。")
finally:
    ser.close()
    print("[Serial] 序列埠已安全關閉。")
