"""
GroundingDINO 推論封裝模組

支援兩種載入方式：
1. 本地安裝（需 clone GroundingDINO repo 並 pip install -e .）
2. HuggingFace Transformers（不需本地安裝，推薦用於快速測試）

輸出統一轉為 LabelMe JSON 格式。
"""

import os
import warnings
from pathlib import Path
from typing import Optional, Union
import numpy as np


# ---------------------------------------------------------------------------
# 統一推論結果格式
# ---------------------------------------------------------------------------

class DetectionResult:
    """單次推論結果容器。"""

    def __init__(
        self,
        boxes_xyxy: list,   # [[x1,y1,x2,y2], ...] 絕對像素座標
        labels: list,        # ["label1", "label2", ...]
        scores: list,        # [0.85, 0.72, ...]
        image_width: int,
        image_height: int,
    ):
        self.boxes_xyxy = boxes_xyxy
        self.labels = labels
        self.scores = scores
        self.image_width = image_width
        self.image_height = image_height

    def __len__(self):
        return len(self.boxes_xyxy)

    def __repr__(self):
        return (
            f"DetectionResult({len(self)} detections, "
            f"image={self.image_width}x{self.image_height})"
        )

    def to_labelme_shapes(self) -> list:
        """轉換為 LabelMe shapes 列表。"""
        from src.labelme_utils import xyxy_to_points, make_shape
        shapes = []
        for box, label, score in zip(self.boxes_xyxy, self.labels, self.scores):
            x1, y1, x2, y2 = box
            shapes.append(
                make_shape(
                    label=label,
                    points=xyxy_to_points(x1, y1, x2, y2),
                    shape_type="rectangle",
                    confidence=score,
                )
            )
        return shapes

    def filter_by_score(self, min_score: float) -> "DetectionResult":
        """過濾低信心分數的結果。"""
        filtered = [
            (b, l, s)
            for b, l, s in zip(self.boxes_xyxy, self.labels, self.scores)
            if s >= min_score
        ]
        if not filtered:
            return DetectionResult([], [], [], self.image_width, self.image_height)
        boxes, labels, scores = zip(*filtered)
        return DetectionResult(
            list(boxes), list(labels), list(scores),
            self.image_width, self.image_height,
        )

    def apply_nms(self, iou_threshold: float = 0.5) -> "DetectionResult":
        """對相同類別的結果進行非極大值抑制（NMS）。"""
        if len(self) == 0:
            return self

        try:
            import torch
            from torchvision.ops import nms

            boxes_tensor = torch.tensor(self.boxes_xyxy, dtype=torch.float32)
            scores_tensor = torch.tensor(self.scores, dtype=torch.float32)
            keep = nms(boxes_tensor, scores_tensor, iou_threshold).tolist()

            return DetectionResult(
                [self.boxes_xyxy[i] for i in keep],
                [self.labels[i] for i in keep],
                [self.scores[i] for i in keep],
                self.image_width,
                self.image_height,
            )
        except ImportError:
            warnings.warn("torchvision 未安裝，跳過 NMS。")
            return self


# ---------------------------------------------------------------------------
# HuggingFace 版本（推薦，不需本地安裝 GroundingDINO）
# ---------------------------------------------------------------------------

class GroundingDINOHF:
    """
    使用 HuggingFace Transformers 的 GroundingDINO 推論器。

    優點：安裝簡單，只需 pip install transformers
    缺點：需要網路下載模型（首次）

    使用範例：
        model = GroundingDINOHF(model_id="IDEA-Research/grounding-dino-tiny")
        result = model.predict("image.jpg", categories=["screw", "bolt", "glove"])
    """

    AVAILABLE_MODELS = {
        "tiny": "IDEA-Research/grounding-dino-tiny",    # 較快，精度稍低
        "base": "IDEA-Research/grounding-dino-base",    # 較慢，精度較高
    }

    def __init__(
        self,
        model_id: str = "IDEA-Research/grounding-dino-tiny",
        device: Optional[str] = None,
        box_threshold: float = 0.35,
        text_threshold: float = 0.25,
    ):
        """
        Args:
            model_id: HuggingFace model ID 或本地路徑
            device: "cuda", "cpu", 或 None（自動選擇）
            box_threshold: BBox 信心閾值（0~1），越高越嚴格
            text_threshold: 文字匹配閾值（0~1）
        """
        self.model_id = model_id
        self.box_threshold = box_threshold
        self.text_threshold = text_threshold

        import torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._model = None
        self._processor = None

    def _load(self):
        """延遲載入模型（首次推論時才載入）。"""
        if self._model is not None:
            return

        from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection

        print(f"[GroundingDINO] 載入模型：{self.model_id}")
        self._processor = AutoProcessor.from_pretrained(self.model_id)
        self._model = AutoModelForZeroShotObjectDetection.from_pretrained(
            self.model_id
        ).to(self.device)
        print(f"[GroundingDINO] 模型已載入到 {self.device}")

    def _build_text_prompt(self, categories: list) -> str:
        """
        將類別列表轉為 GroundingDINO 文字提示格式。

        GroundingDINO 使用 ". " 分隔多個類別，並以 "." 結尾。
        範例: ["screw", "bolt"] → "screw . bolt ."
        """
        return " . ".join(categories) + " ."

    def predict(
        self,
        image: Union[str, "PIL.Image.Image", np.ndarray],
        categories: list,
        box_threshold: Optional[float] = None,
        text_threshold: Optional[float] = None,
    ) -> DetectionResult:
        """
        對單張圖片進行物件偵測。

        Args:
            image: 圖片路徑、PIL Image 或 numpy array
            categories: 要偵測的類別列表，例如 ["screw", "bolt", "glove"]
            box_threshold: 覆蓋預設 BBox 閾值
            text_threshold: 覆蓋預設文字閾值

        Returns:
            DetectionResult
        """
        self._load()

        from PIL import Image as PILImage
        import torch

        box_thr = box_threshold or self.box_threshold
        text_thr = text_threshold or self.text_threshold

        # 載入圖片
        if isinstance(image, str):
            pil_image = PILImage.open(image).convert("RGB")
        elif isinstance(image, np.ndarray):
            pil_image = PILImage.fromarray(image)
        else:
            pil_image = image

        image_width, image_height = pil_image.size

        text_prompt = self._build_text_prompt(categories)

        # 前處理
        inputs = self._processor(
            images=pil_image,
            text=text_prompt,
            return_tensors="pt",
        ).to(self.device)

        # 推論
        with torch.no_grad():
            outputs = self._model(**inputs)

        # 後處理
        results = self._processor.post_process_grounded_object_detection(
            outputs,
            inputs.input_ids,
            box_threshold=box_thr,
            text_threshold=text_thr,
            target_sizes=[(image_height, image_width)],
        )

        result = results[0]
        boxes = result["boxes"].cpu().tolist()      # [[x1,y1,x2,y2], ...]
        scores = result["scores"].cpu().tolist()
        labels = result["labels"]                   # list of str

        return DetectionResult(
            boxes_xyxy=boxes,
            labels=labels,
            scores=scores,
            image_width=image_width,
            image_height=image_height,
        )

    def predict_batch(
        self,
        image_paths: list,
        categories: list,
        box_threshold: Optional[float] = None,
        text_threshold: Optional[float] = None,
        verbose: bool = True,
    ) -> list:
        """
        批次推論多張圖片。

        Returns:
            list of (image_path, DetectionResult)
        """
        results = []
        total = len(image_paths)
        for i, image_path in enumerate(image_paths):
            if verbose:
                print(f"[{i+1}/{total}] 處理：{os.path.basename(image_path)}")
            result = self.predict(image_path, categories, box_threshold, text_threshold)
            results.append((image_path, result))
        return results


# ---------------------------------------------------------------------------
# 本地安裝版本（GroundingDINO repo 需已安裝）
# ---------------------------------------------------------------------------

class GroundingDINOLocal:
    """
    使用本地安裝的 GroundingDINO 推論器。

    需先執行：
        git clone https://github.com/IDEA-Research/GroundingDINO.git
        cd GroundingDINO && pip install -e .

    使用範例：
        model = GroundingDINOLocal(
            config_path="GroundingDINO/groundingdino/config/GroundingDINO_SwinT_OGC.py",
            checkpoint_path="weights/groundingdino_swint_ogc.pth",
        )
        result = model.predict("image.jpg", categories=["screw", "bolt"])
    """

    def __init__(
        self,
        config_path: str,
        checkpoint_path: str,
        device: Optional[str] = None,
        box_threshold: float = 0.35,
        text_threshold: float = 0.25,
    ):
        self.config_path = config_path
        self.checkpoint_path = checkpoint_path
        self.box_threshold = box_threshold
        self.text_threshold = text_threshold

        import torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._model = None

    def _load(self):
        if self._model is not None:
            return

        try:
            from groundingdino.util.inference import load_model
        except ImportError:
            raise ImportError(
                "GroundingDINO 未安裝。請執行：\n"
                "  git clone https://github.com/IDEA-Research/GroundingDINO.git\n"
                "  cd GroundingDINO && pip install -e ."
            )

        print(f"[GroundingDINO] 載入本地模型：{self.checkpoint_path}")
        self._model = load_model(self.config_path, self.checkpoint_path)
        print(f"[GroundingDINO] 模型已載入到 {self.device}")

    def _build_text_prompt(self, categories: list) -> str:
        return " . ".join(categories) + " ."

    def predict(
        self,
        image: Union[str, np.ndarray],
        categories: list,
        box_threshold: Optional[float] = None,
        text_threshold: Optional[float] = None,
    ) -> DetectionResult:
        self._load()

        from groundingdino.util.inference import load_image, predict
        from PIL import Image as PILImage
        import torch

        box_thr = box_threshold or self.box_threshold
        text_thr = text_threshold or self.text_threshold

        if isinstance(image, str):
            image_source, image_tensor = load_image(image)
            pil_img = PILImage.open(image).convert("RGB")
            image_height, image_width = image_source.shape[:2]
        else:
            raise ValueError("本地版本目前僅支援圖片路徑輸入。")

        text_prompt = self._build_text_prompt(categories)

        boxes, logits, phrases = predict(
            model=self._model,
            image=image_tensor,
            caption=text_prompt,
            box_threshold=box_thr,
            text_threshold=text_thr,
            device=self.device,
        )

        # boxes 為正規化的 cx,cy,w,h 格式，需轉為絕對 xyxy
        from src.labelme_utils import denormalize_bbox
        boxes_xyxy = [
            list(denormalize_bbox(tuple(b.tolist()), image_width, image_height))
            for b in boxes
        ]

        return DetectionResult(
            boxes_xyxy=boxes_xyxy,
            labels=phrases,
            scores=logits.tolist(),
            image_width=image_width,
            image_height=image_height,
        )


# ---------------------------------------------------------------------------
# 工廠函式：自動選擇最佳可用版本
# ---------------------------------------------------------------------------

def create_model(
    mode: str = "auto",
    hf_model_id: str = "IDEA-Research/grounding-dino-tiny",
    local_config: Optional[str] = None,
    local_checkpoint: Optional[str] = None,
    device: Optional[str] = None,
    box_threshold: float = 0.35,
    text_threshold: float = 0.25,
) -> Union[GroundingDINOHF, GroundingDINOLocal]:
    """
    建立 GroundingDINO 推論器。

    Args:
        mode: "auto" | "hf" | "local"
              "auto" 會優先嘗試本地版本，若未安裝則使用 HuggingFace 版本
        hf_model_id: HuggingFace 模型 ID
        local_config: 本地設定檔路徑（mode="local" 時必填）
        local_checkpoint: 本地權重路徑（mode="local" 時必填）
        device: "cuda" | "cpu" | None（自動）
        box_threshold: BBox 信心閾值
        text_threshold: 文字匹配閾值

    Returns:
        GroundingDINOHF 或 GroundingDINOLocal 實例
    """
    if mode == "hf":
        return GroundingDINOHF(
            model_id=hf_model_id,
            device=device,
            box_threshold=box_threshold,
            text_threshold=text_threshold,
        )

    if mode == "local":
        assert local_config and local_checkpoint, (
            "mode='local' 時必須提供 local_config 和 local_checkpoint"
        )
        return GroundingDINOLocal(
            config_path=local_config,
            checkpoint_path=local_checkpoint,
            device=device,
            box_threshold=box_threshold,
            text_threshold=text_threshold,
        )

    # mode == "auto"：優先本地
    if local_config and local_checkpoint and os.path.exists(local_checkpoint):
        try:
            import groundingdino  # noqa
            return GroundingDINOLocal(
                config_path=local_config,
                checkpoint_path=local_checkpoint,
                device=device,
                box_threshold=box_threshold,
                text_threshold=text_threshold,
            )
        except ImportError:
            pass

    return GroundingDINOHF(
        model_id=hf_model_id,
        device=device,
        box_threshold=box_threshold,
        text_threshold=text_threshold,
    )
