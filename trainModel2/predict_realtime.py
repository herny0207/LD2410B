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
SCALER_PATH  = os.path.join(script_dir, 'radar_scaler.pkl')  # 👈 1. 新增：標準化器路徑
# ==========================================

# --- 前處理：原始特徵欄位定義 ---
MOTION_COLS = [f"g{i}_m" for i in range(9)]   # g0_m ~ g8_m
STATIC_COLS = [f"g{i}_s" for i in range(9)]   # g0_s ~ g8_s
BASE_COLS   = MOTION_COLS + STATIC_COLS        # 18 個原始特徵

# 👈 2. 修改：EWMA 平滑參數（與訓練集前處理一模一樣）
EWMA_ALPHA = 0.6
ewma_current = None  # 用來記錄上一幀平滑後的狀態

def apply_statistical_features(raw_18: np.ndarray) -> np.ndarray:
    """
    輸入：長度 18 的 1D array（g0_m..g8_m, g0_s..g8_s）
    輸出：長度 24 的 1D array（原始 18 + 6 個統計特徵）
    """
    motion = raw_18[:9]
    static = raw_18[9:18]

    stats = np.array([
        motion.mean(),                      # motion_mean
        motion.std(),                       # motion_std
        motion.max() - motion.min(),        # motion_range
        static.mean(),                      # static_mean
        static.std(),                       # static_std
        static.max() - static.min(),        # static_range
    ])
    return np.concatenate([raw_18, stats])


# 載入模型、特徵欄位與標準化器
try:
    model = joblib.load(MODEL_PATH)
    print(f"[OK] 成功載入 AI 模型: {MODEL_PATH}")
except FileNotFoundError:
    print(f"[Error] 找不到模型檔案 '{MODEL_PATH}'，請先執行訓練系統！")
    exit()

try:
    scaler = joblib.load(SCALER_PATH)  # 👈 3. 新增：強烈要求載入 Scaler
    print(f"[OK] 成功載入特徵標準化器: {SCALER_PATH}")
except FileNotFoundError:
    print(f"[Error] 找不到標準化檔案 '{SCALER_PATH}'，請確認訓練系統是否有匯出！")
    exit()

if os.path.exists(FEATURE_PATH):
    feature_columns = joblib.load(FEATURE_PATH)
    print(f"[OK] 特徵欄位已載入（{len(feature_columns)} 維）")
else:
    print("[Warning] 找不到 feature_columns.pkl，將直接使用 24 維特徵")
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

                    # 2) 👈 修改：改用 EWMA 指數加權移動平滑，摒棄 Center Rolling Mean
                    if ewma_current is None:
                        ewma_current = raw_18  # 第一幀初始化
                    else:
                        ewma_current = EWMA_ALPHA * raw_18 + (1 - EWMA_ALPHA) * ewma_current
                    
                    # 3) 加入統計特徵 (18 -> 24 維)
                    features_24 = apply_statistical_features(ewma_current)
                    
                    # 4) 👈 修正：特徵標準化轉換 (這步沒做，SVM/MLP 預測會完全失準！)
                    # scaler.transform 必須吃 2D 陣列 [[...]]
                    features_scaled = scaler.transform(features_24.reshape(1, -1))

                    # 5) 進行預測 (改用經過標準化後的特徵)
                    pred_class    = model.predict(features_scaled)[0]
                    probabilities = model.predict_proba(features_scaled)[0]

                    # 清除終端機畫面
                    os.system('cls' if os.name == 'nt' else 'clear')

                    print("=" * 50)
                    print("     HLK-LD2410B AI 即時距離類別預測（含前處理）")
                    print("=" * 50)
                    print(f"當前預測結果: \033[1;36m{classes[pred_class]}\033[0m")
                    print(f"特徵維度: 18 原始 + 6 統計 = 24 維 | 平滑模式: EWMA (α={EWMA_ALPHA})")
                    print("-" * 50)

                    for idx, (label, prob) in enumerate(zip(classes, probabilities)):
                        bar        = draw_bar(prob)
                        color_code = "1;32" if idx == pred_class else "0;37"
                        print(f"\033[{color_code}m{label:<15} : [{bar}] {prob*100:6.1f}%\033[0m")

                    print("=" * 50)
                    print("提示: 按 Ctrl+C 可以安全結束預測")

            except Exception as e:
                pass
        time.sleep(0.02) # 👈 降低微調時延，搭配雷達 0.2 秒的發送頻率，能做到更即時
except KeyboardInterrupt:
    print("\n[Info] 已停止即時預測。")
finally:
    ser.close()
    print("[Serial] 序列埠已安全關閉。")