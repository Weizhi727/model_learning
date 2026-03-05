"""
腳本 02：零樣本自動標注

功能：
  - 讀取圖片目錄，對每張圖片執行 GroundingDINO 推論
  - 輸出與原始 LabelMe 格式相容的 JSON 標注
  - 支援批次處理、斷點續跑（skip_existing）
  - 支援 NMS 後處理去除重複框
  - 可選：輸出帶有視覺化結果的圖片

使用方式：
  # 使用 HuggingFace 模型（不需本地安裝 GroundingDINO）
  python scripts/02_zero_shot_annotate.py \
    --image_dir /path/to/images \
    --output_dir /path/to/output \
    --config config/config.yaml

  # 使用本地模型
  python scripts/02_zero_shot_annotate.py \
    --image_dir /path/to/images \
    --output_dir /path/to/output \
    --config config/config.yaml \
    --mode local \
    --local_config GroundingDINO/groundingdino/config/GroundingDINO_SwinT_OGC.py \
    --local_checkpoint weights/groundingdino_swint_ogc.pth

  # 單張圖片快速測試
  python scripts/02_zero_shot_annotate.py \
    --image_dir /path/to/images \
    --output_dir /path/to/output \
    --config config/config.yaml \
    --limit 5
"""

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.gdino_inference import create_model
from src.converters import detection_result_to_labelme
from src.labelme_utils import save_labelme_json

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".JPG", ".JPEG", ".PNG"}


def get_image_size(image_path: str):
    """快速取得圖片尺寸（不載入完整圖片）。"""
    from PIL import Image
    with Image.open(image_path) as img:
        return img.size  # (width, height)


def visualize_result(image_path: str, detection_result, output_path: str) -> None:
    """在圖片上畫出偵測結果並儲存。"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import random

        img = Image.open(image_path).convert("RGB")
        draw = ImageDraw.Draw(img)

        # 為每個類別分配固定顏色
        color_map = {}
        rng = random.Random(42)

        for box, label, score in zip(
            detection_result.boxes_xyxy,
            detection_result.labels,
            detection_result.scores,
        ):
            if label not in color_map:
                color_map[label] = (
                    rng.randint(50, 220),
                    rng.randint(50, 220),
                    rng.randint(50, 220),
                )
            color = color_map[label]

            x1, y1, x2, y2 = [int(v) for v in box]
            draw.rectangle([x1, y1, x2, y2], outline=color, width=2)

            text = f"{label} {score:.2f}"
            draw.rectangle([x1, y1 - 18, x1 + len(text) * 7, y1], fill=color)
            draw.text((x1 + 2, y1 - 16), text, fill="white")

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        img.save(output_path)
    except ImportError:
        pass  # Pillow 未安裝時略過視覺化


def annotate_directory(
    image_dir: str,
    output_dir: str,
    categories: list,
    model,
    box_threshold: float = 0.35,
    text_threshold: float = 0.25,
    nms_threshold: float = 0.5,
    skip_existing: bool = True,
    limit: int = 0,
    visualize: bool = False,
    vis_dir: str = None,
) -> dict:
    """
    批次標注圖片目錄。

    Returns:
        統計資訊 dict
    """
    # 收集圖片
    image_paths = [
        str(p)
        for p in Path(image_dir).rglob("*")
        if p.suffix in IMAGE_EXTENSIONS
    ]
    image_paths.sort()

    if limit > 0:
        image_paths = image_paths[:limit]

    total = len(image_paths)
    print(f"[標注] 找到 {total} 張圖片")
    print(f"[標注] 偵測類別：{categories}")
    print(f"[標注] Box 閾值：{box_threshold}  Text 閾值：{text_threshold}")

    stats = {
        "total": total,
        "processed": 0,
        "skipped": 0,
        "total_detections": 0,
    }

    for i, image_path in enumerate(image_paths):
        # 計算輸出 JSON 路徑（保留子目錄結構）
        rel_path = os.path.relpath(image_path, image_dir)
        json_rel_path = str(Path(rel_path).with_suffix(".json"))
        json_output_path = os.path.join(output_dir, json_rel_path)

        if skip_existing and os.path.exists(json_output_path):
            stats["skipped"] += 1
            continue

        print(f"[{i+1}/{total}] {os.path.basename(image_path)}", end=" ... ")

        try:
            # 推論
            result = model.predict(
                image=image_path,
                categories=categories,
                box_threshold=box_threshold,
                text_threshold=text_threshold,
            )

            # NMS 後處理
            if nms_threshold < 1.0:
                result = result.apply_nms(iou_threshold=nms_threshold)

            n_det = len(result)
            print(f"{n_det} 個偵測結果")
            stats["total_detections"] += n_det

            # 轉換為 LabelMe JSON
            width, height = get_image_size(image_path)
            labelme_data = detection_result_to_labelme(
                detection_result=result,
                image_path=image_path,
                image_height=height,
                image_width=width,
            )

            # 儲存
            save_labelme_json(labelme_data, json_output_path)

            # 視覺化（可選）
            if visualize:
                vis_output_dir = vis_dir or os.path.join(output_dir, "_visualizations")
                vis_path = os.path.join(vis_output_dir, rel_path)
                visualize_result(image_path, result, vis_path)

        except Exception as e:
            print(f"[錯誤] 處理失敗：{e}")
            continue

        stats["processed"] += 1

    print(f"\n[完成] 處理 {stats['processed']} 張，跳過 {stats['skipped']} 張")
    print(f"[完成] 共產生 {stats['total_detections']} 個標注框")
    print(f"[完成] 輸出目錄：{output_dir}")

    return stats


def load_config(config_path: str) -> dict:
    """載入 YAML 設定檔。"""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(
        description="使用 GroundingDINO 進行零樣本自動標注"
    )
    parser.add_argument("--image_dir", "-i", required=True, help="圖片目錄")
    parser.add_argument("--output_dir", "-o", required=True, help="輸出目錄")
    parser.add_argument("--config", "-c", default="config/config.yaml", help="設定檔路徑")

    # 模型選項
    parser.add_argument(
        "--mode", choices=["auto", "hf", "local"], default="auto",
        help="模型載入模式：auto（自動）、hf（HuggingFace）、local（本地）",
    )
    parser.add_argument("--hf_model_id", default=None, help="HuggingFace 模型 ID")
    parser.add_argument("--local_config", default=None, help="本地 GroundingDINO 設定檔")
    parser.add_argument("--local_checkpoint", default=None, help="本地模型權重路徑")
    parser.add_argument("--device", default=None, help="推論裝置（cuda/cpu）")

    # 推論參數
    parser.add_argument("--box_threshold", type=float, default=None, help="BBox 信心閾值")
    parser.add_argument("--text_threshold", type=float, default=None, help="文字匹配閾值")
    parser.add_argument("--nms_threshold", type=float, default=0.5, help="NMS IoU 閾值")
    parser.add_argument("--categories", nargs="+", default=None, help="偵測類別（覆蓋設定檔）")

    # 執行選項
    parser.add_argument("--limit", type=int, default=0, help="最多處理幾張（0=全部）")
    parser.add_argument("--no_skip", action="store_true", help="重新處理已存在的標注")
    parser.add_argument("--visualize", action="store_true", help="輸出視覺化圖片")
    parser.add_argument("--vis_dir", default=None, help="視覺化輸出目錄")

    args = parser.parse_args()

    # 載入設定
    config = {}
    if os.path.exists(args.config):
        config = load_config(args.config)
        print(f"[設定] 載入設定檔：{args.config}")
    else:
        print(f"[警告] 設定檔不存在：{args.config}，使用預設值")

    model_cfg = config.get("model", {})
    inference_cfg = config.get("inference", {})

    # 合併參數（命令列優先）
    categories = args.categories or config.get("categories", [])
    if not categories:
        print("[錯誤] 請提供偵測類別（--categories 或在 config.yaml 中設定）")
        sys.exit(1)

    box_threshold = args.box_threshold or inference_cfg.get("box_threshold", 0.35)
    text_threshold = args.text_threshold or inference_cfg.get("text_threshold", 0.25)
    hf_model_id = args.hf_model_id or model_cfg.get("hf_model_id", "IDEA-Research/grounding-dino-tiny")
    local_config = args.local_config or model_cfg.get("local_config")
    local_checkpoint = args.local_checkpoint or model_cfg.get("local_checkpoint")

    # 建立模型
    print(f"[初始化] 建立 GroundingDINO 模型（mode={args.mode}）...")
    model = create_model(
        mode=args.mode,
        hf_model_id=hf_model_id,
        local_config=local_config,
        local_checkpoint=local_checkpoint,
        device=args.device,
        box_threshold=box_threshold,
        text_threshold=text_threshold,
    )

    # 執行標注
    annotate_directory(
        image_dir=args.image_dir,
        output_dir=args.output_dir,
        categories=categories,
        model=model,
        box_threshold=box_threshold,
        text_threshold=text_threshold,
        nms_threshold=args.nms_threshold,
        skip_existing=not args.no_skip,
        limit=args.limit,
        visualize=args.visualize,
        vis_dir=args.vis_dir,
    )


if __name__ == "__main__":
    main()
