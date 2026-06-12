import serial
import joblib
import numpy as np
import time
import os
import threading
import math
import tkinter as tk
from PIL import Image, ImageTk

# ================= 設定區 =================
COM_PORT  = 'COM3'   # 👈 請修改為你的 COM 埠
BAUD_RATE = 115200

script_dir   = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH   = os.path.join(script_dir, 'radar_model.pkl')
FEATURE_PATH = os.path.join(script_dir, 'feature_columns.pkl')
SCALER_PATH  = os.path.join(script_dir, 'radar_scaler.pkl')

picture_dir = os.path.join(script_dir, '..', 'picture')
IMAGE_PATHS = {
    0: os.path.join(picture_dir, 'no_person.png'),   # 無人 (Idle)
    1: os.path.join(picture_dir, 'close.png'),        # 近距離 (Close)
    2: os.path.join(picture_dir, 'far.png'),          # 遠距離 (Far)
}

# ─── 視窗與動畫參數 ───
WIN_WIDTH      = 960
WIN_HEIGHT     = 540

TRANS_STEPS    = 34        # 轉場總步數
TRANS_INTERVAL = 14        # ms / 步 → 約 70fps 感
ZOOM_PUSH      = 1.10      # 舊圖推出時放大倍率
FLASH_ALPHA    = 130       # 閃光峰值 alpha (0-255)
BORDER_W       = 5         # 邊框基礎寬度 px
PULSE_INTERVAL = 25        # 邊框脈動每 xx ms 更新一次
SWITCH_THRESHOLD = 0.85    # 👈 預測機率需達此門檻才觸發畫面切換

# ─── 各類別主題色 ───
CLASS_COLORS = {           # (R, G, B)
    0: (30,  150, 255),    # 無人  → 電藍
    1: (255,  50,  20),    # 近距離 → 火紅
    2: (0,   220, 100),    # 遠距離 → 霓虹綠
}
CLASS_HEX = {
    0: "#1e96ff",
    1: "#ff3214",
    2: "#00dc64",
}
# ==========================================

# ─── 前處理設定 ───
EWMA_ALPHA   = 0.7         # 👈 已修正為 0.7，符合 70/30 黃金比例
ewma_current = None        # 現在改為儲存 24 維的平滑狀態

def apply_statistical_features(raw_18: np.ndarray) -> np.ndarray:
    """將 18 維原始特徵工程擴充至 24 維（包含 Mean, Std, Range）"""
    motion = raw_18[:9]
    static = raw_18[9:18]
    stats = np.array([
        motion.mean(), motion.std(), motion.max() - motion.min(),
        static.mean(), static.std(), static.max() - static.min(),
    ])
    return np.concatenate([raw_18, stats])


# ─── 載入模型 ───
try:
    model = joblib.load(MODEL_PATH)
    print(f"[OK] 成功載入 AI 模型: {MODEL_PATH}")
except FileNotFoundError:
    print(f"[Error] 找不到模型檔案 '{MODEL_PATH}'，請先執行訓練系統！")
    exit()

try:
    scaler = joblib.load(SCALER_PATH)
    print(f"[OK] 成功載入特徵標準化器: {SCALER_PATH}")
except FileNotFoundError:
    print(f"[Error] 找不到標準化器 '{SCALER_PATH}'，請確認訓練系統是否有匯出！")
    exit()

feature_columns = None
if os.path.exists(FEATURE_PATH):
    feature_columns = joblib.load(FEATURE_PATH)
    print(f"[OK] 特徵欄位已載入（{len(feature_columns)} 維）")
else:
    print("[Warning] 找不到 feature_columns.pkl，直接使用 24 維特徵")

try:
    ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=0.1)
    print(f"[Serial] 成功連線至 {COM_PORT}，開始進行即時預測...\n")
except Exception as e:
    print(f"[Error] 無法開啟序列埠 {COM_PORT}: {e}")
    exit()

classes = ["無人 (Idle)", "近距離 (Close)", "遠距離 (Far)"]

def draw_bar(prob, length=16):
    filled = int(prob * length)
    return "█" * filled + "░" * (length - filled)


# ──────────────────────────────────────────────────────────────────
#  RadarImageWindow  ─  帶驚艷轉場效果的 GUI 視窗
# ──────────────────────────────────────────────────────────────────
class RadarImageWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("HLK-LD2410B 即時預測")
        self.root.geometry(f"{WIN_WIDTH}x{WIN_HEIGHT}")
        self.root.resizable(False, False)
        self.root.configure(bg="black")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # ── 預載圖片（LANCZOS 高品質） ──
        self._pil_images: dict[int, Image.Image] = {}
        for cls_id, path in IMAGE_PATHS.items():
            img = Image.open(path).convert("RGBA")
            img = img.resize((WIN_WIDTH, WIN_HEIGHT), Image.LANCZOS)
            self._pil_images[cls_id] = img

        # ── Canvas ──
        self.canvas = tk.Canvas(
            self.root, width=WIN_WIDTH, height=WIN_HEIGHT,
            bg="black", highlightthickness=0
        )
        self.canvas.pack()

        # ── 主圖 item ──
        first = self._composite(self._pil_images[0])
        self._tk_image = ImageTk.PhotoImage(first)
        self._img_id   = self.canvas.create_image(0, 0, anchor="nw", image=self._tk_image)

        # ── 彩色邊框 ──
        self._border_id = self.canvas.create_rectangle(
            1, 1, WIN_WIDTH - 1, WIN_HEIGHT - 1,
            outline=CLASS_HEX[0], width=BORDER_W, fill=""
        )

        # ── 右上角類別標籤 ──
        self._label_id = self.canvas.create_text(
            WIN_WIDTH - 18, 18, anchor="ne",
            text="▶ 初始化...",
            font=("Microsoft JhengHei", 24, "bold"),
            fill=CLASS_HEX[0]
        )

        # ── 左下角機率長條 ──
        self._prob_id = self.canvas.create_text(
            14, WIN_HEIGHT - 10, anchor="sw",
            text="",
            font=("Consolas", 12),
            fill="white",
            justify="left"
        )

        # ── 左上角脈動指示點 ──
        R = 9
        self._dot_id = self.canvas.create_oval(
            14, 14, 14 + R*2, 14 + R*2,
            fill=CLASS_HEX[0], outline=""
        )

        # ── 確保疊層順序 ──
        for item in [self._border_id, self._label_id, self._prob_id, self._dot_id]:
            self.canvas.tag_raise(item)

        # ── 狀態 ──
        self._current_cls  = 0
        self._old_cls      = 0
        self._target_cls   = 0
        self._animating    = False
        self._pulse_phase  = 0.0
        self._pulse_job    = None

        # ── 線程安全佇列 ──
        self._pending = None
        self._lock    = threading.Lock()

        self.root.after(100, self._poll_update)
        self._pulse_border()

    def request_update(self, pred_class: int, probs):
        with self._lock:
            self._pending = (pred_class, list(probs))

    def _poll_update(self):
        with self._lock:
            update       = self._pending
            self._pending = None

        if update is not None:
            cls_id, probs = update
            self._update_hud(cls_id, probs)
            if cls_id != self._current_cls and not self._animating:
                self._old_cls    = self._current_cls
                self._target_cls = cls_id
                self._start_transition()

        self.root.after(50, self._poll_update)

    def _start_transition(self):
        self._animating = True
        if self._pulse_job:
            self.root.after_cancel(self._pulse_job)
            self._pulse_job = None
        self._transition_step(0)

    def _ease_in(self, t: float) -> float: return t * t * t
    def _ease_out(self, t: float) -> float: return 1.0 - (1.0 - t) ** 3

    def _apply_zoom_alpha(self, cls_id: int, scale: float, alpha: int) -> Image.Image:
        src = self._pil_images[cls_id]
        if abs(scale - 1.0) < 0.003:
            zoomed = src
        else:
            nw = int(WIN_WIDTH  * scale)
            nh = int(WIN_HEIGHT * scale)
            zoomed = src.resize((nw, nh), Image.BILINEAR)
            lx = (nw - WIN_WIDTH)  // 2
            ly = (nh - WIN_HEIGHT) // 2
            zoomed = zoomed.crop((lx, ly, lx + WIN_WIDTH, ly + WIN_HEIGHT))
        r, g, b, a = zoomed.split()
        a = a.point(lambda _: alpha)
        return Image.merge("RGBA", (r, g, b, a))

    def _transition_step(self, step: int):
        half   = TRANS_STEPS // 2
        bg     = Image.new("RGBA", (WIN_WIDTH, WIN_HEIGHT), (0, 0, 0, 255))

        if step <= half:
            t       = step / half
            et      = self._ease_in(t)
            alpha   = int(255 * (1.0 - et))
            scale   = 1.0 + (ZOOM_PUSH - 1.0) * et

            img = self._apply_zoom_alpha(self._old_cls, scale, alpha)
            bg.alpha_composite(img)

            flash_a = int(FLASH_ALPHA * math.sin(math.pi * min(t / 0.85, 1.0)))
            if flash_a > 4:
                cr, cg, cb = CLASS_COLORS[self._target_cls]
                flash = Image.new("RGBA", (WIN_WIDTH, WIN_HEIGHT), (cr, cg, cb, flash_a))
                bg.alpha_composite(flash)

            bc = self._lerp_hex(CLASS_COLORS[self._old_cls], CLASS_COLORS[self._target_cls], et)
            bw = BORDER_W + int(12 * et)
            self.canvas.itemconfig(self._border_id, outline=bc, width=bw)

        else:
            t       = (step - half) / half
            et      = self._ease_out(t)
            alpha   = int(255 * et)
            scale   = ZOOM_PUSH - (ZOOM_PUSH - 1.0) * et

            img = self._apply_zoom_alpha(self._target_cls, scale, alpha)
            bg.alpha_composite(img)

            bc = CLASS_HEX[self._target_cls]
            bw = BORDER_W + int(12 * (1.0 - et))
            self.canvas.itemconfig(self._border_id, outline=bc, width=bw)

        tk_img = ImageTk.PhotoImage(bg.convert("RGB"))
        self.canvas.itemconfig(self._img_id, image=tk_img)
        self._tk_image = tk_img

        next_step = step + 1
        if next_step > TRANS_STEPS:
            self._current_cls = self._target_cls
            self._animating   = False
            self.canvas.itemconfig(self._border_id, outline=CLASS_HEX[self._current_cls], width=BORDER_W)
            self.canvas.itemconfig(self._dot_id, fill=CLASS_HEX[self._current_cls])
            self._pulse_border()
        else:
            self.root.after(TRANS_INTERVAL, lambda: self._transition_step(next_step))

    def _pulse_border(self):
        if self._animating:
            return
        self._pulse_phase += 0.10
        pulse = (math.sin(self._pulse_phase) + 1) / 2
        r, g, b = CLASS_COLORS[self._current_cls]
        lo, hi  = 0.22, 1.0
        i  = lo + (hi - lo) * pulse
        rc = f"#{min(255,int(r*i)):02x}{min(255,int(g*i)):02x}{min(255,int(b*i)):02x}"
        bw = BORDER_W + int(2 * pulse)
        self.canvas.itemconfig(self._border_id, outline=rc, width=bw)
        self.canvas.itemconfig(self._dot_id, fill=rc)
        self._pulse_job = self.root.after(PULSE_INTERVAL, self._pulse_border)

    def _update_hud(self, cls_id: int, probs: list):
        self.canvas.itemconfig(self._label_id, text=f"▶ {classes[cls_id]}", fill=CLASS_HEX[cls_id])
        lines = []
        for idx, (label, prob) in enumerate(zip(classes, probs)):
            bar  = draw_bar(prob)
            mark = "◀" if idx == cls_id else "  "
            lines.append(f"{mark} {label:<14} [{bar}] {prob*100:5.1f}%")
        self.canvas.itemconfig(self._prob_id, text="\n".join(lines))

    @staticmethod
    def _composite(img: Image.Image) -> Image.Image:
        bg = Image.new("RGBA", img.size, (0, 0, 0, 255))
        bg.alpha_composite(img)
        return bg.convert("RGB")

    @staticmethod
    def _lerp_hex(c1: tuple, c2: tuple, t: float) -> str:
        r = min(255, int(c1[0] + (c2[0] - c1[0]) * t))
        g = min(255, int(c1[1] + (c2[1] - c1[1]) * t))
        b = min(255, int(c1[2] + (c2[2] - c1[2]) * t))
        return f"#{r:02x}{g:02x}{b:02x}"

    def _on_close(self):
        if self._pulse_job:
            self.root.after_cancel(self._pulse_job)
        self.root.destroy()


# ──────────────────────────────────────────
#  序列讀取子線程（前處理順序已更新修正）
# ──────────────────────────────────────────
def serial_thread(gui: RadarImageWindow, stop_event: threading.Event):
    global ewma_current
    ser.reset_input_buffer()
    while not stop_event.is_set():
        if ser.in_waiting:
            try:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line == "-1":
                    continue
                parts = line.split(',')
                if len(parts) >= 19 and parts[-1] == "END":
                    # 1. 取得 18 維原始雷達數據
                    raw_18 = np.array([int(x) for x in parts[0:18]], dtype=float)

                    # 2. ⚡【步驟一：特徵工程擴充】先將 18 維原始值擴充至 24 維
                    features_24_raw = apply_statistical_features(raw_18)

                    # 3. ⚡【步驟二：EWMA 平滑】對擴充完的 24 維特徵進行指數平滑計算
                    if ewma_current is None:
                        ewma_current = features_24_raw
                    else:
                        ewma_current = EWMA_ALPHA * features_24_raw + (1 - EWMA_ALPHA) * ewma_current

                    # 4. 進行特徵標準化轉換
                    features_scaled = scaler.transform(ewma_current.reshape(1, -1))
                    
                    # 5. 模型預測
                    pred_class      = model.predict(features_scaled)[0]
                    probabilities   = model.predict_proba(features_scaled)[0]

                    # 終端機即時除錯輸出
                    os.system('cls' if os.name == 'nt' else 'clear')
                    print("=" * 50)
                    print("     HLK-LD2410B AI 即時距離類別預測（修正順序版）")
                    print("=" * 50)
                    print(f"當前預測結果: \033[1;36m{classes[pred_class]}\033[0m")
                    print(f"處理順序: 18維原始 ──► 24維擴充 ──► 24維共同 EWMA (α={EWMA_ALPHA})")
                    print("-" * 50)
                    for idx, (label, prob) in enumerate(zip(classes, probabilities)):
                        bar        = draw_bar(prob, 20)
                        color_code = "1;32" if idx == pred_class else "0;37"
                        print(f"\033[{color_code}m{label:<15} : [{bar}] {prob*100:6.1f}%\033[0m")
                    print("=" * 50)
                    print("提示: 按 Ctrl+C 或關閉視窗可以安全結束預測")

                    # 雙重動態過濾：只有最高機率 ≥ 門檻值才通知 GUI 切換畫面
                    max_prob = probabilities[pred_class]
                    if max_prob >= SWITCH_THRESHOLD:
                        gui.request_update(pred_class, probabilities)
                    else:
                        print(f"[Hold] 信心度 {max_prob*100:.1f}% < {SWITCH_THRESHOLD*100:.0f}%，維持目前畫面")
            except Exception:
                pass
        time.sleep(0.02)


# ──────────────────────────────────────────
#  主程式
# ──────────────────────────────────────────
if __name__ == "__main__":
    stop_event = threading.Event()
    root = tk.Tk()
    gui  = RadarImageWindow(root)

    t = threading.Thread(target=serial_thread, args=(gui, stop_event), daemon=True)
    t.start()

    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        ser.close()
        print("\n[Info] 已停止即時預測。")
        print("[Serial] 序列埠已安全關閉。")