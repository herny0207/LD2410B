import pandas as pd
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier
from sklearn.svm import SVC
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.metrics import classification_report
import joblib

print("=== 毫米波雷達多模型比較與訓練系統 ===")

# 1. 自動搜尋並讀取資料夾內這三個 csv 檔案
csv_files = ['data_0_idle.csv', 'data_1_close.csv', 'data_2_far.csv']
train_list = []
test_list = []

print("正在讀取、進行時序切分並合併 CSV 檔案...")
for file in csv_files:
    try:
        df = pd.read_csv(file)
        # 針對每一種類別，按時序切分前 80% 為訓練集，後 20% 為測試集，防止滑動窗口造成資料洩漏
        split_idx = int(len(df) * 0.8)
        df_train = df.iloc[:split_idx]
        df_test = df.iloc[split_idx:]
        
        train_list.append(df_train)
        test_list.append(df_test)
        print(f"-> 成功載入 {file} (訓練集: {len(df_train)} 筆, 測試集: {len(df_test)} 筆)")
    except FileNotFoundError:
        print(f"錯誤：找不到 {file}，請確認是否已執行對應的收集程式！")
        exit()

# 合併成訓練集與測試集
train_dataset = pd.concat(train_list, ignore_index=True)
test_dataset = pd.concat(test_list, ignore_index=True)

# 分離 特徵 (X) 與 標籤 (y)
X_train = train_dataset.drop(columns=['label'])
y_train = train_dataset['label']
X_test = test_dataset.drop(columns=['label'])
y_test = test_dataset['label']

print(f"總數據打包完成。訓練集計: {len(train_dataset)} 筆，測試集計: {len(test_dataset)} 筆。")

print("\n正在進行多模型對比訓練與評估...")

# 定義多個分類器模型
models = {
    "Random Forest": RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42),
    "SVM (RBF Kernel)": SVC(probability=True, random_state=42),
    "Gradient Boosting": HistGradientBoostingClassifier(random_state=42),
    "K-Nearest Neighbors": KNeighborsClassifier(n_neighbors=5),
    "Neural Network (MLP)": MLPClassifier(hidden_layer_sizes=(64, 32), max_iter=500, random_state=42)
}

X_train_val = X_train.values
X_test_val = X_test.values
y_train_val = y_train.values
y_test_val = y_test.values

results = []
best_model_name = None
best_model = None
best_test_acc = -1.0

# 走訪訓練所有模型
for name, clf in models.items():
    try:
        clf.fit(X_train_val, y_train_val)
        train_acc = clf.score(X_train_val, y_train_val) * 100
        test_acc = clf.score(X_test_val, y_test_val) * 100
        results.append({
            "Model": name,
            "Train Acc": f"{train_acc:.2f}%",
            "Test Acc": f"{test_acc:.2f}%"
        })
        
        if test_acc > best_test_acc:
            best_test_acc = test_acc
            best_model_name = name
            best_model = clf
    except Exception as e:
        print(f"訓練 {name} 發生錯誤: {e}")

# 顯示多模型比較表
df_results = pd.DataFrame(results)
print("\n================== 模型效能排行榜 ==================")
print(df_results.to_string(index=False))
print("====================================================")

print(f"\n獲勝模型是：【{best_model_name}】，測試集準確度達 {best_test_acc:.2f}%！")

# 輸出獲勝模型的詳細報告
y_pred = best_model.predict(X_test_val)
print(f"\n【{best_model_name}】的詳細統計指標 (Classification Report):")
print(classification_report(y_test_val, y_pred, target_names=["無人(0)", "近距離(1)", "遠距離(2)"]))

# 5. 匯出最好的模型
import os
script_dir = os.path.dirname(os.path.abspath(__file__))
model_filename = os.path.join(script_dir, "radar_model.pkl")
joblib.dump(best_model, model_filename)
print(f"\n恭喜！獲勝模型已匯出儲存為: {model_filename}")
print("現在你們可以使用這顆 'AI大腦' 去做即時的互動式廣告切換了！")