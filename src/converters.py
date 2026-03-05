"""
格式轉換模組

支援以下格式互轉：
- LabelMe JSON  ↔  COCO JSON
- LabelMe JSON  →  odvg JSONL  （供 Open-GroundingDino fine-tune 使用）
- LabelMe JSON  ←  GroundingDINO 推論結果

odvg 格式說明（每行一筆 JSON）：
  物件偵測 (OD)：
    {"filename": "img.jpg", "height": 480, "width": 640,
     "detection": {"instances": [{"bbox": [x,y,w,h], "label": 0, "category": "dog"}],
                   "categories": [{"id": 0, "name": "dog"}]}}

  視覺定位 (VG)：
    {"filename": "img.jpg", "height": 480, "width": 640,
     "grounding": {"caption": "a dog on the grass",
                   "regions": [{"bbox": [x,y,w,h], "phrase": "a dog",
                                "tokens_positive": [[2, 7]]}]}}
"""

import json
import os
from pathlib import Path
from typing import Optional

from src.labelme_utils import (
    load_labelme_json,
    load_all_labelme_jsons,
    points_to_xyxy,
    points_to_xywh,
    get_image_path_from_json,
)


# ---------------------------------------------------------------------------
# LabelMe → odvg JSONL（供 Open-GroundingDino fine-tune）
# ---------------------------------------------------------------------------

def labelme_to_odvg_entry(
    labelme_data: dict,
    image_filename: str,
    label_to_id: dict,
    mode: str = "od",
    caption_template: str = "{categories}",
) -> Optional[dict]:
    """
    將單筆 LabelMe JSON 轉為 odvg 格式。

    Args:
        labelme_data: LabelMe JSON dict
        image_filename: 圖片相對路徑（相對於訓練資料根目錄）
        label_to_id: 類別名稱到 ID 的映射，例如 {"screw": 0, "bolt": 1}
        mode: "od"（物件偵測）或 "vg"（視覺定位）
        caption_template: VG 模式下描述文字的模板（用 {categories} 填入類別）

    Returns:
        odvg 格式的 dict，若無有效 shape 則回傳 None
    """
    shapes = labelme_data.get("shapes", [])
    image_height = labelme_data.get("imageHeight", 0)
    image_width = labelme_data.get("imageWidth", 0)

    # 篩選矩形標注
    valid_shapes = [
        s for s in shapes
        if s.get("shape_type") in ("rectangle", "polygon")
        and s.get("label") in label_to_id
    ]

    if not valid_shapes:
        return None

    entry = {
        "filename": image_filename,
        "height": image_height,
        "width": image_width,
    }

    if mode == "od":
        categories = [
            {"id": id_, "name": name}
            for name, id_ in sorted(label_to_id.items(), key=lambda x: x[1])
        ]
        instances = []
        for shape in valid_shapes:
            x, y, w, h = points_to_xywh(shape["points"])
            instances.append({
                "bbox": [x, y, w, h],
                "label": label_to_id[shape["label"]],
                "category": shape["label"],
            })
        entry["detection"] = {
            "instances": instances,
            "categories": categories,
        }

    elif mode == "vg":
        # 為 VG 模式生成 caption（描述圖片中出現了哪些物件）
        present_labels = list(dict.fromkeys(s["label"] for s in valid_shapes))
        caption = caption_template.format(categories=", ".join(present_labels))

        regions = []
        for shape in valid_shapes:
            x, y, w, h = points_to_xywh(shape["points"])
            phrase = shape["label"]
            # 在 caption 中找到 phrase 的位置
            start = caption.find(phrase)
            tokens_positive = [[start, start + len(phrase)]] if start >= 0 else []
            regions.append({
                "bbox": [x, y, w, h],
                "phrase": phrase,
                "tokens_positive": tokens_positive,
            })
        entry["grounding"] = {
            "caption": caption,
            "regions": regions,
        }

    return entry


def labelme_dir_to_odvg(
    labelme_dir: str,
    output_jsonl_path: str,
    label_to_id: dict,
    image_dir: Optional[str] = None,
    mode: str = "od",
    image_path_prefix: str = "",
    recursive: bool = True,
) -> dict:
    """
    將整個 LabelMe 標注目錄轉換為 odvg JSONL 格式。

    Args:
        labelme_dir: 包含 LabelMe JSON 的目錄
        output_jsonl_path: 輸出 JSONL 檔案路徑
        label_to_id: 類別映射，例如 {"screw": 0, "bolt": 1}
        image_dir: 圖片目錄（若與 JSON 不在同一目錄）
        mode: "od" 或 "vg"
        image_path_prefix: 圖片路徑前綴（相對於訓練根目錄）
        recursive: 是否遞迴搜尋子目錄

    Returns:
        轉換統計資訊 dict
    """
    labelme_list = load_all_labelme_jsons(labelme_dir, recursive=recursive)

    os.makedirs(os.path.dirname(output_jsonl_path) or ".", exist_ok=True)

    stats = {"total": len(labelme_list), "converted": 0, "skipped": 0}

    with open(output_jsonl_path, "w", encoding="utf-8") as f:
        for json_path, labelme_data in labelme_list:
            image_filename = labelme_data.get("imagePath", "")
            if image_path_prefix:
                image_filename = os.path.join(
                    image_path_prefix, os.path.basename(image_filename)
                )

            entry = labelme_to_odvg_entry(
                labelme_data, image_filename, label_to_id, mode=mode
            )

            if entry is None:
                stats["skipped"] += 1
                continue

            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            stats["converted"] += 1

    print(
        f"[odvg 轉換] 完成：{stats['converted']}/{stats['total']} "
        f"（跳過 {stats['skipped']} 筆）"
    )
    print(f"[odvg 轉換] 輸出：{output_jsonl_path}")
    return stats


# ---------------------------------------------------------------------------
# LabelMe → COCO JSON
# ---------------------------------------------------------------------------

def labelme_dir_to_coco(
    labelme_dir: str,
    output_json_path: str,
    label_to_id: dict,
    recursive: bool = True,
    split_name: str = "train",
) -> dict:
    """
    將 LabelMe 標注目錄轉換為 COCO 格式 JSON。

    COCO 格式可用於：
    - 標準目標偵測評估工具（pycocotools）
    - 其他支援 COCO 格式的訓練框架

    Args:
        labelme_dir: LabelMe JSON 目錄
        output_json_path: 輸出 COCO JSON 路徑
        label_to_id: 類別映射，從 1 開始（COCO 慣例）
        recursive: 是否遞迴搜尋
        split_name: 資料集分割名稱（"train", "val", "test"）

    Returns:
        COCO dict
    """
    labelme_list = load_all_labelme_jsons(labelme_dir, recursive=recursive)

    categories = [
        {"id": id_, "name": name, "supercategory": "industrial"}
        for name, id_ in sorted(label_to_id.items(), key=lambda x: x[1])
    ]

    images = []
    annotations = []
    ann_id = 1

    for img_id, (json_path, labelme_data) in enumerate(labelme_list, start=1):
        image_filename = labelme_data.get("imagePath", "")
        image_height = labelme_data.get("imageHeight", 0)
        image_width = labelme_data.get("imageWidth", 0)

        images.append({
            "id": img_id,
            "file_name": os.path.basename(image_filename),
            "height": image_height,
            "width": image_width,
        })

        for shape in labelme_data.get("shapes", []):
            label = shape.get("label", "")
            if label not in label_to_id:
                continue

            x, y, w, h = points_to_xywh(shape["points"])
            area = w * h

            annotations.append({
                "id": ann_id,
                "image_id": img_id,
                "category_id": label_to_id[label],
                "bbox": [x, y, w, h],
                "area": area,
                "iscrowd": 0,
                "segmentation": [],
            })
            ann_id += 1

    coco_dict = {
        "info": {"description": f"Industrial dataset - {split_name}"},
        "licenses": [],
        "categories": categories,
        "images": images,
        "annotations": annotations,
    }

    os.makedirs(os.path.dirname(output_json_path) or ".", exist_ok=True)
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(coco_dict, f, ensure_ascii=False, indent=2)

    print(
        f"[COCO 轉換] 完成：{len(images)} 圖片，{len(annotations)} 標注 → {output_json_path}"
    )
    return coco_dict


# ---------------------------------------------------------------------------
# 從 LabelMe 目錄自動建立類別映射
# ---------------------------------------------------------------------------

def build_label_to_id(
    labelme_dir: str,
    recursive: bool = True,
    start_id: int = 0,
) -> dict:
    """
    掃描 LabelMe JSON 目錄，自動建立類別名稱到 ID 的映射。

    Args:
        labelme_dir: LabelMe JSON 目錄
        recursive: 是否遞迴搜尋
        start_id: 起始 ID（COCO 格式通常從 1 開始，odvg 從 0 開始）

    Returns:
        {"label_name": id, ...}，依出現頻率降序排列
    """
    from src.labelme_utils import get_dataset_stats

    labelme_list = load_all_labelme_jsons(labelme_dir, recursive=recursive)
    stats = get_dataset_stats(labelme_list)
    label_counts = stats["label_counts"]

    return {
        label: idx + start_id
        for idx, label in enumerate(label_counts.keys())
    }


# ---------------------------------------------------------------------------
# GroundingDINO 推論結果 → LabelMe JSON
# ---------------------------------------------------------------------------

def detection_result_to_labelme(
    detection_result,
    image_path: str,
    image_height: int,
    image_width: int,
    include_image_data: bool = False,
) -> dict:
    """
    將 DetectionResult 轉換為完整的 LabelMe JSON dict。

    Args:
        detection_result: src.gdino_inference.DetectionResult
        image_path: 圖片路徑（用於 imagePath 欄位）
        image_height: 圖片高度
        image_width: 圖片寬度
        include_image_data: 是否將圖片 base64 嵌入 JSON（會使檔案變大）

    Returns:
        LabelMe JSON dict
    """
    from src.labelme_utils import make_labelme_json, encode_image_to_base64

    shapes = detection_result.to_labelme_shapes()

    image_data = None
    if include_image_data and os.path.exists(image_path):
        image_data = encode_image_to_base64(image_path)

    return make_labelme_json(
        image_path=image_path,
        shapes=shapes,
        image_height=image_height,
        image_width=image_width,
        image_data=image_data,
    )


# ---------------------------------------------------------------------------
# 訓練/驗證集分割工具
# ---------------------------------------------------------------------------

def split_odvg_file(
    odvg_path: str,
    output_dir: str,
    train_ratio: float = 0.8,
    seed: int = 42,
) -> tuple:
    """
    將 odvg JSONL 分割為訓練集和驗證集。

    Args:
        odvg_path: 原始 odvg JSONL 路徑
        output_dir: 輸出目錄
        train_ratio: 訓練集比例
        seed: 隨機種子

    Returns:
        (train_path, val_path)
    """
    import random

    with open(odvg_path, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]

    rng = random.Random(seed)
    rng.shuffle(lines)

    split_idx = int(len(lines) * train_ratio)
    train_lines = lines[:split_idx]
    val_lines = lines[split_idx:]

    os.makedirs(output_dir, exist_ok=True)
    stem = Path(odvg_path).stem

    train_path = os.path.join(output_dir, f"{stem}_train.jsonl")
    val_path = os.path.join(output_dir, f"{stem}_val.jsonl")

    with open(train_path, "w", encoding="utf-8") as f:
        f.write("\n".join(train_lines) + "\n")

    with open(val_path, "w", encoding="utf-8") as f:
        f.write("\n".join(val_lines) + "\n")

    print(f"[分割] 訓練集：{len(train_lines)} 筆 → {train_path}")
    print(f"[分割] 驗證集：{len(val_lines)} 筆 → {val_path}")

    return train_path, val_path
