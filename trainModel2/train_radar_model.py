import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier
from sklearn.svm import SVC
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler  # 👈 修正：引入標準化
from sklearn.metrics import classification_report, confusion_matrix
import joblib
import os

print("=== 毫米波雷達【頂級前處理 + 多模型比較】互動看板訓練系統 ===")

# ============================================================
#  前處理函式定義 (優化版)
# ============================================================

def remove_outliers_iqr(df, feature_cols, factor=3.0):
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
    """ 
    👈 修正：改用 EWMA (指數加權移動平均) 替代 Center Rolling Mean
    防止 Data Leakage，符合硬體即時因果關係 (Causal Linearity)，對最新訊號反應更快。
    """
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
    train_list, test_list = [], []
    for df in all_dfs:
        split_idx = int(len(df) * split_ratio)
        train_list.append(df.iloc[:split_idx].copy())
        test_list.append(df.iloc[split_idx:].copy())

    train_ds = pd.concat(train_list, ignore_index=True)
    test_ds  = pd.concat(test_list,  ignore_index=True)

    # 1. IQR 異常值移除（只對訓練集，防止測試集資訊流失）
    train_ds = remove_outliers_iqr(train_ds, feature_cols_base, factor=3.0)

    # 2. EWMA 平滑（防止資料外洩）
    train_ds = apply_ewma_smoothing(train_ds, feature_cols_base, alpha=0.6)
    test_ds  = apply_ewma_smoothing(test_ds,  feature_cols_base, alpha=0.6)

    # 3. 統計特徵工程
    train_ds = add_statistical_features(train_ds, feature_cols_base)
    test_ds  = add_statistical_features(test_ds,  feature_cols_base)

    X_train = train_ds.drop(columns=['label'])
    y_train = train_ds['label']
    X_test  = test_ds.drop(columns=['label'])
    y_test  = test_ds['label']

    # 4. 👈 修正：特徵標準化 (讓 SVM 與 MLP 發揮 100% 實力)
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
#  2. 訓練多模型與橫向評估
# ============================================================
split_ratios = [0.80]

model_defs = {
    "Random Forest":        lambda: RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42),
    "SVM (RBF)":            lambda: SVC(probability=True, random_state=42),
    "Gradient Boosting":    lambda: HistGradientBoostingClassifier(random_state=42),
    "KNN":                  lambda: KNeighborsClassifier(n_neighbors=5),
    "MLP":                  lambda: MLPClassifier(hidden_layer_sizes=(64, 32), max_iter=500, random_state=42),
}

summary_rows = []
global_best_acc   = -1.0
global_best_model = None
global_best_name  = ""
global_best_scaler = None
global_best_Xtrain = None

print("\n[步驟 2] 開始進行多模型訓練（已導入特徵標準化）...\n")
print(f"{'模型':<22} {'訓練集筆數':<10} {'測試集筆數':<10} {'Train Acc':<12} {'Test Acc':<12}")
print("-" * 70)

for ratio in split_ratios:
    # 修正：回傳值增加了 scaler
    X_train, X_test, y_train, y_test, scaler = preprocess_split(raw_dfs, ratio, feature_cols_base)
    n_train = len(X_train)
    n_test  = len(X_test)

    for mname, mfunc in model_defs.items():
        try:
            clf = mfunc()
            clf.fit(X_train.values, y_train.values)
            train_acc = clf.score(X_train.values, y_train.values) * 100
            test_acc  = clf.score(X_test.values,  y_test.values)  * 100

            print(f"{mname:<22} {n_train:<10} {n_test:<10} {train_acc:>9.2f}%   {test_acc:>9.2f}%")

            summary_rows.append({
                "模型": mname,
                "Test Acc": test_acc,
                "_clf": clf,
                "_X_test": X_test,
                "_y_test": y_test
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
        print(f"* 最佳模型：【{row['模型']}】 (測試集最終準確度: {row['Test Acc']:.2f}%)")
        print("\n--- 分類報告 (Classification Report) ---")
        print(classification_report(row["_y_test"].values, y_pred, target_names=class_names))
        
        print("--- 混淆矩陣 (Confusion Matrix) ---")
        cm = confusion_matrix(row["_y_test"].values, y_pred)
        print(f"{'':<12} 預測: {class_names[0]:<8} {class_names[1]:<8} {class_names[2]:<8}")
        for i, label in enumerate(class_names):
            print(f"真實: {label:<8} {cm[i][0]:<12d} {cm[i][1]:<12d} {cm[i][2]:<12d}")

# ============================================================
#  4. 輸出特徵重要性 (如果是樹狀模型的話，報告加分神物)
# ============================================================
if global_best_name in ["Random Forest", "Gradient Boosting"]:
    print("\n--- 特徵重要性分析 (Feature Importance Top 5) ---")
    importances = global_best_model.feature_importances_
    indices = np.argsort(importances)[::-1]
    for f in range(5):
        print(f"{f+1}. 特徵: {global_best_Xtrain.columns[indices[f]]:<12} 貢獻度: {importances[indices[f]]*100:.2f}%")

# ============================================================
#  5. 儲存戰果 (包含模型、特徵欄位名、標準化器)
# ============================================================
script_dir = os.path.dirname(os.path.abspath(__file__))
joblib.dump(global_best_model, os.path.join(script_dir, "radar_model.pkl"))
joblib.dump(list(global_best_Xtrain.columns), os.path.join(script_dir, "feature_columns.pkl"))
joblib.dump(global_best_scaler, os.path.join(script_dir, "radar_scaler.pkl"))  # 👈 修正：一定要存 scaler！

print(f"\n[OK] 最佳模型、特徵欄位與標準化外掛 (radar_scaler.pkl) 已安全儲存！")