# GroundingDINO 工業數據集自動標注系統

基於 GroundingDINO 的工業生產場景自動/輔助標注工具，支援與 LabelMe 格式無縫整合，並提供完整的 fine-tune pipeline 以提升特定工站的標注精度。

---

## 系統架構

```
工業圖片
   │
   ▼
[01] 資料集探索           ← 分析現有 LabelMe JSON，統計類別分布
   │
   ▼
[02] 零樣本自動標注        ← GroundingDINO 推論，輸出 LabelMe JSON
   │
   ▼
[人工校正]               ← 在 LabelMe 中快速確認/修正
   │
   ├──────────────────────────────────────────┐
   ▼                                          ▼
[03] 轉換為 odvg 格式      [持續使用校正後的標注結果]
   │
   ▼
[04] Fine-tune 設定        ← 基於去年工站資料訓練模型
   │
   ▼
[Fine-tuned 模型]          ← 精度顯著提升（+10~20 AP）
   │
   ▼
[05] 評估                 ← 與人工標注比對 IoU / mAP
```

---

## 目錄結構

```
model_learning/
├── README.md
├── requirements.txt
├── config/
│   └── config.yaml              # 全局設定（模型路徑、閾值、類別等）
├── data/
│   └── sample/                  # 範例 LabelMe JSON 與圖片
├── src/
│   ├── __init__.py
│   ├── labelme_utils.py         # LabelMe JSON 讀寫工具
│   ├── gdino_inference.py       # GroundingDINO 推論封裝
│   ├── converters.py            # 格式轉換：LabelMe ↔ odvg ↔ COCO
│   └── evaluator.py             # 評估模組（IoU、mAP、召回率）
├── scripts/
│   ├── 01_explore_dataset.py    # 分析現有標注資料集
│   ├── 02_zero_shot_annotate.py # 零樣本自動標注
│   ├── 03_labelme_to_odvg.py    # LabelMe → odvg 轉換（供 fine-tune 用）
│   ├── 04_finetune_setup.py     # 產生 fine-tune 設定檔
│   └── 05_evaluate.py           # 評估自動標注品質
├── notebooks/
│   └── demo.ipynb               # 互動示範
└── docs/
    ├── workflow.md               # 完整使用流程說明
    └── labelme_format.md         # LabelMe JSON 格式說明
```

---

## 快速開始

### 1. 安裝依賴

```bash
pip install -r requirements.txt

# 安裝 GroundingDINO
git clone https://github.com/IDEA-Research/GroundingDINO.git
cd GroundingDINO && pip install -e . && cd ..

# 下載預訓練權重
mkdir -p weights
wget -q https://github.com/IDEA-Research/GroundingDINO/releases/download/v0.1.0-alpha/groundingdino_swint_ogc.pth \
     -O weights/groundingdino_swint_ogc.pth
```

### 2. 設定 config.yaml

```bash
cp config/config.yaml config/config_local.yaml
# 修改 model_path、data_dir、categories 等設定
```

### 3. 探索現有資料集

```bash
python scripts/01_explore_dataset.py --data_dir /path/to/your/labelme/jsons
```

### 4. 執行零樣本自動標注

```bash
python scripts/02_zero_shot_annotate.py \
  --image_dir /path/to/new/images \
  --output_dir /path/to/output \
  --config config/config.yaml
```

### 5. 轉換格式供 fine-tune 使用

```bash
python scripts/03_labelme_to_odvg.py \
  --input_dir /path/to/labelme/jsons \
  --output_dir /path/to/odvg/output \
  --image_dir /path/to/images
```

### 6. 評估自動標注品質

```bash
python scripts/05_evaluate.py \
  --pred_dir /path/to/auto/annotations \
  --gt_dir /path/to/manual/annotations
```

---

## Fine-tune 策略說明

### 為什麼同工站資料 fine-tune 效果好？

| 場景 | 零樣本 AP | Fine-tune 後 AP |
|------|----------|----------------|
| 通用物件（人、車） | ~45-55 | ~60-65 |
| 工業通用零件（螺絲、手套） | ~35-45 | ~55-65 |
| 工業專用零件/缺陷 | ~15-30 | ~50-60 |

> 同工站不同年份資料：年間差異遠小於零樣本泛化差距，fine-tune 遷移效果極佳。

### 建議的迭代流程

```
第一輪（冷啟動）
  → 零樣本標注全部圖片
  → 人工校正（預估需校正 60-80%）
  → 校正後資料加入訓練集

第二輪（首次 fine-tune）
  → 使用去年全部標注 + 第一輪校正資料
  → fine-tune GroundingDINO
  → 重新自動標注新圖片
  → 人工校正（預估需校正 20-40%）

第三輪以後（持續改進）
  → 持續累積校正資料
  → 定期 re-fine-tune
  → 人工校正量持續下降
```

---

## 支援的格式

| 格式 | 說明 | 用途 |
|------|------|------|
| LabelMe JSON | 標準 LabelMe 輸出格式 | 標注輸入/輸出、人工校正 |
| odvg JSONL | Open-GroundingDino 訓練格式 | Fine-tune 訓練資料 |
| COCO JSON | 標準 COCO 格式 | 評估、與其他工具整合 |

---

## 授權

本工具為輔助腳本集合，依賴項目授權：
- GroundingDINO：Apache 2.0
- Open-GroundingDino：MIT
