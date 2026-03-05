# 完整使用流程說明

## 工作流程總覽

```
【已有標注資料】                        【新圖片】
去年各工站 LabelMe JSON                 今年各工站圖片
         │                                   │
         ▼                                   ▼
  [01] 探索資料集                    [02] 零樣本自動標注
  - 統計類別分布                     - GroundingDINO 推論
  - 確認資料品質                     - 輸出 LabelMe JSON
  - 決定訓練類別                              │
         │                                   ▼
         │                          [人工在 LabelMe 校正]
         │                          - 開啟自動標注 JSON
         │                          - 快速確認/修正框
         │                          - 儲存校正後 JSON
         │                                   │
         ▼                                   │
  [03] 格式轉換                              │
  LabelMe → odvg JSONL                       │
         │                                   │
         ▼                                   │
  [04] Fine-tune 設定                        │
  生成訓練設定 + 訓練腳本                     │
         │                                   │
         ▼                                   │
  Open-GroundingDino 訓練                    │
  （去年資料 + 第一輪校正資料）               │
         │                                   │
         ▼                                   │
  Fine-tuned 模型 ◄──────────────────────────┘
         │                      下一輪使用 fine-tuned 模型
         ▼                      重複自動標注 → 校正 → 訓練
  [05] 評估品質
  - 計算 mAP、Recall
  - 找出低品質圖片
```

---

## 第一步：安裝環境

```bash
# 安裝 Python 依賴
pip install -r requirements.txt

# 選項 A：使用 HuggingFace（推薦新手）
# 不需額外安裝，transformers 會自動下載模型

# 選項 B：安裝本地 GroundingDINO（推薦生產環境）
git clone https://github.com/IDEA-Research/GroundingDINO.git
cd GroundingDINO
export CUDA_HOME=/usr/local/cuda  # 指向你的 CUDA 目錄
pip install -e .
cd ..

# 下載預訓練權重
mkdir weights
wget -q https://github.com/IDEA-Research/GroundingDINO/releases/download/v0.1.0-alpha/groundingdino_swint_ogc.pth \
     -O weights/groundingdino_swint_ogc.pth
```

---

## 第二步：設定類別

編輯 `config/config.yaml`，填入你的工站物件類別：

```yaml
categories:
  - "screw"      # 螺絲
  - "bolt"       # 螺栓
  - "glove"      # 手套
  # 加入你的類別...
```

**重要提示：**
- 用英文描述效果最好（模型以英文預訓練）
- 描述越具體越好：`"M3 screw"` 比 `"screw"` 更精確
- 可用自然語言短句：`"yellow safety helmet"`

---

## 第三步：探索現有資料

```bash
python scripts/01_explore_dataset.py \
  --data_dir /path/to/your/labelme/jsons \
  --output stats.json
```

輸出會顯示：
- 各類別的標注數量（幫助確認訓練資料是否均衡）
- 各工站的圖片分布
- 資料品質問題（缺失圖片、空標注）

---

## 第四步：零樣本自動標注新圖片

```bash
# 使用 HuggingFace 模型
python scripts/02_zero_shot_annotate.py \
  --image_dir /path/to/this_year/images \
  --output_dir /path/to/auto_annotations \
  --config config/config.yaml

# 先跑 5 張測試效果
python scripts/02_zero_shot_annotate.py \
  --image_dir /path/to/images \
  --output_dir /path/to/test_output \
  --config config/config.yaml \
  --limit 5 \
  --visualize
```

---

## 第五步：人工校正

1. 在 LabelMe 中打開輸出目錄
2. 每張圖片的自動標注已儲存為對應 JSON
3. 校正流程：
   - 刪除錯誤的框（False Positive）
   - 補上漏掉的框（False Negative）
   - 調整不夠準確的框
   - 修正錯誤的類別標籤

**效率提示：**
- 自動標注的信心分數儲存在 shape 的 description 欄位
- 高分數（>0.7）的框通常準確，可快速確認
- 低分數（<0.4）的框建議仔細確認

---

## 第六步：準備 Fine-tune 資料

```bash
# 將已校正的 LabelMe JSON 轉換為 odvg 格式
python scripts/03_labelme_to_odvg.py \
  --input_dir /path/to/corrected_labelme_jsons \
  --output_dir /path/to/odvg_data \
  --image_dir /path/to/images \
  --split \
  --train_ratio 0.8
```

---

## 第七步：生成 Fine-tune 設定並訓練

```bash
# 生成設定檔
python scripts/04_finetune_setup.py \
  --odvg_dir /path/to/odvg_data \
  --image_dir /path/to/images \
  --output_dir finetune_setup \
  --gpu_count 1 \
  --epochs 12

# 按照生成的說明安裝 Open-GroundingDino
# 然後執行訓練
bash finetune_setup/train.sh
```

---

## 第八步：評估與迭代

```bash
# 評估自動標注品質（需要有人工標注作為 GT）
python scripts/05_evaluate.py \
  --pred_dir /path/to/auto_annotations \
  --gt_dir /path/to/manual_annotations \
  --output_html report.html \
  --output_low_quality low_quality_images.txt
```

報告中包含：
- 每個類別的 AP 和 Recall
- 品質低的圖片列表（優先安排人工校正）
- HTML 視覺化報告

---

## Fine-tune 後的參數調整建議

| 場景 | box_threshold | text_threshold | 備註 |
|------|--------------|----------------|------|
| 零樣本，追求召回率 | 0.25~0.30 | 0.20~0.25 | 誤報較多，需人工篩選 |
| 零樣本，追求精確率 | 0.40~0.50 | 0.30~0.35 | 漏報較多 |
| Fine-tune 後，均衡 | 0.40~0.45 | 0.30 | 推薦設定 |
| Fine-tune 後，高品質 | 0.50~0.60 | 0.35~0.40 | 用於高信心自動標注 |

---

## 常見問題

**Q: 自動標注的框不夠準確怎麼辦？**
A: 降低 `box_threshold`（更多框但需要更多人工校正），或收集更多校正資料後重新 fine-tune。

**Q: 某個類別完全偵測不到？**
A: 嘗試更改類別名稱的描述（如 `"metal fastener"` 代替 `"screw"`），或收集該類別的樣本進行 fine-tune。

**Q: Fine-tune 後效果反而下降？**
A: 可能是訓練資料太少（建議每類至少 100 個標注框）或訓練 epoch 過多（過擬合）。嘗試降低 `epochs` 或混合更多樣化的工站資料。

**Q: 同工站不同年份的圖片差異很大怎麼辦？**
A: 在訓練資料中加入跨年份的資料，以及做資料增強（翻轉、旋轉、亮度調整），讓模型學習類別本身而非特定光線/角度的特徵。
