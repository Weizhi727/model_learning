"""
LabelMe JSON 格式讀寫與操作工具

LabelMe JSON 格式範例：
{
  "version": "5.2.1",
  "flags": {},
  "shapes": [
    {
      "label": "screw",
      "points": [[x1, y1], [x2, y2]],  # rectangle: 兩個對角點
      "group_id": null,
      "shape_type": "rectangle",        # 或 "polygon"
      "flags": {}
    }
  ],
  "imagePath": "image.jpg",
  "imageData": null,                    # base64 編碼圖片（可為 null）
  "imageHeight": 480,
  "imageWidth": 640
}
"""

import json
import base64
import os
from pathlib import Path
from typing import Optional
import numpy as np


# ---------------------------------------------------------------------------
# 資料結構定義（dict-based，方便序列化）
# ---------------------------------------------------------------------------

def make_shape(
    label: str,
    points: list,
    shape_type: str = "rectangle",
    group_id: Optional[int] = None,
    flags: Optional[dict] = None,
    confidence: Optional[float] = None,
) -> dict:
    """建立一個 LabelMe shape 物件。

    Args:
        label: 類別名稱
        points: 座標點列表
                - rectangle: [[x1,y1],[x2,y2]]（左上、右下）
                - polygon:   [[x1,y1],[x2,y2],...]
        shape_type: "rectangle" 或 "polygon"
        group_id: 群組 ID（可選）
        flags: 標記字典（可選）
        confidence: 模型信心分數，儲存在 description 欄位（可選）
    """
    shape = {
        "label": label,
        "points": points,
        "group_id": group_id,
        "shape_type": shape_type,
        "flags": flags or {},
    }
    if confidence is not None:
        shape["description"] = f"confidence:{confidence:.4f}"
    return shape


def make_labelme_json(
    image_path: str,
    shapes: list,
    image_height: int,
    image_width: int,
    image_data: Optional[str] = None,
    version: str = "5.2.1",
) -> dict:
    """建立完整的 LabelMe JSON 物件。"""
    return {
        "version": version,
        "flags": {},
        "shapes": shapes,
        "imagePath": os.path.basename(image_path),
        "imageData": image_data,
        "imageHeight": image_height,
        "imageWidth": image_width,
    }


# ---------------------------------------------------------------------------
# 讀取
# ---------------------------------------------------------------------------

def load_labelme_json(json_path: str) -> dict:
    """讀取 LabelMe JSON 檔案。"""
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_all_labelme_jsons(directory: str, recursive: bool = True) -> list:
    """遞迴讀取目錄下所有 LabelMe JSON 檔案。

    Returns:
        list of (json_path, labelme_dict)
    """
    pattern = "**/*.json" if recursive else "*.json"
    results = []
    for json_path in Path(directory).glob(pattern):
        try:
            data = load_labelme_json(str(json_path))
            # 簡單驗證是否為 LabelMe 格式
            if "shapes" in data and "imagePath" in data:
                results.append((str(json_path), data))
        except (json.JSONDecodeError, KeyError):
            pass
    return results


# ---------------------------------------------------------------------------
# 寫入
# ---------------------------------------------------------------------------

def save_labelme_json(data: dict, output_path: str, indent: int = 2) -> None:
    """儲存 LabelMe JSON 檔案。"""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)


# ---------------------------------------------------------------------------
# BBox 格式轉換
# ---------------------------------------------------------------------------

def points_to_xyxy(points: list) -> tuple:
    """LabelMe rectangle points → (x1, y1, x2, y2)。"""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def xyxy_to_points(x1: float, y1: float, x2: float, y2: float) -> list:
    """(x1, y1, x2, y2) → LabelMe rectangle points。"""
    return [[x1, y1], [x2, y2]]


def points_to_xywh(points: list) -> tuple:
    """LabelMe rectangle points → (x, y, w, h)（COCO 格式）。"""
    x1, y1, x2, y2 = points_to_xyxy(points)
    return x1, y1, x2 - x1, y2 - y1


def xywh_to_points(x: float, y: float, w: float, h: float) -> list:
    """(x, y, w, h) → LabelMe rectangle points。"""
    return xyxy_to_points(x, y, x + w, y + h)


def normalize_bbox(
    bbox_xyxy: tuple, image_width: int, image_height: int
) -> tuple:
    """將絕對座標 bbox 轉為 [0,1] 正規化座標（GroundingDINO 輸出格式）。"""
    x1, y1, x2, y2 = bbox_xyxy
    return (
        x1 / image_width,
        y1 / image_height,
        x2 / image_width,
        y2 / image_height,
    )


def denormalize_bbox(
    bbox_norm: tuple, image_width: int, image_height: int
) -> tuple:
    """將正規化座標轉為絕對像素座標。"""
    cx, cy, w, h = bbox_norm  # GroundingDINO 輸出為 cx,cy,w,h（正規化）
    x1 = (cx - w / 2) * image_width
    y1 = (cy - h / 2) * image_height
    x2 = (cx + w / 2) * image_width
    y2 = (cy + h / 2) * image_height
    # 夾到合法範圍
    x1 = max(0.0, x1)
    y1 = max(0.0, y1)
    x2 = min(float(image_width), x2)
    y2 = min(float(image_height), y2)
    return x1, y1, x2, y2


# ---------------------------------------------------------------------------
# 統計分析
# ---------------------------------------------------------------------------

def get_dataset_stats(labelme_list: list) -> dict:
    """統計資料集的類別分布、BBox 大小等資訊。

    Args:
        labelme_list: list of (json_path, labelme_dict)

    Returns:
        dict with keys: total_images, total_annotations, label_counts,
                        avg_annotations_per_image, shape_types
    """
    label_counts = {}
    shape_types = {}
    total_annotations = 0

    for _, data in labelme_list:
        for shape in data.get("shapes", []):
            label = shape.get("label", "unknown")
            stype = shape.get("shape_type", "unknown")
            label_counts[label] = label_counts.get(label, 0) + 1
            shape_types[stype] = shape_types.get(stype, 0) + 1
            total_annotations += 1

    return {
        "total_images": len(labelme_list),
        "total_annotations": total_annotations,
        "label_counts": dict(sorted(label_counts.items(), key=lambda x: -x[1])),
        "avg_annotations_per_image": (
            total_annotations / len(labelme_list) if labelme_list else 0
        ),
        "shape_types": shape_types,
    }


def get_image_path_from_json(json_path: str, labelme_data: dict) -> Optional[str]:
    """根據 JSON 路徑推斷對應圖片的完整路徑。

    搜尋順序：
    1. 與 JSON 同目錄
    2. 常見副檔名嘗試（.jpg, .jpeg, .png, .bmp）
    """
    json_dir = os.path.dirname(json_path)
    image_filename = labelme_data.get("imagePath", "")
    image_stem = Path(image_filename).stem

    # 嘗試原始路徑
    candidate = os.path.join(json_dir, image_filename)
    if os.path.exists(candidate):
        return candidate

    # 嘗試不同副檔名
    for ext in [".jpg", ".jpeg", ".png", ".bmp", ".JPG", ".JPEG", ".PNG"]:
        candidate = os.path.join(json_dir, image_stem + ext)
        if os.path.exists(candidate):
            return candidate

    return None


def encode_image_to_base64(image_path: str) -> str:
    """將圖片編碼為 base64 字串（供嵌入 LabelMe JSON 用）。"""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")
