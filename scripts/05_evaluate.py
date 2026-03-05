"""
腳本 05：評估自動標注品質

功能：
  - 比較自動標注（預測）與人工標注（Ground Truth）
  - 計算各類別 AP、整體 mAP、Precision、Recall、F1
  - 找出品質差的圖片（優先安排人工校正）
  - 輸出 HTML 視覺化報告（可選）

使用方式：
  # 對應目錄比較（pred 目錄與 gt 目錄結構需相同）
  python scripts/05_evaluate.py \
    --pred_dir /path/to/auto/annotations \
    --gt_dir /path/to/manual/annotations

  # 輸出低品質圖片列表（召回率 < 0.7 的圖片）
  python scripts/05_evaluate.py \
    --pred_dir /path/to/auto/annotations \
    --gt_dir /path/to/manual/annotations \
    --recall_threshold 0.7 \
    --output_low_quality low_quality.txt
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.evaluator import AnnotationEvaluator
from src.labelme_utils import load_labelme_json


def find_matching_pairs(pred_dir: str, gt_dir: str) -> list:
    """
    找到 pred_dir 和 gt_dir 中同名的 JSON 配對。

    Returns:
        list of (pred_path, gt_path)
    """
    pred_jsons = {
        os.path.relpath(str(p), pred_dir): str(p)
        for p in Path(pred_dir).rglob("*.json")
    }
    gt_jsons = {
        os.path.relpath(str(p), gt_dir): str(p)
        for p in Path(gt_dir).rglob("*.json")
    }

    common_keys = set(pred_jsons.keys()) & set(gt_jsons.keys())

    if not common_keys:
        print("[警告] 未找到同名的 JSON 配對！")
        print(f"  預測目錄中的 JSON 數量：{len(pred_jsons)}")
        print(f"  GT 目錄中的 JSON 數量：{len(gt_jsons)}")
        if pred_jsons:
            print(f"  預測目錄範例：{list(pred_jsons.keys())[:3]}")
        if gt_jsons:
            print(f"  GT 目錄範例：{list(gt_jsons.keys())[:3]}")
        return []

    print(f"[配對] 找到 {len(common_keys)} 對配對（pred 共 {len(pred_jsons)}，GT 共 {len(gt_jsons)}）")
    if len(pred_jsons) != len(gt_jsons):
        only_pred = len(pred_jsons) - len(common_keys)
        only_gt = len(gt_jsons) - len(common_keys)
        if only_pred:
            print(f"[警告] 有 {only_pred} 個 JSON 只在預測目錄中")
        if only_gt:
            print(f"[警告] 有 {only_gt} 個 JSON 只在 GT 目錄中（未偵測到任何目標）")

    return sorted([
        (pred_jsons[key], gt_jsons[key])
        for key in common_keys
    ])


def generate_html_report(results: dict, output_path: str, iou_threshold: float) -> None:
    """生成 HTML 格式的評估報告。"""
    overall = results["overall"]
    per_class = results["per_class"]
    per_image = results["per_image"]

    rows_class = ""
    for label, m in sorted(per_class.items(), key=lambda x: -x[1]["ap"]):
        rows_class += f"""
        <tr>
            <td>{label}</td>
            <td>{m['ap']:.3f}</td>
            <td>{m['precision']:.3f}</td>
            <td>{m['recall']:.3f}</td>
            <td>{m['f1']:.3f}</td>
            <td>{m['tp']}</td>
            <td>{m['fp']}</td>
            <td>{m['fn']}</td>
        </tr>"""

    rows_image = ""
    for img in sorted(per_image, key=lambda x: x["recall"]):
        color = "#ffcccc" if img["recall"] < 0.5 else "#fff3cd" if img["recall"] < 0.7 else "#d4edda"
        rows_image += f"""
        <tr style="background:{color}">
            <td>{img['image']}</td>
            <td>{img['n_pred']}</td>
            <td>{img['n_gt']}</td>
            <td>{img['tp']}</td>
            <td>{img['fp']}</td>
            <td>{img['fn']}</td>
            <td>{img['precision']:.3f}</td>
            <td>{img['recall']:.3f}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>自動標注品質評估報告</title>
<style>
  body {{ font-family: sans-serif; margin: 20px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
  th, td {{ border: 1px solid #ddd; padding: 8px; text-align: right; }}
  th {{ background: #4472c4; color: white; }}
  td:first-child {{ text-align: left; }}
  .metric {{ font-size: 1.5em; font-weight: bold; color: #2c3e50; }}
  .section {{ background: #f8f9fa; padding: 15px; margin: 15px 0; border-radius: 5px; }}
</style>
</head>
<body>
<h1>自動標注品質評估報告</h1>
<div class="section">
  <h2>整體指標（IoU@{iou_threshold}）</h2>
  <table style="width:auto">
    <tr><th>指標</th><th>數值</th></tr>
    <tr><td>評估圖片數</td><td class="metric">{overall['total_images']}</td></tr>
    <tr><td>mAP@{iou_threshold}</td><td class="metric">{overall['mAP']:.4f}</td></tr>
    <tr><td>整體精確率</td><td class="metric">{overall['precision']:.4f}</td></tr>
    <tr><td>整體召回率</td><td class="metric">{overall['recall']:.4f}</td></tr>
    <tr><td>整體 F1</td><td class="metric">{overall['f1']:.4f}</td></tr>
    <tr><td>預測標注總數</td><td>{overall['total_pred']}</td></tr>
    <tr><td>人工標注總數</td><td>{overall['total_gt']}</td></tr>
  </table>
</div>
<div class="section">
  <h2>各類別指標</h2>
  <table>
    <tr><th>類別</th><th>AP</th><th>Precision</th><th>Recall</th><th>F1</th><th>TP</th><th>FP</th><th>FN</th></tr>
    {rows_class}
  </table>
</div>
<div class="section">
  <h2>各圖片品質（依召回率升序，紅=差、黃=中、綠=好）</h2>
  <table>
    <tr><th>圖片</th><th>預測數</th><th>GT數</th><th>TP</th><th>FP</th><th>FN</th><th>Precision</th><th>Recall</th></tr>
    {rows_image}
  </table>
</div>
</body>
</html>"""

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[報告] HTML 報告已儲存：{output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="評估自動標注品質（與人工標注比對）"
    )
    parser.add_argument("--pred_dir", "-p", required=True, help="自動標注 JSON 目錄")
    parser.add_argument("--gt_dir", "-g", required=True, help="人工標注 JSON 目錄（Ground Truth）")
    parser.add_argument(
        "--iou_threshold", type=float, default=0.5,
        help="IoU 匹配閾值（預設 0.5）",
    )
    parser.add_argument(
        "--recall_threshold", type=float, default=0.7,
        help="低品質圖片的召回率閾值（低於此值列為待校正）",
    )
    parser.add_argument(
        "--output_json", default=None,
        help="將完整評估結果輸出為 JSON",
    )
    parser.add_argument(
        "--output_html", default=None,
        help="輸出 HTML 視覺化報告",
    )
    parser.add_argument(
        "--output_low_quality", default=None,
        help="輸出低品質圖片列表（待人工校正）",
    )

    args = parser.parse_args()

    # 找配對
    pairs = find_matching_pairs(args.pred_dir, args.gt_dir)
    if not pairs:
        sys.exit(1)

    # 建立評估器
    evaluator = AnnotationEvaluator(iou_threshold=args.iou_threshold)

    print(f"[評估] 載入 {len(pairs)} 對標注...")
    for pred_path, gt_path in pairs:
        evaluator.add_image_files(pred_path, gt_path)

    # 計算結果
    results = evaluator.compute()

    # 印出報告
    evaluator.print_report(results)

    # 輸出低品質圖片列表
    low_quality = evaluator.get_low_quality_images(
        results, recall_threshold=args.recall_threshold
    )

    if low_quality:
        print(f"\n[校正優先] 召回率 < {args.recall_threshold} 的圖片共 {len(low_quality)} 張：")
        for img_name, recall in low_quality[:20]:
            print(f"  recall={recall:.3f}  {img_name}")
        if len(low_quality) > 20:
            print(f"  ... 以及另外 {len(low_quality) - 20} 張")

        if args.output_low_quality:
            os.makedirs(
                os.path.dirname(args.output_low_quality) or ".", exist_ok=True
            )
            with open(args.output_low_quality, "w", encoding="utf-8") as f:
                for img_name, recall in low_quality:
                    f.write(f"{recall:.4f}\t{img_name}\n")
            print(f"[輸出] 低品質圖片列表：{args.output_low_quality}")
    else:
        print(f"\n[品質] 所有圖片召回率均 >= {args.recall_threshold}，品質良好！")

    # 輸出 JSON 結果
    if args.output_json:
        # 使結果可 JSON 序列化
        import copy
        serializable_results = copy.deepcopy(results)
        os.makedirs(
            os.path.dirname(args.output_json) or ".", exist_ok=True
        )
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(serializable_results, f, ensure_ascii=False, indent=2)
        print(f"[輸出] 評估結果 JSON：{args.output_json}")

    # 輸出 HTML 報告
    if args.output_html:
        generate_html_report(results, args.output_html, args.iou_threshold)


if __name__ == "__main__":
    main()
