"""
自動標注品質評估模組

計算自動標注與人工標注之間的差距：
- IoU（Intersection over Union）逐框比對
- 精確率（Precision）/ 召回率（Recall）/ F1
- 各類別 AP（Average Precision）
- 整體 mAP

使用場景：
  評估零樣本或 fine-tune 後的自動標注品質，
  決定哪些圖片需要人工校正的優先順序。
"""

from typing import Optional
import numpy as np


# ---------------------------------------------------------------------------
# 基礎 IoU 計算
# ---------------------------------------------------------------------------

def compute_iou(box1: list, box2: list) -> float:
    """
    計算兩個 BBox 的 IoU。

    Args:
        box1, box2: [x1, y1, x2, y2] 格式

    Returns:
        IoU 值 (0.0 ~ 1.0)
    """
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])

    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if intersection == 0.0:
        return 0.0

    area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    union = area1 + area2 - intersection

    return intersection / union if union > 0 else 0.0


def compute_iou_matrix(boxes1: list, boxes2: list) -> np.ndarray:
    """
    計算兩組 BBox 之間的 IoU 矩陣。

    Returns:
        numpy array of shape (len(boxes1), len(boxes2))
    """
    if not boxes1 or not boxes2:
        return np.zeros((len(boxes1), len(boxes2)))

    matrix = np.zeros((len(boxes1), len(boxes2)))
    for i, b1 in enumerate(boxes1):
        for j, b2 in enumerate(boxes2):
            matrix[i, j] = compute_iou(b1, b2)
    return matrix


# ---------------------------------------------------------------------------
# 單圖評估
# ---------------------------------------------------------------------------

def match_predictions(
    pred_boxes: list,
    pred_labels: list,
    pred_scores: list,
    gt_boxes: list,
    gt_labels: list,
    iou_threshold: float = 0.5,
) -> dict:
    """
    對單張圖片的預測結果與 Ground Truth 進行配對。

    使用貪婪匹配（依分數排序後逐一配對）。

    Returns:
        dict with keys:
          - tp: list of bool（各預測是否為 True Positive）
          - fp: list of bool（各預測是否為 False Positive）
          - matched_gt: list of int（配對到的 GT 索引，-1 表示未配對）
          - unmatched_gt: list of int（未被任何預測配對的 GT 索引）
    """
    n_pred = len(pred_boxes)
    n_gt = len(gt_boxes)

    tp = [False] * n_pred
    fp = [False] * n_pred
    matched_gt = [-1] * n_pred
    gt_matched = [False] * n_gt

    # 依分數降序排列預測
    sorted_indices = sorted(range(n_pred), key=lambda i: pred_scores[i], reverse=True)

    iou_matrix = compute_iou_matrix(pred_boxes, gt_boxes)

    for pred_idx in sorted_indices:
        pred_label = pred_labels[pred_idx]

        # 找到同類別且 IoU 最高的 GT
        best_iou = iou_threshold
        best_gt_idx = -1

        for gt_idx in range(n_gt):
            if gt_matched[gt_idx]:
                continue
            if gt_labels[gt_idx] != pred_label:
                continue
            iou = iou_matrix[pred_idx, gt_idx]
            if iou >= best_iou:
                best_iou = iou
                best_gt_idx = gt_idx

        if best_gt_idx >= 0:
            tp[pred_idx] = True
            matched_gt[pred_idx] = best_gt_idx
            gt_matched[best_gt_idx] = True
        else:
            fp[pred_idx] = True

    unmatched_gt = [i for i in range(n_gt) if not gt_matched[i]]

    return {
        "tp": tp,
        "fp": fp,
        "matched_gt": matched_gt,
        "unmatched_gt": unmatched_gt,
    }


# ---------------------------------------------------------------------------
# 資料集評估
# ---------------------------------------------------------------------------

class AnnotationEvaluator:
    """
    比較自動標注與人工標注的品質評估器。

    使用範例：
        evaluator = AnnotationEvaluator(iou_threshold=0.5)

        # 逐圖加入結果
        for pred_json, gt_json in zip(pred_files, gt_files):
            evaluator.add_image(pred_json, gt_json)

        # 計算並顯示統計
        results = evaluator.compute()
        evaluator.print_report(results)
    """

    def __init__(self, iou_threshold: float = 0.5):
        self.iou_threshold = iou_threshold
        self._records = []  # list of (pred_data, gt_data)

    def add_image_data(self, pred_labelme: dict, gt_labelme: dict) -> None:
        """加入一對預測/GT LabelMe JSON 資料。"""
        self._records.append((pred_labelme, gt_labelme))

    def add_image_files(self, pred_json_path: str, gt_json_path: str) -> None:
        """從檔案路徑載入並加入。"""
        from src.labelme_utils import load_labelme_json
        pred = load_labelme_json(pred_json_path)
        gt = load_labelme_json(gt_json_path)
        self.add_image_data(pred, gt)

    def _extract_boxes_labels_scores(self, labelme_data: dict):
        """從 LabelMe JSON 提取 boxes、labels、scores。"""
        from src.labelme_utils import points_to_xyxy

        boxes, labels, scores = [], [], []
        for shape in labelme_data.get("shapes", []):
            if shape.get("shape_type") not in ("rectangle", "polygon"):
                continue
            box = list(points_to_xyxy(shape["points"]))
            label = shape.get("label", "unknown")

            # 從 description 欄位讀取信心分數
            desc = shape.get("description", "")
            score = 1.0
            if desc.startswith("confidence:"):
                try:
                    score = float(desc.split(":")[1])
                except ValueError:
                    pass

            boxes.append(box)
            labels.append(label)
            scores.append(score)

        return boxes, labels, scores

    def compute(self) -> dict:
        """
        計算整體評估指標。

        Returns:
            dict with keys:
              - per_class: {label: {precision, recall, f1, ap, tp, fp, fn}}
              - overall: {precision, recall, f1, mAP, total_pred, total_gt}
              - per_image: list of per-image stats
        """
        from collections import defaultdict

        # 按類別收集所有 (score, tp/fp) 記錄
        class_records = defaultdict(lambda: {"scores": [], "tp": [], "n_gt": 0})
        total_pred = 0
        total_gt = 0
        per_image_stats = []

        for pred_data, gt_data in self._records:
            pred_boxes, pred_labels, pred_scores = self._extract_boxes_labels_scores(pred_data)
            gt_boxes, gt_labels, gt_scores = self._extract_boxes_labels_scores(gt_data)

            match_result = match_predictions(
                pred_boxes, pred_labels, pred_scores,
                gt_boxes, gt_labels,
                iou_threshold=self.iou_threshold,
            )

            total_pred += len(pred_boxes)
            total_gt += len(gt_boxes)

            # 按類別記錄
            gt_label_counts = defaultdict(int)
            for label in gt_labels:
                gt_label_counts[label] += 1

            for i, (pred_label, score, is_tp) in enumerate(
                zip(pred_labels, pred_scores, match_result["tp"])
            ):
                class_records[pred_label]["scores"].append(score)
                class_records[pred_label]["tp"].append(int(is_tp))

            for label, count in gt_label_counts.items():
                class_records[label]["n_gt"] += count

            # 單圖統計
            n_tp = sum(match_result["tp"])
            n_fp = sum(match_result["fp"])
            n_fn = len(match_result["unmatched_gt"])
            img_prec = n_tp / (n_tp + n_fp) if (n_tp + n_fp) > 0 else 0.0
            img_recall = n_tp / (n_tp + n_fn) if (n_tp + n_fn) > 0 else 0.0

            per_image_stats.append({
                "image": pred_data.get("imagePath", ""),
                "n_pred": len(pred_boxes),
                "n_gt": len(gt_boxes),
                "tp": n_tp,
                "fp": n_fp,
                "fn": n_fn,
                "precision": img_prec,
                "recall": img_recall,
            })

        # 計算各類別 AP
        per_class = {}
        all_aps = []

        for label, records in class_records.items():
            scores = np.array(records["scores"])
            tps = np.array(records["tp"])
            n_gt = records["n_gt"]

            if len(scores) == 0 or n_gt == 0:
                continue

            # 依分數降序排列
            sorted_idx = np.argsort(-scores)
            tps_sorted = tps[sorted_idx]
            fps_sorted = 1 - tps_sorted

            cum_tp = np.cumsum(tps_sorted)
            cum_fp = np.cumsum(fps_sorted)

            precision = cum_tp / (cum_tp + cum_fp)
            recall = cum_tp / n_gt

            ap = _compute_ap(recall, precision)
            all_aps.append(ap)

            final_tp = int(cum_tp[-1]) if len(cum_tp) > 0 else 0
            final_fp = int(cum_fp[-1]) if len(cum_fp) > 0 else 0
            final_fn = n_gt - final_tp

            prec = final_tp / (final_tp + final_fp) if (final_tp + final_fp) > 0 else 0.0
            rec = final_tp / n_gt if n_gt > 0 else 0.0
            f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0

            per_class[label] = {
                "precision": prec,
                "recall": rec,
                "f1": f1,
                "ap": ap,
                "tp": final_tp,
                "fp": final_fp,
                "fn": final_fn,
                "n_gt": n_gt,
            }

        mAP = np.mean(all_aps) if all_aps else 0.0
        overall_tp = sum(c["tp"] for c in per_class.values())
        overall_fp = sum(c["fp"] for c in per_class.values())
        overall_fn = sum(c["fn"] for c in per_class.values())

        overall_prec = overall_tp / (overall_tp + overall_fp) if (overall_tp + overall_fp) > 0 else 0.0
        overall_rec = overall_tp / (overall_tp + overall_fn) if (overall_tp + overall_fn) > 0 else 0.0
        overall_f1 = (
            2 * overall_prec * overall_rec / (overall_prec + overall_rec)
            if (overall_prec + overall_rec) > 0
            else 0.0
        )

        return {
            "per_class": per_class,
            "overall": {
                "precision": overall_prec,
                "recall": overall_rec,
                "f1": overall_f1,
                "mAP": mAP,
                "total_pred": total_pred,
                "total_gt": total_gt,
                "total_images": len(self._records),
            },
            "per_image": per_image_stats,
        }

    def print_report(self, results: Optional[dict] = None) -> None:
        """印出格式化的評估報告。"""
        if results is None:
            results = self.compute()

        overall = results["overall"]
        per_class = results["per_class"]

        print("\n" + "=" * 60)
        print("自動標注品質評估報告")
        print("=" * 60)
        print(f"評估圖片數：{overall['total_images']}")
        print(f"預測標注數：{overall['total_pred']}")
        print(f"人工標注數：{overall['total_gt']}")
        print(f"IoU 閾值：{self.iou_threshold}")
        print("-" * 60)
        print(f"整體精確率：{overall['precision']:.4f}")
        print(f"整體召回率：{overall['recall']:.4f}")
        print(f"整體 F1：{overall['f1']:.4f}")
        print(f"mAP@{self.iou_threshold}：{overall['mAP']:.4f}")
        print("-" * 60)

        if per_class:
            print(f"{'類別':<20} {'AP':>6} {'Prec':>6} {'Rec':>6} {'F1':>6} {'TP':>5} {'FP':>5} {'FN':>5}")
            print("-" * 60)
            for label, metrics in sorted(per_class.items(), key=lambda x: -x[1]["ap"]):
                print(
                    f"{label:<20} "
                    f"{metrics['ap']:>6.3f} "
                    f"{metrics['precision']:>6.3f} "
                    f"{metrics['recall']:>6.3f} "
                    f"{metrics['f1']:>6.3f} "
                    f"{metrics['tp']:>5} "
                    f"{metrics['fp']:>5} "
                    f"{metrics['fn']:>5}"
                )

        print("=" * 60)

    def get_low_quality_images(
        self, results: Optional[dict] = None, recall_threshold: float = 0.7
    ) -> list:
        """
        找出自動標注品質低的圖片（召回率不足），優先排給人工校正。

        Returns:
            list of (image_name, recall) 依召回率升序
        """
        if results is None:
            results = self.compute()

        low_quality = [
            (img["image"], img["recall"])
            for img in results["per_image"]
            if img["recall"] < recall_threshold
        ]
        return sorted(low_quality, key=lambda x: x[1])


# ---------------------------------------------------------------------------
# 輔助函式
# ---------------------------------------------------------------------------

def _compute_ap(recall: np.ndarray, precision: np.ndarray) -> float:
    """計算 11-point interpolated AP。"""
    ap = 0.0
    for threshold in np.arange(0.0, 1.1, 0.1):
        mask = recall >= threshold
        prec_at_threshold = precision[mask].max() if mask.any() else 0.0
        ap += prec_at_threshold
    return ap / 11.0
