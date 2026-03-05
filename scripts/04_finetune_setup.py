"""
腳本 04：Fine-tune 環境設定與設定檔生成

功能：
  - 生成 Open-GroundingDino 所需的訓練設定檔
  - 自動下載預訓練權重（可選）
  - 生成訓練啟動腳本
  - 提供各硬體環境的訓練指令範例

使用方式：
  python scripts/04_finetune_setup.py \
    --odvg_dir /path/to/odvg/output \
    --image_dir /path/to/images \
    --output_dir /path/to/finetune/setup \
    --pretrain_checkpoint weights/groundingdino_swint_ogc.pth

設定完成後執行訓練：
  bash /path/to/finetune/setup/train.sh
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# Open-GroundingDino 訓練設定模板（基於 Swin-T 骨幹）
TRAINING_CONFIG_TEMPLATE = '''# Open-GroundingDino Fine-tune 設定
# 自動生成 by 04_finetune_setup.py

modelname = "groundingdino"
backbone = "swin_T_224_1k"
position_embedding = "sine"
pe_temperatureH = 20
pe_temperatureW = 20
return_interm_indices = [1, 2, 3]
backbone_freeze_keywords = None
enc_layers = 6
dec_layers = 6
pre_norm = False
dim_feedforward = 2048
hidden_dim = 256
dropout = 0.0
nheads = 8
num_queries = 900
query_dim = 4
num_patterns = 0
num_feature_levels = 4
enc_n_points = 4
dec_n_points = 4
two_stage_type = "standard"
two_stage_bbox_embed_share = False
two_stage_class_embed_share = False
transformer_activation = "relu"
dec_pred_bbox_embed_share = True
dn_box_noise_scale = 1.0
dn_label_noise_ratio = 0.5
dn_label_coef = 1.0
dn_bbox_coef = 1.0
embed_init_tgt = True
dn_labelbook_size = 2000
max_text_len = 256
text_encoder_type = "bert-base-uncased"
use_text_enhancer = True
use_fusion_layer = True
use_checkpoint = True
use_transformer_ckpt = True
use_text_cross_attention = True
text_dropout = 0.0
fusion_dropout = 0.0
fusion_droppath = 0.1
sub_sentence_present = True

# 訓練參數
batch_size = 2            # 依 GPU 記憶體調整：8GB→2, 16GB→4, 24GB→8
lr = 1e-4
lr_backbone = 1e-5
lr_text_encoder = 5e-5    # BERT fine-tune 學習率
weight_decay = 1e-4
epochs = {epochs}
lr_drop = {lr_drop}
clip_max_norm = 0.1

# 資料設定（自動填入）
train_data = "{train_data}"
val_data = "{val_data}"

# 輸出設定
output_dir = "{output_dir}"
save_checkpoint_interval = 1
'''

TRAIN_SCRIPT_TEMPLATE = '''#!/bin/bash
# Open-GroundingDino Fine-tune 訓練腳本
# 自動生成 by 04_finetune_setup.py

# ===== 環境設定 =====
OPEN_GDINO_DIR="{open_gdino_dir}"   # Open-GroundingDino 目錄
GPU_COUNT={gpu_count}               # GPU 數量
CONFIG="{config_path}"
DATASETS="{datasets_json}"
OUTPUT_DIR="{output_dir}"
PRETRAIN_CKPT="{pretrain_checkpoint}"

# ===== 基本檢查 =====
if [ ! -d "$OPEN_GDINO_DIR" ]; then
    echo "[錯誤] Open-GroundingDino 目錄不存在：$OPEN_GDINO_DIR"
    echo "請先 clone：git clone https://github.com/longzw1997/Open-GroundingDino.git"
    exit 1
fi

if [ ! -f "$PRETRAIN_CKPT" ]; then
    echo "[警告] 預訓練權重不存在：$PRETRAIN_CKPT"
    echo "請先下載：見 docs/workflow.md"
fi

# ===== 執行訓練 =====
cd $OPEN_GDINO_DIR

if [ "$GPU_COUNT" -eq 1 ]; then
    # 單 GPU 訓練
    python main.py \\
        --config_file "$CONFIG" \\
        --datasets "$DATASETS" \\
        --output_dir "$OUTPUT_DIR" \\
        --pretrain_model_path "$PRETRAIN_CKPT" \\
        --options batch_size={batch_size} epochs={epochs}
else
    # 多 GPU 分散式訓練
    python -m torch.distributed.launch \\
        --nproc_per_node=$GPU_COUNT \\
        main.py \\
        --config_file "$CONFIG" \\
        --datasets "$DATASETS" \\
        --output_dir "$OUTPUT_DIR" \\
        --pretrain_model_path "$PRETRAIN_CKPT" \\
        --options batch_size={batch_size} epochs={epochs}
fi
'''

DATASETS_JSON_TEMPLATE = [
    {
        "root": "{image_dir}",
        "anno": "{train_jsonl}",
        "label_map": "{label_map}",
        "dataset_mode": "od",
    }
]


def generate_finetune_setup(
    odvg_dir: str,
    image_dir: str,
    output_dir: str,
    pretrain_checkpoint: str = "weights/groundingdino_swint_ogc.pth",
    open_gdino_dir: str = "Open-GroundingDino",
    gpu_count: int = 1,
    batch_size: int = 2,
    epochs: int = 12,
) -> None:
    """生成 fine-tune 所需的所有設定檔。"""

    os.makedirs(output_dir, exist_ok=True)

    # 找到 odvg 相關檔案
    train_jsonl = os.path.join(odvg_dir, "dataset_od_train.jsonl")
    val_jsonl = os.path.join(odvg_dir, "dataset_od_val.jsonl")
    label_map_path = os.path.join(odvg_dir, "label_map.json")

    # 若無分割檔，使用全量資料
    if not os.path.exists(train_jsonl):
        train_jsonl = os.path.join(odvg_dir, "dataset_od.jsonl")
        val_jsonl = train_jsonl

    if not os.path.exists(label_map_path):
        print(f"[警告] 找不到 label_map.json，請先執行腳本 03")

    # 讀取類別數量
    num_classes = 0
    if os.path.exists(label_map_path):
        with open(label_map_path) as f:
            label_map = json.load(f)
        num_classes = len(label_map)
        print(f"[類別] 讀取到 {num_classes} 個類別")

    # 生成訓練設定檔
    lr_drop = max(1, epochs - 3)
    config_content = TRAINING_CONFIG_TEMPLATE.format(
        epochs=epochs,
        lr_drop=lr_drop,
        train_data=os.path.abspath(train_jsonl),
        val_data=os.path.abspath(val_jsonl),
        output_dir=os.path.abspath(os.path.join(output_dir, "checkpoints")),
    )
    config_path = os.path.join(output_dir, "cfg_finetune.py")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(config_content)
    print(f"[設定] 訓練設定檔：{config_path}")

    # 生成資料集設定 JSON
    datasets_content = [
        {
            "root": os.path.abspath(image_dir),
            "anno": os.path.abspath(train_jsonl),
            "label_map": os.path.abspath(label_map_path) if os.path.exists(label_map_path) else "",
            "dataset_mode": "od",
        }
    ]
    datasets_json_path = os.path.join(output_dir, "datasets_finetune.json")
    with open(datasets_json_path, "w", encoding="utf-8") as f:
        json.dump(datasets_content, f, ensure_ascii=False, indent=2)
    print(f"[設定] 資料集設定：{datasets_json_path}")

    # 生成訓練腳本
    train_script = TRAIN_SCRIPT_TEMPLATE.format(
        open_gdino_dir=os.path.abspath(open_gdino_dir),
        gpu_count=gpu_count,
        config_path=os.path.abspath(config_path),
        datasets_json=os.path.abspath(datasets_json_path),
        output_dir=os.path.abspath(os.path.join(output_dir, "checkpoints")),
        pretrain_checkpoint=os.path.abspath(pretrain_checkpoint),
        batch_size=batch_size,
        epochs=epochs,
    )
    train_script_path = os.path.join(output_dir, "train.sh")
    with open(train_script_path, "w", encoding="utf-8") as f:
        f.write(train_script)
    os.chmod(train_script_path, 0o755)
    print(f"[設定] 訓練腳本：{train_script_path}")

    # 生成執行說明
    instructions = f"""# Fine-tune 執行說明

## 前置準備

### 1. 安裝 Open-GroundingDino
```bash
git clone https://github.com/longzw1997/Open-GroundingDino.git
cd Open-GroundingDino
pip install -r requirements.txt
cd models/GroundingDINO/ops && python setup.py build install && cd ../../..
```

### 2. 下載預訓練權重
```bash
mkdir -p weights
wget -q https://github.com/IDEA-Research/GroundingDINO/releases/download/v0.1.0-alpha/groundingdino_swint_ogc.pth \\
     -O {pretrain_checkpoint}
```

### 3. 下載 BERT tokenizer
```bash
# 方法一：HuggingFace Hub
python -c "from transformers import BertTokenizer; BertTokenizer.from_pretrained('bert-base-uncased', cache_dir='bert_weights')"

# 方法二：手動下載後在設定中指定路徑
```

## 執行訓練

```bash
bash {os.path.abspath(train_script_path)}
```

## 訓練資料統計
- 圖片目錄：{image_dir}
- 訓練集：{train_jsonl}
- 驗證集：{val_jsonl}
- 類別數量：{num_classes}
- GPU 數量：{gpu_count}
- Batch Size：{batch_size}
- Epochs：{epochs}

## 訓練完成後

訓練完成的權重位於：{os.path.join(output_dir, 'checkpoints')}

使用 fine-tuned 模型進行自動標注：
```bash
python scripts/02_zero_shot_annotate.py \\
  --image_dir /path/to/new/images \\
  --output_dir /path/to/output \\
  --config config/config.yaml \\
  --mode local \\
  --local_config {config_path} \\
  --local_checkpoint {os.path.join(output_dir, 'checkpoints', 'checkpoint_best.pth')}
```

## 建議的 box_threshold 調整

Fine-tune 後模型對自身類別更有把握，建議適當提高閾值：
- 零樣本推薦：box_threshold=0.35
- Fine-tune 後推薦：box_threshold=0.40~0.50
"""

    instructions_path = os.path.join(output_dir, "INSTRUCTIONS.md")
    with open(instructions_path, "w", encoding="utf-8") as f:
        f.write(instructions)
    print(f"[說明] 執行說明：{instructions_path}")

    print(f"\n[完成] Fine-tune 設定已生成至：{output_dir}")
    print(f"[下一步] 請執行：bash {train_script_path}")


def main():
    parser = argparse.ArgumentParser(
        description="生成 Fine-tune 環境設定與訓練腳本"
    )
    parser.add_argument("--odvg_dir", "-d", required=True, help="odvg JSONL 所在目錄")
    parser.add_argument("--image_dir", "-i", required=True, help="圖片目錄")
    parser.add_argument("--output_dir", "-o", default="finetune_setup", help="輸出目錄")
    parser.add_argument(
        "--pretrain_checkpoint",
        default="weights/groundingdino_swint_ogc.pth",
        help="預訓練權重路徑",
    )
    parser.add_argument(
        "--open_gdino_dir",
        default="Open-GroundingDino",
        help="Open-GroundingDino repo 目錄",
    )
    parser.add_argument("--gpu_count", type=int, default=1, help="GPU 數量")
    parser.add_argument("--batch_size", type=int, default=2, help="Batch size")
    parser.add_argument("--epochs", type=int, default=12, help="訓練 epochs 數")

    args = parser.parse_args()

    generate_finetune_setup(
        odvg_dir=args.odvg_dir,
        image_dir=args.image_dir,
        output_dir=args.output_dir,
        pretrain_checkpoint=args.pretrain_checkpoint,
        open_gdino_dir=args.open_gdino_dir,
        gpu_count=args.gpu_count,
        batch_size=args.batch_size,
        epochs=args.epochs,
    )


if __name__ == "__main__":
    main()
