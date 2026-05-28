import serial
import joblib
import numpy as np
import time
import os

# ================= 設定區 =================
COM_PORT  = 'COM3'   # 👈 請修改為你的 COM 埠
BAUD_RATE = 115200

script_dir   = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH   = os.path.join(script_dir, 'radar_model.pkl')
FEATURE_PATH = os.path.join(script_dir, 'feature_columns.pkl')
# ==========================================

WINDOW_SIZE   = 5     # 滑動窗口大小
SMOOTH_WINDOW = 3     # 移動平均平滑窗口大小
frame_buffer  = []    # 存 5 幀完整資料（各 18 維）
smooth_buffer = []    # 存最近 3 幀原始資料（用於平滑）


def smooth_frame(raw_18: np.ndarray, buffer: list) -> np.ndarray:
    """
    對單幀 18 維特徵做移動平均平滑（與訓練時一致，window=3）。
    """
    buffer.append(raw_18.copy())
    if len(buffer) > SMOOTH_WINDOW:
        buffer.pop(0)
    return np.mean(buffer, axis=0)


def add_statistical_features_window(window_90: np.ndarray) -> np.ndarray:
    """
    對 90 維扁平化窗口特徵加入統計特徵（與訓練時一致）。
    前 45 維為 motion (5 幀 × 9 gates)，後 45 維為 static。
    新增 6 個統計特徵 -> 共 96 維。
    """
    # 重建為 5 × 18 矩陣
    window_matrix = window_90.reshape(WINDOW_SIZE, 18)   # shape: (5, 18)
    motion_vals   = window_matrix[:, :9].flatten()        # 前 9 欄 = motion
    static_vals   = window_matrix[:, 9:].flatten()        # 後 9 欄 = static

    stats = np.array([
        motion_vals.mean(),
        motion_vals.std(),
        motion_vals.max() - motion_vals.min(),
        static_vals.mean(),
        static_vals.std(),
        static_vals.max() - static_vals.min(),
    ])
    return np.concatenate([window_90, stats])


# 載入模型
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
    print("[Warning] 找不到 feature_columns.pkl，將使用預設 96 維特徵")
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
                    smoothed_18 = smooth_frame(raw_18, smooth_buffer)

                    # 3) 存入滑動窗口緩衝
                    frame_buffer.append(smoothed_18)
                    if len(frame_buffer) > WINDOW_SIZE:
                        frame_buffer.pop(0)

                    if len(frame_buffer) == WINDOW_SIZE:
                        # 4) 攤平 5 幀 -> 90 維
                        window_90 = np.array(frame_buffer).flatten()  # shape: (90,)

                        # 5) 加入統計特徵 (90 -> 96 維)
                        features_96 = add_statistical_features_window(window_90)
                        features = features_96.reshape(1, -1)

                        # 6) 進行預測
                        pred_class    = model.predict(features)[0]
                        probabilities = model.predict_proba(features)[0]

                        os.system('cls' if os.name == 'nt' else 'clear')

                        print("=" * 55)
                        print("  HLK-LD2410B AI 即時距離類別預測（滑動窗口 + 前處理）")
                        print("=" * 55)
                        print(f"當前預測結果: \033[1;36m{classes[pred_class]}\033[0m")
                        print(f"特徵維度: 90 原始 + 6 統計 = 96 維 | 窗口: {len(frame_buffer)}/{WINDOW_SIZE} | 平滑: {len(smooth_buffer)}/{SMOOTH_WINDOW}")
                        print("-" * 55)

                        for idx, (label, prob) in enumerate(zip(classes, probabilities)):
                            bar        = draw_bar(prob)
                            color_code = "1;32" if idx == pred_class else "0;37"
                            print(f"\033[{color_code}m{label:<15} : [{bar}] {prob*100:6.1f}%\033[0m")

                        print("=" * 55)
                        print("提示: 按 Ctrl+C 可以安全結束預測")

            except Exception as e:
                pass
        time.sleep(0.05)
except KeyboardInterrupt:
    print("\n[Info] 已停止即時預測。")
finally:
    ser.close()
    print("[Serial] 序列埠已安全關閉。")
