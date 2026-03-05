"""
腳本 01：探索現有 LabelMe 標注資料集

功能：
  - 統計各工站的圖片數量與標注數量
  - 分析類別分布（哪些類別最多/最少）
  - 檢查資料品質問題（找不到對應圖片、空標注等）
  - 輸出類別列表供後續 config 使用

使用方式：
  python scripts/01_explore_dataset.py --data_dir /path/to/labelme/jsons
  python scripts/01_explore_dataset.py --data_dir /path/to/labelme/jsons --output stats.json
"""

import argparse
import json
import os
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.labelme_utils import (
    load_all_labelme_jsons,
    get_dataset_stats,
    get_image_path_from_json,
    points_to_xywh,
)


def explore_dataset(data_dir: str, verbose: bool = True) -> dict:
    """分析資料集並回傳統計資訊。"""

    print(f"\n[探索] 掃描目錄：{data_dir}")
    labelme_list = load_all_labelme_jsons(data_dir, recursive=True)

    if not labelme_list:
        print("[警告] 未找到任何 LabelMe JSON 檔案！")
        return {}

    print(f"[探索] 找到 {len(labelme_list)} 個 JSON 檔案")

    # --- 基本統計 ---
    stats = get_dataset_stats(labelme_list)

    # --- 圖片存在性檢查 ---
    missing_images = []
    for json_path, labelme_data in labelme_list:
        img_path = get_image_path_from_json(json_path, labelme_data)
        if img_path is None:
            missing_images.append({
                "json": json_path,
                "expected_image": labelme_data.get("imagePath", ""),
            })

    # --- 空標注檢查 ---
    empty_annotations = [
        json_path
        for json_path, data in labelme_list
        if len(data.get("shapes", [])) == 0
    ]

    # --- BBox 大小分析 ---
    bbox_areas = []
    for _, data in labelme_list:
        h = data.get("imageHeight", 1)
        w = data.get("imageWidth", 1)
        for shape in data.get("shapes", []):
            if shape.get("shape_type") == "rectangle":
                _, _, bw, bh = points_to_xywh(shape["points"])
                # 相對面積（佔圖片比例）
                rel_area = (bw * bh) / (w * h) if w * h > 0 else 0
                bbox_areas.append(rel_area)

    import numpy as np
    bbox_stats = {}
    if bbox_areas:
        bbox_stats = {
            "count": len(bbox_areas),
            "mean_relative_area": float(np.mean(bbox_areas)),
            "median_relative_area": float(np.median(bbox_areas)),
            "min_relative_area": float(np.min(bbox_areas)),
            "max_relative_area": float(np.max(bbox_areas)),
            "small_objects_pct": float(np.mean(np.array(bbox_areas) < 0.01)),  # < 1% 圖片面積
        }

    # --- 工站分析（依子目錄分組）---
    station_stats = defaultdict(lambda: {"images": 0, "annotations": 0, "labels": set()})
    for json_path, data in labelme_list:
        # 取相對路徑的第一層子目錄作為工站名稱
        rel_path = os.path.relpath(json_path, data_dir)
        parts = Path(rel_path).parts
        station = parts[0] if len(parts) > 1 else "root"
        station_stats[station]["images"] += 1
        for shape in data.get("shapes", []):
            station_stats[station]["annotations"] += 1
            station_stats[station]["labels"].add(shape.get("label", ""))

    station_summary = {
        name: {
            "images": s["images"],
            "annotations": s["annotations"],
            "unique_labels": sorted(s["labels"]),
        }
        for name, s in station_stats.items()
    }

    # 組合完整報告
    report = {
        "data_dir": str(data_dir),
        "summary": stats,
        "data_quality": {
            "missing_image_count": len(missing_images),
            "missing_images": missing_images[:10],  # 最多顯示 10 筆
            "empty_annotation_count": len(empty_annotations),
            "empty_annotation_files": [
                os.path.relpath(p, data_dir) for p in empty_annotations[:10]
            ],
        },
        "bbox_stats": bbox_stats,
        "station_breakdown": station_summary,
        "recommended_categories": list(stats["label_counts"].keys()),
    }

    if verbose:
        _print_report(report)

    return report


def _print_report(report: dict) -> None:
    """格式化輸出統計報告。"""
    summary = report["summary"]
    quality = report["data_quality"]
    bbox = report.get("bbox_stats", {})

    print("\n" + "=" * 60)
    print("資料集探索報告")
    print("=" * 60)
    print(f"目錄：{report['data_dir']}")
    print(f"總圖片數：{summary['total_images']}")
    print(f"總標注數：{summary['total_annotations']}")
    print(f"平均每圖標注數：{summary['avg_annotations_per_image']:.2f}")
    print(f"標注形狀類型：{summary['shape_types']}")

    print("\n--- 類別分布 ---")
    for label, count in summary["label_counts"].items():
        pct = count / summary["total_annotations"] * 100 if summary["total_annotations"] > 0 else 0
        bar = "█" * int(pct / 2)
        print(f"  {label:<25} {count:>6} ({pct:>5.1f}%)  {bar}")

    if bbox:
        print("\n--- BBox 大小統計 ---")
        print(f"  平均相對面積：{bbox.get('mean_relative_area', 0):.4f}")
        print(f"  中位相對面積：{bbox.get('median_relative_area', 0):.4f}")
        print(f"  小物件比例（<1% 圖片面積）：{bbox.get('small_objects_pct', 0):.2%}")

    print("\n--- 資料品質檢查 ---")
    print(f"  缺少對應圖片：{quality['missing_image_count']} 筆")
    print(f"  空標注 JSON：{quality['empty_annotation_count']} 筆")

    if quality["missing_images"]:
        print("  缺少圖片的 JSON 範例：")
        for item in quality["missing_images"][:5]:
            print(f"    {item['json']}")

    stations = report.get("station_breakdown", {})
    if len(stations) > 1:
        print("\n--- 工站分布 ---")
        for station, info in sorted(stations.items()):
            print(
                f"  {station:<30} "
                f"{info['images']:>4} 圖  "
                f"{info['annotations']:>6} 標注  "
                f"類別: {', '.join(info['unique_labels'][:5])}"
                + ("..." if len(info['unique_labels']) > 5 else "")
            )

    print("\n--- 建議的 config.yaml categories ---")
    cats = report.get("recommended_categories", [])
    print("  categories:")
    for cat in cats:
        print(f"    - \"{cat}\"")

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="探索 LabelMe 標注資料集"
    )
    parser.add_argument(
        "--data_dir", "-d",
        required=True,
        help="LabelMe JSON 檔案所在目錄",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="統計結果輸出路徑（JSON 格式），可選",
    )
    args = parser.parse_args()

    if not os.path.isdir(args.data_dir):
        print(f"[錯誤] 目錄不存在：{args.data_dir}")
        sys.exit(1)

    report = explore_dataset(args.data_dir)

    if args.output and report:
        # 將 set 轉為 list 以便 JSON 序列化
        import copy
        report_copy = copy.deepcopy(report)
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report_copy, f, ensure_ascii=False, indent=2)
        print(f"\n[完成] 統計結果已儲存：{args.output}")


if __name__ == "__main__":
    main()
