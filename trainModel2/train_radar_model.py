import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier
from sklearn.svm import SVC
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.metrics import classification_report, confusion_matrix
import joblib
import os

print("=== 毫米波雷達【原始單幀 + 資料前處理】多模型比較與訓練系統 ===")

# ============================================================
#  前處理函式定義
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


def apply_rolling_mean(df, feature_cols, window=3):
    df_smooth = df.copy()
    for col in feature_cols:
        df_smooth[col] = df[col].rolling(window=window, min_periods=1, center=True).mean()
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
    """給定原始 DataFrame list 和切分比例，回傳前處理後的 X_train, X_test, y_train, y_test。"""
    train_list, test_list = [], []
    for df in all_dfs:
        split_idx = int(len(df) * split_ratio)
        train_list.append(df.iloc[:split_idx].copy())
        test_list.append(df.iloc[split_idx:].copy())

    train_ds = pd.concat(train_list, ignore_index=True)
    test_ds  = pd.concat(test_list,  ignore_index=True)

    # 1. IQR 異常值移除（只對訓練集）
    train_ds = remove_outliers_iqr(train_ds, feature_cols_base, factor=3.0)

    # 2. 移動平均平滑
    train_ds = apply_rolling_mean(train_ds, feature_cols_base, window=3)
    test_ds  = apply_rolling_mean(test_ds,  feature_cols_base, window=3)

    # 3. 統計特徵工程
    train_ds = add_statistical_features(train_ds, feature_cols_base)
    test_ds  = add_statistical_features(test_ds,  feature_cols_base)

    X_train = train_ds.drop(columns=['label'])
    y_train = train_ds['label']
    X_test  = test_ds.drop(columns=['label'])
    y_test  = test_ds['label']

    return X_train, X_test, y_train, y_test


# ============================================================
#  1. 讀取所有 CSV（只讀一次）
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
print(f"  原始特徵數：{len(feature_cols_base)} 維")


# ============================================================
#  2. 嘗試所有切分比例 × 所有模型
# ============================================================
split_ratios = [0.80]

model_defs = {
    "Random Forest":        lambda: RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42),
    "SVM (RBF)":            lambda: SVC(probability=True, random_state=42),
    "Gradient Boosting":    lambda: HistGradientBoostingClassifier(random_state=42),
    "KNN":                  lambda: KNeighborsClassifier(n_neighbors=5),
    "MLP":                  lambda: MLPClassifier(hidden_layer_sizes=(64, 32), max_iter=500, random_state=42),
}

summary_rows = []          # 彙整所有組合結果
global_best_acc   = -1.0
global_best_model = None
global_best_name  = ""
global_best_split = 0.0
global_best_Xtrain = None
global_best_Xtest  = None
global_best_ytest  = None

print("\n[步驟 2] 開始進行 80/20 切分與多模型訓練...\n")
print(f"{'切分比例':<10} {'模型':<22} {'訓練集':<8} {'測試集':<8} {'Train%':<10} {'Test%':<10}")
print("-" * 68)

for ratio in split_ratios:
    X_train, X_test, y_train, y_test = preprocess_split(raw_dfs, ratio, feature_cols_base)
    n_train = len(X_train)
    n_test  = len(X_test)

    for mname, mfunc in model_defs.items():
        try:
            clf = mfunc()
            clf.fit(X_train.values, y_train.values)
            train_acc = clf.score(X_train.values, y_train.values) * 100
            test_acc  = clf.score(X_test.values,  y_test.values)  * 100

            print(f"{int(ratio*100):>3}% / {int((1-ratio)*100):>2}%   {mname:<22} {n_train:<8} {n_test:<8} {train_acc:>7.2f}%  {test_acc:>7.2f}%")

            summary_rows.append({
                "切分":      f"{int(ratio*100)}/{int((1-ratio)*100)}",
                "模型":      mname,
                "訓練筆數":  n_train,
                "測試筆數":  n_test,
                "Train Acc": f"{train_acc:.2f}%",
                "Test Acc":  f"{test_acc:.2f}%",
                "_test_acc": test_acc,
                "_ratio":    ratio,
                "_clf":      clf,
                "_X_train":  X_train,
                "_X_test":   X_test,
                "_y_test":   y_test,
            })

            if test_acc > global_best_acc:
                global_best_acc    = test_acc
                global_best_model  = clf
                global_best_name   = mname
                global_best_split  = ratio
                global_best_Xtrain = X_train
                global_best_Xtest  = X_test
                global_best_ytest  = y_test

        except Exception as e:
            print(f"{int(ratio*100):>3}%/{int((1-ratio)*100):>2}%  {mname:<22}  ERROR: {e}")

    print()   # 每個切分比例之間空一行


print("\n" + "=" * 75)
print("              ★ 80/20 切分下各模型結果彙整 ★")
print("=" * 75)
df_summary = pd.DataFrame(summary_rows)[["切分", "模型", "訓練筆數", "測試筆數", "Train Acc", "Test Acc"]]

# 依 Test Acc 排序（高到低）
df_summary["_sort"] = [r["_test_acc"] for r in summary_rows]
df_summary = df_summary.sort_values("_sort", ascending=False).drop(columns=["_sort"])
print(df_summary.to_string(index=False))
print("=" * 75)

print(f"\n[最佳組合] 全域最佳組合：切分【{int(global_best_split*100)}/{int((1-global_best_split)*100)}】× 模型【{global_best_name}】")
print(f"   測試集準確度：{global_best_acc:.2f}%")


# ============================================================
#  4. 詳細報告（最佳切分比例下各模型的詳細指標與混淆矩陣）
# ============================================================
class_names = ["無人(0)", "近距離(1)", "遠距離(2)"]
print(f"\n================== 最佳比例【{int(global_best_split*100)}/{int((1-global_best_split)*100)}】下各模型的詳細評估與混淆矩陣 ==================")
best_ratio_rows = [r for r in summary_rows if r["_ratio"] == global_best_split]

for row in best_ratio_rows:
    mname  = row["模型"]
    clf    = row["_clf"]
    X_test = row["_X_test"]
    y_test = row["_y_test"]
    
    try:
        y_pred = clf.predict(X_test.values)
        print(f"\n* 模型：【{mname}】 (測試集準確度: {row['Test Acc']})")
        print("--- 分類報告 (Classification Report) ---")
        print(classification_report(y_test.values, y_pred, target_names=class_names))
        
        print("--- 混淆矩陣 (Confusion Matrix) ---")
        cm = confusion_matrix(y_test.values, y_pred)
        print(f"{'':<12} 預測: {class_names[0]:<8} {class_names[1]:<8} {class_names[2]:<8}")
        for i, label in enumerate(class_names):
            print(f"真實: {label:<8} {cm[i][0]:<12d} {cm[i][1]:<12d} {cm[i][2]:<12d}")
        print("-" * 55)
    except Exception as e:
        print(f"無法產生 {mname} 的詳細指標: {e}")


# ============================================================
#  5. 儲存最佳模型
# ============================================================
script_dir       = os.path.dirname(os.path.abspath(__file__))
model_filename   = os.path.join(script_dir, "radar_model.pkl")
feature_filename = os.path.join(script_dir, "feature_columns.pkl")

joblib.dump(global_best_model,            model_filename)
joblib.dump(list(global_best_Xtrain.columns), feature_filename)

print(f"\n[OK] 最佳模型已儲存：{model_filename}")
print(f"[OK] 特徵欄位已儲存：{feature_filename}")
print("現在可以執行 predict_realtime.py 進行即時預測！")
