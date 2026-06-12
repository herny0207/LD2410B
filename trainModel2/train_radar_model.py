import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier
from sklearn.svm import SVC
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler, LabelEncoder  # 👈 新增：LabelEncoder
from sklearn.metrics import classification_report, confusion_matrix
import joblib
import os

# 嘗試引入 xgboost，若未安裝則提示
try:
    from xgboost import XGBClassifier
    HAS_XGBOOST = True
except ImportError:
    HAS_XGBOOST = False
    print("[Warning] 偵測到未安裝 xgboost 套件，請先於終端機執行: pip install xgboost")

print("=== 毫米波雷達【最新前處理順序 + 擴充 XGBoost + IQR精準防誤殺】多模型比較系統 ===")

# ============================================================
#  前處理函式定義
# ============================================================

def remove_outliers_iqr(df, feature_cols, factor=10.0):
    """
    優化版 IQR：精準限縮檢查欄位。
    傳入統計欄位後，可防止原始 18 個 Gate 正常的人體走動能譜被誤殺。
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


def apply_ewma_smoothing(df, feature_cols, alpha=0.6):
    df_smooth = df.copy()
    for col in feature_cols:
        df_smooth[col] = df[col].ewm(alpha=alpha, adjust=False).mean()
    return df_smooth


def add_statistical_features(df, feature_cols):
    motion_cols = [c for c in feature_cols if c.endswith('_m')]
    static_cols = [c for c in feature_cols if c.endswith('_s')]
    df = df.copy()
    df['motion_mean']  = df[motion_cols].mean(axis=1)
    df['motion_std']   = df[motion_cols].std(axis=1).fillna(0)
    df['motion_range'] = df[motion_cols].max(axis=1) - df[motion_cols].min(axis=1)
    df['static_mean']  = df[static_cols].mean(axis=1)
    df['static_std']   = df[static_cols].std(axis=1).fillna(0)
    df['static_range'] = df[static_cols].max(axis=1) - df[static_cols].min(axis=1)
    return df


def preprocess_split(all_dfs, split_ratio, feature_cols_base):
    """
    依照使用者指定之最完美邏輯順序：
    先擴充特徵 -> 切分數據 -> 訓練集 IQR 異常移除 -> EWMA 平滑 -> 標準化
    """
    # 1. 先擴充統計特徵 (18 -> 24 維)
    extended_dfs = []
    for df in all_dfs:
        ext_df = add_statistical_features(df, feature_cols_base)
        extended_dfs.append(ext_df)
    
    all_feature_cols = [c for c in extended_dfs[0].columns if c != 'label']

    # 2. 切分訓練集與測試集
    train_list, test_list = [], []
    for df in extended_dfs:
        split_idx = int(len(df) * split_ratio)
        train_list.append(df.iloc[:split_idx].copy())
        test_list.append(df.iloc[split_idx:].copy())

    train_ds = pd.concat(train_list, ignore_index=True)
    test_ds  = pd.concat(test_list,  ignore_index=True)

    # 3. 👈 修正：IQR 異常值移除（僅對訓練集的「6個統計特徵」生效，防止原始 18 通道被誤殺）
    stats_cols = ['motion_mean', 'motion_std', 'motion_range', 'static_mean', 'static_std', 'static_range']
    
    orig_len = len(train_ds)
    train_ds = remove_outliers_iqr(train_ds, stats_cols, factor=1.0)
    new_len = len(train_ds)
    print(f"  -> [IQR 檢查] 原始訓練集筆數: {orig_len} | 剩餘筆數: {new_len} (剔除率: {((orig_len - new_len)/orig_len)*100:.2f}%)")

    # 4. EWMA 平滑（24維整體平滑，兼顧物理因果與穩定度）
    train_ds = apply_ewma_smoothing(train_ds, all_feature_cols, alpha=0.7)
    test_ds  = apply_ewma_smoothing(test_ds,  all_feature_cols, alpha=0.7)

    X_train = train_ds.drop(columns=['label'])
    y_train = train_ds['label']
    X_test  = test_ds.drop(columns=['label'])
    y_test  = test_ds['label']

    # 5. StandardScaler 特徵標準化
    scaler = StandardScaler()
    X_train_scaled = pd.DataFrame(scaler.fit_transform(X_train), columns=X_train.columns)
    X_test_scaled  = pd.DataFrame(scaler.transform(X_test), columns=X_test.columns)

    return X_train_scaled, X_test_scaled, y_train, y_test, scaler


# ============================================================
#  1. 讀取所有 CSV
# ============================================================
csv_files = ['data_0_idle.csv', 'data_1_close.csv', 'data_2_far.csv']
raw_dfs   = []

print("\n[步驟 1] 讀取 CSV...")
for file in csv_files:
    try:
        df = pd.read_csv(file)
        if "g0_m_t4" in df.columns:
            single_frame_cols = [f"g{g}_m_t4" for g in range(9)] + [f"g{g}_s_t4" for g in range(9)] + ["label"]
            df = df[single_frame_cols]
            new_cols = {f"g{g}_m_t4": f"g{g}_m" for g in range(9)}
            new_cols.update({f"g{g}_s_t4": f"g{g}_s" for g in range(9)})
            df = df.rename(columns=new_cols)
        raw_dfs.append(df)
        print(f"  -> 成功載入 {file}（{len(df)} 筆）")
    except FileNotFoundError:
        print(f"  錯誤：找不到 {file}！")
        exit()

feature_cols_base = [c for c in raw_dfs[0].columns if c != 'label']

# ============================================================
#  2. 構建模型定義（包含 XGBoost）
# ============================================================
model_defs = {
    "Random Forest":        lambda: RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42),
    "SVM (RBF)":            lambda: SVC(probability=True, random_state=42),
    "Gradient Boosting":    lambda: HistGradientBoostingClassifier(random_state=42),
    "KNN":                  lambda: KNeighborsClassifier(n_neighbors=5),
    "MLP":                  lambda: MLPClassifier(hidden_layer_sizes=(64, 32), max_iter=500, random_state=42),
}

# 動態加入 XGBoost
if HAS_XGBOOST:
    model_defs["XGBoost"] = lambda: XGBClassifier(
        n_estimators=100, 
        max_depth=4, 
        learning_rate=0.1, 
        eval_metric='mlogloss', 
        random_state=42
    )

summary_rows = []
global_best_acc   = -1.0
global_best_model = None
global_best_name  = ""
global_best_scaler = None
global_best_Xtrain = None

print("\n[步驟 2] 開始進行多模型訓練（流水線優化版）...\n")
print(f"{'模型':<22} {'訓練集':<8} {'測試集':<8} {'Train Acc':<12} {'Test Acc':<12}")
print("-" * 70)

split_ratios = [0.80]
for ratio in split_ratios:
    X_train, X_test, y_train, y_test, scaler = preprocess_split(raw_dfs, ratio, feature_cols_base)
    
    # 對標籤進行編碼（防範 XGBoost 報錯）
    le = LabelEncoder()
    y_train_encoded = le.fit_transform(y_train.values)
    y_test_encoded  = le.transform(y_test.values)

    n_train = len(X_train)
    n_test  = len(X_test)

    for mname, mfunc in model_defs.items():
        try:
            clf = mfunc()
            
            # 訓練與評分
            clf.fit(X_train.values, y_train_encoded)
            train_acc = clf.score(X_train.values, y_train_encoded) * 100
            test_acc  = clf.score(X_test.values,  y_test_encoded)  * 100

            print(f"{mname:<22} {n_train:<8} {n_test:<8} {train_acc:>9.2f}%   {test_acc:>9.2f}%")

            summary_rows.append({
                "模型": mname,
                "Test Acc": test_acc,
                "_clf": clf,
                "_X_test": X_test,
                "_y_test_encoded": y_test_encoded
            })

            if test_acc > global_best_acc:
                global_best_acc   = test_acc
                global_best_model = clf
                global_best_name  = mname
                global_best_scaler = scaler
                global_best_Xtrain = X_train

        except Exception as e:
            print(f"{mname:<22} ERROR: {e}")

# ============================================================
#  3. 印出詳細報告與混淆矩陣
# ============================================================
class_names = ["無人(0)", "近距離(1)", "遠距離(2)"]
print("\n" + "="*80 + "\n★ 最佳模型詳細評估與混淆矩陣 ★\n" + "="*80)

for row in summary_rows:
    if row["模型"] == global_best_name:
        y_pred = row["_clf"].predict(row["_X_test"].values)
        print(f"* 最終勝出最佳模型：【{row['模型']}】 (測試集最終準確度: {row['Test Acc']:.2f}%)")
        print("\n--- 分類報告 (Classification Report) ---")
        print(classification_report(row["_y_test_encoded"], y_pred, target_names=class_names))
        
        print("--- 混淆矩陣 (Confusion Matrix) ---")
        cm = confusion_matrix(row["_y_test_encoded"], y_pred)
        print(f"{'':<12} 預測: {class_names[0]:<8} {class_names[1]:<8} {class_names[2]:<8}")
        for i, label in enumerate(class_names):
            print(f"真實: {label:<8} {cm[i][0]:<12d} {cm[i][1]:<12d} {cm[i][2]:<12d}")

# ============================================================
#  4. 輸出特徵重要性 (XGBoost 亦支援此功能)
# ============================================================
# ============================================================
#  5. 儲存戰果
# ============================================================
script_dir = os.path.dirname(os.path.abspath(__file__))
joblib.dump(global_best_model, os.path.join(script_dir, "radar_model.pkl"))
joblib.dump(list(global_best_Xtrain.columns), os.path.join(script_dir, "feature_columns.pkl"))
joblib.dump(global_best_scaler, os.path.join(script_dir, "radar_scaler.pkl"))

print(f"\n[OK] 最佳模型、特徵欄位與標準化外掛 (radar_scaler.pkl) 已安全儲存！")