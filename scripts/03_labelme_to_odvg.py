"""
腳本 03：LabelMe JSON → odvg JSONL 格式轉換

將現有的 LabelMe 標注轉換為 Open-GroundingDino 訓練所需的 odvg 格式。

使用方式：
  # 基本轉換（OD 模式）
  python scripts/03_labelme_to_odvg.py \
    --input_dir /path/to/labelme/jsons \
    --output_dir /path/to/odvg/output \
    --image_dir /path/to/images

  # 指定類別映射（不自動掃描）
  python scripts/03_labelme_to_odvg.py \
    --input_dir /path/to/labelme/jsons \
    --output_dir /path/to/odvg/output \
    --categories screw bolt glove helmet

  # VG 模式（視覺定位）
  python scripts/03_labelme_to_odvg.py \
    --input_dir /path/to/labelme/jsons \
    --output_dir /path/to/odvg/output \
    --mode vg

  # 自動分割訓練/驗證集（8:2）
  python scripts/03_labelme_to_odvg.py \
    --input_dir /path/to/labelme/jsons \
    --output_dir /path/to/odvg/output \
    --split --train_ratio 0.8
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.converters import (
    build_label_to_id,
    labelme_dir_to_odvg,
    split_odvg_file,
)


def main():
    parser = argparse.ArgumentParser(
        description="將 LabelMe JSON 轉換為 odvg JSONL 格式（供 fine-tune 使用）"
    )
    parser.add_argument("--input_dir", "-i", required=True, help="LabelMe JSON 目錄")
    parser.add_argument("--output_dir", "-o", required=True, help="輸出目錄")
    parser.add_argument("--image_dir", default=None, help="圖片目錄（若與 JSON 不同）")
    parser.add_argument(
        "--mode", choices=["od", "vg"], default="od",
        help="轉換模式：od（物件偵測）或 vg（視覺定位）"
    )
    parser.add_argument(
        "--categories", nargs="+", default=None,
        help="類別列表（不指定則自動從 JSON 掃描）"
    )
    parser.add_argument(
        "--image_path_prefix", default="",
        help="odvg 中圖片路徑的前綴（相對於訓練根目錄）"
    )
    parser.add_argument(
        "--split", action="store_true",
        help="是否自動分割訓練/驗證集"
    )
    parser.add_argument(
        "--train_ratio", type=float, default=0.8,
        help="訓練集比例（--split 啟用時有效）"
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="隨機分割種子"
    )
    parser.add_argument(
        "--no_recursive", action="store_true",
        help="不遞迴搜尋子目錄"
    )

    args = parser.parse_args()

    if not os.path.isdir(args.input_dir):
        print(f"[錯誤] 目錄不存在：{args.input_dir}")
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)
    recursive = not args.no_recursive

    # 建立類別映射
    if args.categories:
        label_to_id = {cat: idx for idx, cat in enumerate(args.categories)}
        print(f"[類別] 使用指定類別：{label_to_id}")
    else:
        print("[類別] 自動掃描類別...")
        label_to_id = build_label_to_id(args.input_dir, recursive=recursive, start_id=0)
        print(f"[類別] 掃描到 {len(label_to_id)} 個類別：{label_to_id}")

    if not label_to_id:
        print("[錯誤] 未找到任何類別，請確認資料目錄是否正確")
        sys.exit(1)

    # 儲存類別映射供後續使用
    label_map_path = os.path.join(args.output_dir, "label_map.json")
    with open(label_map_path, "w", encoding="utf-8") as f:
        json.dump(label_to_id, f, ensure_ascii=False, indent=2)
    print(f"[類別] 類別映射已儲存：{label_map_path}")

    # 執行轉換
    output_jsonl_path = os.path.join(args.output_dir, f"dataset_{args.mode}.jsonl")

    stats = labelme_dir_to_odvg(
        labelme_dir=args.input_dir,
        output_jsonl_path=output_jsonl_path,
        label_to_id=label_to_id,
        mode=args.mode,
        image_path_prefix=args.image_path_prefix,
        recursive=recursive,
    )

    # 分割訓練/驗證集
    if args.split:
        train_path, val_path = split_odvg_file(
            odvg_path=output_jsonl_path,
            output_dir=args.output_dir,
            train_ratio=args.train_ratio,
            seed=args.seed,
        )

        # 生成 Open-GroundingDino 的資料集設定 JSON
        dataset_config = [
            {
                "root": args.image_dir or args.input_dir,
                "anno": train_path,
                "label_map": label_map_path,
                "dataset_mode": args.mode,
            }
        ]
        dataset_cfg_path = os.path.join(args.output_dir, "datasets_config.json")
        with open(dataset_cfg_path, "w", encoding="utf-8") as f:
            json.dump(dataset_config, f, ensure_ascii=False, indent=2)
        print(f"[設定] Open-GroundingDino 資料集設定已儲存：{dataset_cfg_path}")

    print("\n[完成] 轉換結果摘要：")
    print(f"  輸入目錄：{args.input_dir}")
    print(f"  輸出 JSONL：{output_jsonl_path}")
    print(f"  類別數量：{len(label_to_id)}")
    print(f"  轉換成功：{stats['converted']} / {stats['total']}")

    print("\n[下一步] 使用 Open-GroundingDino 進行 fine-tune：")
    print("  python scripts/04_finetune_setup.py \\")
    print(f"    --odvg_dir {args.output_dir} \\")
    print(f"    --image_dir {args.image_dir or args.input_dir}")


if __name__ == "__main__":
    main()
