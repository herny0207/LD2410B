import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier
from sklearn.svm import SVC
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.metrics import classification_report, confusion_matrix
import joblib
import os

print("=== 毫米波雷達【5 幀滑動窗口 + 資料前處理】多模型比較與訓練系統 ===")

# ============================================================
#  前處理函式定義
# ============================================================

def remove_outliers_iqr(df, feature_cols, factor=1.5):
    """
    IQR 異常值移除：移除超出 [Q1-1.5*IQR, Q3+1.5*IQR] 的資料列（僅對訓練集）。
    """
    mask = pd.Series([True] * len(df), index=df.index)
    for col in feature_cols:
        Q1    = df[col].quantile(0.25)
        Q3    = df[col].quantile(0.75)
        IQR   = Q3 - Q1
        lower = Q1 - factor * IQR
        upper = Q3 + factor * IQR
        mask  = mask & (df[col] >= lower) & (df[col] <= upper)
    return df[mask].copy()


def apply_rolling_mean(df, feature_cols, window=3):
    """
    移動平均平滑：對每個特徵欄位做滾動均值（center=True，邊緣不產生 NaN）。
    """
    df_smooth = df.copy()
    for col in feature_cols:
        df_smooth[col] = df[col].rolling(window=window, min_periods=1, center=True).mean()
    return df_smooth


def add_statistical_features_window(df, n_gates=9, n_frames=5):
    """
    對 5 幀 × 18 維（共 90 維）的滑動窗口資料，計算整個窗口內
    motion 通道與 static 通道的統計特徵（mean, std, max-min 差值）。
    新增 6 個統計特徵，使維度從 90 -> 96。
    欄位命名規則：t0_g0_m … t4_g8_s（或扁平化後的 col0..col89）。
    """
    df = df.copy()

    # 找出所有 motion / static 欄位
    motion_cols = [c for c in df.columns if c != 'label' and '_m' in c]
    static_cols = [c for c in df.columns if c != 'label' and '_s' in c]

    df['win_motion_mean']  = df[motion_cols].mean(axis=1)
    df['win_motion_std']   = df[motion_cols].std(axis=1).fillna(0)
    df['win_motion_range'] = df[motion_cols].max(axis=1) - df[motion_cols].min(axis=1)

    df['win_static_mean']  = df[static_cols].mean(axis=1)
    df['win_static_std']   = df[static_cols].std(axis=1).fillna(0)
    df['win_static_range'] = df[static_cols].max(axis=1) - df[static_cols].min(axis=1)

    return df


# ============================================================
#  1. 讀取 CSV
# ============================================================
csv_files = ['data_0_idle.csv', 'data_1_close.csv', 'data_2_far.csv']
train_list = []
test_list  = []

# 腳本所在目錄（用於讀取同目錄的 CSV）
script_dir = os.path.dirname(os.path.abspath(__file__))

print("\n[步驟 1] 正在讀取 CSV 並進行時序切分...")
for file in csv_files:
    # 優先找腳本同目錄，找不到再找上層目錄（root CSV）
    file_path = os.path.join(script_dir, file)
    if not os.path.exists(file_path):
        file_path = os.path.join(os.path.dirname(script_dir), file)
    try:
        df = pd.read_csv(file_path)

        # 時序切分（前 80% 訓練，後 20% 測試）
        split_idx = int(len(df) * 0.80)
        df_train  = df.iloc[:split_idx].copy()
        df_test   = df.iloc[split_idx:].copy()

        train_list.append(df_train)
        test_list.append(df_test)
        print(f"  -> 成功載入 {file} (訓練集: {len(df_train)} 筆, 測試集: {len(df_test)} 筆)")
    except FileNotFoundError:
        print(f"  錯誤：找不到 {file_path}，請確認是否已執行對應的收集程式！")
        exit()

train_dataset = pd.concat(train_list, ignore_index=True)
test_dataset  = pd.concat(test_list,  ignore_index=True)

feature_cols = [c for c in train_dataset.columns if c != 'label']
print(f"\n  原始特徵數：{len(feature_cols)} 維（5 幀 × 18 = 90 維）")
print(f"  合併後 -> 訓練集: {len(train_dataset)} 筆，測試集: {len(test_dataset)} 筆")


# ============================================================
#  2. 異常值移除 (IQR) — 只對訓練集
# ============================================================
print("\n[步驟 2] 異常值移除 (IQR, factor=3.0)...")
before = len(train_dataset)
train_dataset = remove_outliers_iqr(train_dataset, feature_cols, factor=3.0)
after = len(train_dataset)
print(f"  訓練集：{before} 筆 -> 移除 {before - after} 筆異常值 -> 剩餘 {after} 筆")


# ============================================================
#  3. 移動平均平滑 (Rolling Mean, window=3)
# ============================================================
print("\n[步驟 3] 移動平均平滑 (Rolling Mean, window=3)...")
train_dataset = apply_rolling_mean(train_dataset, feature_cols, window=3)
test_dataset  = apply_rolling_mean(test_dataset,  feature_cols, window=3)
print("  平滑完成。")


# ============================================================
#  4. 統計特徵工程 (窗口級：新增 6 個統計特徵，90 -> 96 維)
# ============================================================
print("\n[步驟 4] 統計特徵工程（窗口級 motion/static mean, std, range）...")
train_dataset = add_statistical_features_window(train_dataset)
test_dataset  = add_statistical_features_window(test_dataset)
new_feat_count = len([c for c in train_dataset.columns if c != 'label'])
print(f"  特徵維度：90 -> {new_feat_count} 維")


# ============================================================
#  5. 分離特徵與標籤
# ============================================================
X_train = train_dataset.drop(columns=['label'])
y_train = train_dataset['label']
X_test  = test_dataset.drop(columns=['label'])
y_test  = test_dataset['label']

X_train_val = X_train.values
X_test_val  = X_test.values
y_train_val = y_train.values
y_test_val  = y_test.values

print(f"\n  最終特徵維度：{X_train_val.shape[1]} 維")
print(f"  訓練集：{len(X_train_val)} 筆 | 測試集：{len(X_test_val)} 筆")


# ============================================================
#  6. 多模型訓練與評估
# ============================================================
print("\n[步驟 5] 多模型對比訓練與評估...")

models = {
    "Random Forest":        RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42),
    "SVM (RBF Kernel)":     SVC(probability=True, random_state=42),
    "Gradient Boosting":    HistGradientBoostingClassifier(random_state=42),
    "K-Nearest Neighbors":  KNeighborsClassifier(n_neighbors=5),
    "Neural Network (MLP)": MLPClassifier(hidden_layer_sizes=(64, 32), max_iter=500, random_state=42),
}

results = []
best_model_name = None
best_model      = None
best_test_acc   = -1.0

for name, clf in models.items():
    try:
        clf.fit(X_train_val, y_train_val)
        train_acc = clf.score(X_train_val, y_train_val) * 100
        test_acc  = clf.score(X_test_val,  y_test_val)  * 100
        results.append({
            "Model":     name,
            "Train Acc": f"{train_acc:.2f}%",
            "Test Acc":  f"{test_acc:.2f}%",
        })
        if test_acc > best_test_acc:
            best_test_acc   = test_acc
            best_model_name = name
            best_model      = clf
        print(f"  [{name}]  Train: {train_acc:.2f}%  Test: {test_acc:.2f}%")
    except Exception as e:
        print(f"  訓練 {name} 發生錯誤: {e}")


# ============================================================
#  7. 結果報告與各模型詳細指標
# ============================================================
df_results = pd.DataFrame(results)
print("\n================== 模型效能排行榜 ==================")
print(df_results.to_string(index=False))
print("====================================================")

class_names = ["無人(0)", "近距離(1)", "遠距離(2)"]

print("\n================== 各模型詳細評估與混淆矩陣 ==================")
for name, clf in models.items():
    try:
        y_pred = clf.predict(X_test_val)
        print(f"\n* 模型：【{name}】")
        print("--- 分類報告 (Classification Report) ---")
        print(classification_report(y_test_val, y_pred, target_names=class_names))
        
        print("--- 混淆矩陣 (Confusion Matrix) ---")
        cm = confusion_matrix(y_test_val, y_pred)
        print(f"{'':<12} 預測: {class_names[0]:<8} {class_names[1]:<8} {class_names[2]:<8}")
        for i, label in enumerate(class_names):
            print(f"真實: {label:<8} {cm[i][0]:<12d} {cm[i][1]:<12d} {cm[i][2]:<12d}")
        print("-" * 55)
    except Exception as e:
        print(f"無法產生 {name} 的詳細指標: {e}")

print(f"\n獲勝模型：【{best_model_name}】，測試集準確度達 {best_test_acc:.2f}%！")


# ============================================================
#  8. 匯出模型與特徵欄位
# ============================================================
model_filename   = os.path.join(script_dir, "radar_model.pkl")
feature_filename = os.path.join(script_dir, "feature_columns.pkl")

final_feature_cols = list(X_train.columns)
joblib.dump(best_model,         model_filename)
joblib.dump(final_feature_cols, feature_filename)

print(f"\n[OK] 模型已儲存：{model_filename}")
print(f"[OK] 特徵欄位已儲存：{feature_filename}")
print("現在可以執行 predict_realtime.py 進行即時預測！")