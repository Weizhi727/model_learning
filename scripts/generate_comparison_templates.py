"""
generate_comparison_templates.py
— GroundingDINO vs YOLO 跨廠區泛化性比較投影片模板生成器

輸出 5 種版型，每種風格各 1 頁，共 6 頁（含說明頁）：
  P0  版型選擇指南（縮略圖 + 說明）
  T1  並排指標卡片式    — 強調單廠區的指標值比較
  T2  視覺化條形儀表板式 — 條形長度直觀呈現差距
  T3  多廠區對比表格式  — 所有廠區指標一覽 + 差值
  T4  泛化衰退瀑布式    — 突顯從訓練域到測試域的衰退幅度
  T5  精簡執行摘要式    — 給管理層看的最精簡版

置入方式：
  1. 用 PowerPoint 開啟 output/comparison_templates.pptx
  2. 選定你喜歡的版型所在頁面，複製到目標簡報
  3. 將所有標色為橘色 [ –.–– ] 的文字替換成實際數值
  4. 將所有灰色「📷 圖片置入」方框替換成截圖

使用方式：
  python scripts/generate_comparison_templates.py
  python scripts/generate_comparison_templates.py --output output/my_templates.pptx
"""

import argparse
import os
import sys
from pathlib import Path

try:
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN
    import pptx.oxml as oxml
except ImportError:
    print("[錯誤] 請先安裝 python-pptx：pip install python-pptx")
    sys.exit(1)


# =============================================================================
# 設計 Token
# =============================================================================
class C:
    # 品牌色
    GDINO      = RGBColor(0x1F, 0x4E, 0x79)   # 深藍 — GroundingDINO
    GDINO_LT   = RGBColor(0xBD, 0xD7, 0xEE)   # 淺藍
    YOLO       = RGBColor(0xED, 0x7D, 0x31)   # 橘 — YOLO
    YOLO_LT    = RGBColor(0xFC, 0xE4, 0xD6)   # 淺橘
    # 狀態色
    BETTER     = RGBColor(0x37, 0x86, 0x2D)   # 深綠（較優）
    BETTER_LT  = RGBColor(0xE2, 0xEF, 0xDA)   # 淺綠
    WORSE      = RGBColor(0xC0, 0x00, 0x00)   # 深紅（較差）
    WORSE_LT   = RGBColor(0xFF, 0xCC, 0xCC)   # 淺紅
    NEUTRAL    = RGBColor(0x59, 0x59, 0x59)
    NEUTRAL_LT = RGBColor(0xF2, 0xF2, 0xF2)
    # 排版
    PLACEHOLDER= RGBColor(0xED, 0x7D, 0x31)   # 橘色 → 代表「待填入」
    IMG_BG     = RGBColor(0xD6, 0xDC, 0xE4)   # 圖片佔位背景
    IMG_TEXT   = RGBColor(0x70, 0x80, 0x96)   # 圖片佔位文字
    HEADER_BG  = RGBColor(0x26, 0x26, 0x26)
    WHITE      = RGBColor(0xFF, 0xFF, 0xFF)
    BLACK      = RGBColor(0x00, 0x00, 0x00)
    DIVIDER    = RGBColor(0xCC, 0xCC, 0xCC)
    # 尺寸
    W = Inches(13.33)
    H = Inches(7.50)
    FONT = "Microsoft JhengHei"


# =============================================================================
# 底層繪圖工具
# =============================================================================
def rect(slide, l, t, w, h, fill=None, line=None, lw=Pt(0)):
    shape = slide.shapes.add_shape(1, l, t, w, h)
    if fill:
        shape.fill.solid(); shape.fill.fore_color.rgb = fill
    else:
        shape.fill.background()
    if line:
        shape.line.color.rgb = line; shape.line.width = lw
    else:
        shape.line.fill.background()
    return shape


def txt(slide, text, l, t, w, h,
        size=Pt(14), color=None, bold=False, italic=False,
        align=PP_ALIGN.LEFT, font=None, wrap=True):
    box = slide.shapes.add_textbox(l, t, w, h)
    tf = box.text_frame; tf.word_wrap = wrap
    p = tf.paragraphs[0]; p.alignment = align
    run = p.add_run(); run.text = text
    run.font.size = size; run.font.bold = bold; run.font.italic = italic
    run.font.name = font or C.FONT
    if color: run.font.color.rgb = color
    return box


def img_placeholder(slide, l, t, w, h, label="📷  圖片置入", note=""):
    rect(slide, l, t, w, h, fill=C.IMG_BG,
         line=C.IMG_TEXT, lw=Pt(1.5))
    note_str = f"\n{note}" if note else ""
    txt(slide, f"{label}{note_str}", l + Inches(0.1), t + h/2 - Inches(0.3),
        w - Inches(0.2), Inches(0.6),
        size=Pt(13), color=C.IMG_TEXT, align=PP_ALIGN.CENTER, italic=True)


def val_placeholder(slide, l, t, w, h, metric="", size=Pt(28)):
    """橘色數值佔位框 — 使用者填入實際數值"""
    rect(slide, l, t, w, h, fill=C.WHITE,
         line=C.PLACEHOLDER, lw=Pt(1.2))
    if metric:
        txt(slide, metric, l, t + Inches(0.05), w, Inches(0.3),
            size=Pt(10), color=C.NEUTRAL, align=PP_ALIGN.CENTER)
    txt(slide, "–.–––", l, t + Inches(0.3), w, h - Inches(0.3),
        size=size, color=C.PLACEHOLDER, bold=True, align=PP_ALIGN.CENTER)


def model_badge(slide, model, l, t):
    """GroundingDINO 或 YOLO 的彩色標籤"""
    is_gdino = "grounding" in model.lower() or "dino" in model.lower()
    bg = C.GDINO if is_gdino else C.YOLO
    rect(slide, l, t, Inches(2.4), Inches(0.38), fill=bg)
    txt(slide, model, l + Inches(0.1), t + Inches(0.03),
        Inches(2.2), Inches(0.32),
        size=Pt(13), color=C.WHITE, bold=True, align=PP_ALIGN.CENTER)


def header(slide, title, subtitle=""):
    rect(slide, 0, 0, C.W, Inches(0.95), fill=C.HEADER_BG)
    txt(slide, title, Inches(0.4), Inches(0.08), Inches(12), Inches(0.55),
        size=Pt(26), color=C.WHITE, bold=True)
    if subtitle:
        txt(slide, subtitle, Inches(0.4), Inches(0.62), Inches(12), Inches(0.3),
            size=Pt(12), color=RGBColor(0xA0, 0xA0, 0xA0))


def footer_note(slide, note):
    rect(slide, 0, Inches(7.22), C.W, Inches(0.28),
         fill=RGBColor(0xEE, 0xEE, 0xEE))
    txt(slide, note, Inches(0.3), Inches(7.24), Inches(12.7), Inches(0.24),
        size=Pt(9), color=C.NEUTRAL, italic=True)


def section_label(slide, text, l, t, w=Inches(1.8), h=Inches(0.32),
                  fill=None, tc=None):
    fill = fill or C.NEUTRAL
    tc = tc or C.WHITE
    rect(slide, l, t, w, h, fill=fill)
    txt(slide, text, l + Inches(0.08), t + Inches(0.03),
        w - Inches(0.16), h, size=Pt(11), color=tc,
        bold=True, align=PP_ALIGN.CENTER)


# =============================================================================
# 通用指標列表（4 項）
# =============================================================================
METRICS = ["Precision", "Recall", "F1-Score", "mAP@0.5"]
METRIC_ABBR = ["P", "R", "F1", "mAP"]


# =============================================================================
# 說明頁（P0）
# =============================================================================
def slide_guide(prs):
    sl = prs.slides.add_slide(prs.slide_layouts[6])
    rect(sl, 0, 0, C.W, C.H, fill=C.GDINO)

    txt(sl, "版型選擇指南", Inches(0.5), Inches(0.3),
        Inches(12), Inches(0.7), size=Pt(32), color=C.WHITE, bold=True)
    txt(sl, "選擇最符合你報告情境的版型，複製投影片後填入實際數值與圖片",
        Inches(0.5), Inches(1.0), Inches(12), Inches(0.4),
        size=Pt(15), color=C.GDINO_LT)

    templates = [
        ("T1", "並排指標卡片式",
         "每個模型一欄，四項指標各一張卡片\n適合：單廠區深入比較，加入樣本截圖"),
        ("T2", "視覺化條形儀表板式",
         "橫向條形直觀呈現兩模型差距\n適合：快速掃讀，一眼看出勝負"),
        ("T3", "多廠區對比表格式",
         "多廠區 × 多指標全覽表，含 Δ 差值欄\n適合：跨廠泛化性彙整報告"),
        ("T4", "泛化衰退瀑布式",
         "訓練域 → 測試域的指標下降可視化\n適合：說明為何泛化性是關鍵問題"),
        ("T5", "精簡執行摘要式",
         "最少元素，大數字 + 勝負判決\n適合：管理層報告或一頁式結論"),
    ]
    colors = [C.GDINO, C.YOLO,
              RGBColor(0x37, 0x86, 0x2D),
              RGBColor(0x70, 0x3A, 0xBE),
              RGBColor(0x20, 0x7A, 0x7A)]

    xs = [Inches(0.4), Inches(3.0), Inches(5.6), Inches(8.2), Inches(10.8)]
    for i, ((tag, title, desc), color, x) in enumerate(zip(templates, colors, xs)):
        y = Inches(1.65)
        rect(sl, x, y, Inches(2.3), Inches(5.4), fill=color)
        txt(sl, tag, x + Inches(0.1), y + Inches(0.15),
            Inches(2.1), Inches(0.55),
            size=Pt(28), color=C.WHITE, bold=True, align=PP_ALIGN.CENTER)
        rect(sl, x, y + Inches(0.75), Inches(2.3), Inches(0.02),
             fill=RGBColor(0xFF, 0xFF, 0xFF))
        txt(sl, title, x + Inches(0.1), y + Inches(0.85),
            Inches(2.1), Inches(0.55),
            size=Pt(13), color=C.WHITE, bold=True, align=PP_ALIGN.CENTER)
        txt(sl, desc, x + Inches(0.12), y + Inches(1.5),
            Inches(2.06), Inches(3.6),
            size=Pt(11), color=RGBColor(0xDD, 0xDD, 0xDD),
            align=PP_ALIGN.LEFT)
        txt(sl, f"第 {i+2} 頁 →",
            x + Inches(0.1), y + Inches(4.9), Inches(2.1), Inches(0.35),
            size=Pt(11), color=C.WHITE, italic=True, align=PP_ALIGN.CENTER)

    txt(sl, "📌  橘色 [ –.–– ] = 待填入數值　　灰色方塊 = 待置入圖片",
        Inches(0.5), Inches(7.1), Inches(12.3), Inches(0.35),
        size=Pt(12), color=C.YOLO_LT, align=PP_ALIGN.CENTER)


# =============================================================================
# T1：並排指標卡片式
# =============================================================================
def slide_t1(prs):
    sl = prs.slides.add_slide(prs.slide_layouts[6])
    header(sl, "T1  並排指標卡片式",
           "同工站、不同廠區 — GroundingDINO vs YOLO 指標比較")
    footer_note(sl,
        "📌 使用方式：將橘色 [ –.–– ] 替換為實際數值；灰色方塊替換為對應廠區的偵測截圖")

    # ── 廠區標籤 ──
    section_label(sl, "廠區：[ 填入廠區名稱 ]",
                  Inches(0.35), Inches(1.05),
                  w=Inches(3.5), h=Inches(0.36),
                  fill=C.NEUTRAL, tc=C.WHITE)
    section_label(sl, "工站：[ 填入工站代號 ]",
                  Inches(4.1), Inches(1.05),
                  w=Inches(2.8), h=Inches(0.36),
                  fill=RGBColor(0x40, 0x40, 0x40), tc=C.WHITE)

    # ── 兩欄標題 ──
    for label, x, bg in [("GroundingDINO", Inches(0.35), C.GDINO),
                          ("YOLO",          Inches(6.85), C.YOLO)]:
        rect(sl, x, Inches(1.52), Inches(6.1), Inches(0.42), fill=bg)
        txt(sl, label, x + Inches(0.15), Inches(1.55),
            Inches(5.8), Inches(0.36),
            size=Pt(18), color=C.WHITE, bold=True, align=PP_ALIGN.CENTER)

    # ── 四個指標卡片 ──
    for i, metric in enumerate(METRICS):
        col_offsets = [Inches(0.35), Inches(6.85)]
        card_w = Inches(2.8)
        card_h = Inches(1.18)
        card_y = Inches(2.05) + Inches(1.28) * i

        for j, (ox, bg_light) in enumerate(zip(col_offsets,
                                                [C.GDINO_LT, C.YOLO_LT])):
            cx = ox + Inches(0.1) + (Inches(3.1)) * (0 if j == 0 else 0)
            card_x = ox if j == 0 else ox
            # 左卡（指標名）
            rect(sl, card_x, card_y, Inches(1.5), card_h,
                 fill=C.GDINO if j == 0 else C.YOLO)
            txt(sl, metric,
                card_x + Inches(0.08), card_y + Inches(0.1),
                Inches(1.34), Inches(0.4),
                size=Pt(14), color=C.WHITE, bold=True, align=PP_ALIGN.CENTER)
            txt(sl, "(IoU=0.5)" if metric == "mAP@0.5" else "",
                card_x + Inches(0.08), card_y + Inches(0.48),
                Inches(1.34), Inches(0.25),
                size=Pt(9), color=RGBColor(0xCC, 0xCC, 0xFF),
                align=PP_ALIGN.CENTER)
            # 右卡（數值佔位）
            val_card_x = card_x + Inches(1.55)
            rect(sl, val_card_x, card_y, Inches(4.5), card_h,
                 fill=bg_light, line=C.PLACEHOLDER, lw=Pt(1.0))
            txt(sl, "–.–––",
                val_card_x + Inches(0.1), card_y + Inches(0.18),
                Inches(4.2), Inches(0.75),
                size=Pt(36), color=C.PLACEHOLDER, bold=True,
                align=PP_ALIGN.CENTER)
            txt(sl, "← 填入數值",
                val_card_x + Inches(0.1), card_y + Inches(0.9),
                Inches(4.2), Inches(0.22),
                size=Pt(9), color=C.NEUTRAL,
                align=PP_ALIGN.CENTER, italic=True)

        # 中線分隔
        rect(sl, Inches(6.5), card_y, Inches(0.02), card_h, fill=C.DIVIDER)

    # ── 圖片佔位 ──
    img_placeholder(sl, Inches(0.35), Inches(6.35), Inches(6.1), Inches(0.78),
                    label="📷  GroundingDINO 偵測截圖",
                    note="（廠區X 樣本圖）")
    img_placeholder(sl, Inches(6.85), Inches(6.35), Inches(6.1), Inches(0.78),
                    label="📷  YOLO 偵測截圖",
                    note="（廠區X 相同樣本）")


# =============================================================================
# T2：視覺化條形儀表板式
# =============================================================================
def slide_t2(prs):
    sl = prs.slides.add_slide(prs.slide_layouts[6])
    header(sl, "T2  視覺化條形儀表板式",
           "同工站、不同廠區 — 條形長度直觀呈現兩模型指標差距")
    footer_note(sl,
        "📌 橘色 –.–– = 填入實際數值；深色條長度 = 依實際值等比例調整；灰色方塊 = 置入截圖")

    # ── 廠區標籤列 ──
    for i, label in enumerate(["廠區 A", "廠區 B", "廠區 C", "廠區 D"]):
        x = Inches(0.35) + Inches(3.0) * i
        bg = C.GDINO if i == 0 else RGBColor(0x40, 0x40, 0x40)
        rect(sl, x, Inches(1.05), Inches(2.7), Inches(0.36), fill=bg)
        txt(sl, f"[ {label} ] ← 填廠區名",
            x + Inches(0.1), Inches(1.07),
            Inches(2.5), Inches(0.32),
            size=Pt(12), color=C.WHITE, bold=(i == 0),
            align=PP_ALIGN.CENTER)
        if i == 0:
            txt(sl, "訓練域（GL廠）",
                x + Inches(0.1), Inches(1.39),
                Inches(2.5), Inches(0.22),
                size=Pt(9), color=C.YOLO, align=PP_ALIGN.CENTER)

    # ── 圖例 ──
    rect(sl, Inches(0.35), Inches(1.68), Inches(0.22), Inches(0.22),
         fill=C.GDINO)
    txt(sl, "GroundingDINO", Inches(0.62), Inches(1.68),
        Inches(2.2), Inches(0.22), size=Pt(11), color=C.GDINO, bold=True)
    rect(sl, Inches(3.2), Inches(1.68), Inches(0.22), Inches(0.22),
         fill=C.YOLO)
    txt(sl, "YOLO", Inches(3.47), Inches(1.68),
        Inches(1.2), Inches(0.22), size=Pt(11), color=C.YOLO, bold=True)
    txt(sl, "（條形長度代表指標分數，請按實際數值調整）",
        Inches(5.0), Inches(1.68), Inches(7), Inches(0.22),
        size=Pt(10), color=C.NEUTRAL, italic=True)

    # ── 四個指標的條形組 ──
    bar_max_w = Inches(5.0)   # 滿分 1.0 對應的條形寬
    label_col_w = Inches(1.2)
    val_col_w   = Inches(1.0)
    bar_col_x   = Inches(1.6)
    bar_pair_h  = Inches(0.36)
    group_h     = bar_pair_h * 2 + Inches(0.12)

    for i, metric in enumerate(METRICS):
        gy = Inches(2.0) + group_h * i + Inches(0.1) * i

        # 指標名
        rect(sl, Inches(0.35), gy, label_col_w, group_h,
             fill=C.NEUTRAL_LT)
        txt(sl, metric,
            Inches(0.4), gy + group_h / 2 - Inches(0.18),
            label_col_w - Inches(0.1), Inches(0.36),
            size=Pt(13), color=C.GDINO, bold=True, align=PP_ALIGN.CENTER)

        for j, (model_color, bg_light) in enumerate(
                [(C.GDINO, C.GDINO_LT), (C.YOLO, C.YOLO_LT)]):
            by = gy + bar_pair_h * j + Inches(0.06) * j

            # 數值佔位（左）
            rect(sl, bar_col_x, by, val_col_w, bar_pair_h,
                 fill=bg_light, line=C.PLACEHOLDER, lw=Pt(0.8))
            txt(sl, "–.–––",
                bar_col_x + Inches(0.05), by + Inches(0.04),
                val_col_w - Inches(0.1), bar_pair_h - Inches(0.08),
                size=Pt(15), color=C.PLACEHOLDER, bold=True,
                align=PP_ALIGN.CENTER)

            # 示意條形（右）— 使用者需按實際數值調整長度
            bar_bg_x = bar_col_x + val_col_w + Inches(0.1)
            rect(sl, bar_bg_x, by + Inches(0.04),
                 bar_max_w, bar_pair_h - Inches(0.08),
                 fill=C.NEUTRAL_LT)
            # 示意條形（預設 60%）— 可在 PPT 中直接拖動調整寬度
            demo_w = bar_max_w * 0.6
            rect(sl, bar_bg_x, by + Inches(0.04), demo_w,
                 bar_pair_h - Inches(0.08), fill=model_color)
            txt(sl, "← 條形寬度請按數值等比例調整",
                bar_bg_x + demo_w + Inches(0.1),
                by + Inches(0.08),
                Inches(2.5), bar_pair_h - Inches(0.16),
                size=Pt(8.5), color=C.NEUTRAL, italic=True)

    # ── 底部圖片區 ──
    img_placeholder(sl, Inches(0.35), Inches(6.28), Inches(3.0), Inches(0.88),
                    label="📷 廠區A GT vs GDINO", note="")
    img_placeholder(sl, Inches(3.55), Inches(6.28), Inches(3.0), Inches(0.88),
                    label="📷 廠區A GT vs YOLO", note="")
    img_placeholder(sl, Inches(6.75), Inches(6.28), Inches(3.0), Inches(0.88),
                    label="📷 廠區B 偵測截圖", note="")
    img_placeholder(sl, Inches(9.95), Inches(6.28), Inches(3.0), Inches(0.88),
                    label="📷 廠區C 偵測截圖", note="")


# =============================================================================
# T3：多廠區對比表格式
# =============================================================================
def slide_t3(prs):
    sl = prs.slides.add_slide(prs.slide_layouts[6])
    header(sl, "T3  多廠區對比表格式",
           "跨廠區同工站泛化性指標總覽 — 含兩模型 Δ 差值")
    footer_note(sl,
        "📌 橘色儲存格 = 填入實際數值；Δ 欄 = GroundingDINO 分數 − YOLO 分數（正值=GDINO較好）；灰色方塊 = 置入截圖")

    # ── 廠區列表（預設3廠區，可複製列新增）──
    factories = ["GL 廠（訓練域）", "廠區 A", "廠區 B", "廠區 C", "平均（廠A-C）"]
    row_colors = [C.GDINO_LT,
                  C.WHITE, C.NEUTRAL_LT,
                  C.WHITE, RGBColor(0xFF, 0xF0, 0xCC)]
    factory_label_colors = [C.GDINO, C.NEUTRAL, C.NEUTRAL, C.NEUTRAL,
                             RGBColor(0x7F, 0x60, 0x00)]

    TABLE_X  = Inches(0.3)
    TABLE_Y  = Inches(1.06)
    COL_F    = Inches(1.6)    # 廠區名欄
    COL_VAL  = Inches(0.72)   # 指標值欄（每個）
    COL_D    = Inches(0.72)   # Δ 欄
    ROW_H    = Inches(0.52)
    n_metrics = 4

    total_val_cols = n_metrics * 2  # GDINO x4 + YOLO x4
    total_w = COL_F + COL_VAL * total_val_cols + COL_D

    # 表頭第一行：模型名
    rect(sl, TABLE_X, TABLE_Y, COL_F, ROW_H * 2, fill=C.HEADER_BG)
    txt(sl, "廠區 / 工站",
        TABLE_X, TABLE_Y + ROW_H * 0.3, COL_F, ROW_H * 1.4,
        size=Pt(12), color=C.WHITE, bold=True, align=PP_ALIGN.CENTER)

    for col_i, (model, bg) in enumerate(
            [("GroundingDINO", C.GDINO), ("YOLO", C.YOLO)]):
        mx = TABLE_X + COL_F + COL_VAL * n_metrics * col_i
        rect(sl, mx, TABLE_Y, COL_VAL * n_metrics, ROW_H, fill=bg)
        txt(sl, model, mx, TABLE_Y + Inches(0.08),
            COL_VAL * n_metrics, ROW_H - Inches(0.08),
            size=Pt(13), color=C.WHITE, bold=True, align=PP_ALIGN.CENTER)

    # Δ 欄標頭
    dx = TABLE_X + COL_F + COL_VAL * total_val_cols
    rect(sl, dx, TABLE_Y, COL_D, ROW_H * 2, fill=RGBColor(0x40, 0x30, 0x00))
    txt(sl, "Δ\nmAP", dx, TABLE_Y + Inches(0.06),
        COL_D, ROW_H * 1.85,
        size=Pt(11), color=C.YOLO_LT, bold=True, align=PP_ALIGN.CENTER)

    # 表頭第二行：指標名
    for col_i in range(2):
        for mi, abbr in enumerate(METRIC_ABBR):
            cx = TABLE_X + COL_F + COL_VAL * (col_i * n_metrics + mi)
            bg = C.GDINO if col_i == 0 else C.YOLO
            lbg = RGBColor(0x15, 0x3A, 0x5E) if col_i == 0 else RGBColor(0xB0, 0x5D, 0x22)
            rect(sl, cx, TABLE_Y + ROW_H, COL_VAL, ROW_H, fill=lbg)
            txt(sl, abbr, cx, TABLE_Y + ROW_H + Inches(0.1),
                COL_VAL, ROW_H - Inches(0.1),
                size=Pt(12), color=C.WHITE, bold=True, align=PP_ALIGN.CENTER)

    # 資料列
    for ri, (factory, row_bg, flabel_color) in enumerate(
            zip(factories, row_colors, factory_label_colors)):
        ry = TABLE_Y + ROW_H * 2 + ROW_H * ri

        # 廠區名
        rect(sl, TABLE_X, ry, COL_F, ROW_H, fill=row_bg)
        txt(sl, factory, TABLE_X + Inches(0.06), ry + Inches(0.1),
            COL_F - Inches(0.08), ROW_H - Inches(0.1),
            size=Pt(11), color=flabel_color, bold=(ri == 0 or ri == 4))

        # 8 個數值格（GDINO x4, YOLO x4）
        for col_i in range(2):
            for mi in range(n_metrics):
                cx = TABLE_X + COL_F + COL_VAL * (col_i * n_metrics + mi)
                val_bg = C.GDINO_LT if col_i == 0 else C.YOLO_LT
                val_bg = row_bg if ri == 0 else val_bg
                rect(sl, cx, ry, COL_VAL, ROW_H, fill=val_bg,
                     line=C.DIVIDER, lw=Pt(0.3))
                ph_color = C.NEUTRAL if ri == 0 else C.PLACEHOLDER
                txt(sl, "–.––" if ri > 0 else "–.––",
                    cx, ry + Inches(0.1), COL_VAL, ROW_H - Inches(0.1),
                    size=Pt(13), color=ph_color, bold=(ri == 0),
                    align=PP_ALIGN.CENTER)

        # Δ 欄（最後一欄）
        rect(sl, dx, ry, COL_D, ROW_H,
             fill=RGBColor(0xFF, 0xF5, 0xCC) if ri > 0 else C.NEUTRAL_LT,
             line=C.DIVIDER, lw=Pt(0.3))
        txt(sl, "±.––" if ri > 0 else "—",
            dx, ry + Inches(0.1), COL_D, ROW_H - Inches(0.1),
            size=Pt(13), color=RGBColor(0x80, 0x60, 0x00) if ri > 0 else C.NEUTRAL,
            bold=(ri == 0), align=PP_ALIGN.CENTER)

    # ── 圖片區（三廠區各一張）──
    img_x_list = [Inches(0.3), Inches(4.55), Inches(8.8)]
    for i, (xi, label) in enumerate(zip(img_x_list, ["廠區A 樣本", "廠區B 樣本", "廠區C 樣本"])):
        img_placeholder(sl, xi, Inches(6.28), Inches(4.0), Inches(0.9),
                        label=f"📷 {label}",
                        note="（GT + 兩模型疊圖）")


# =============================================================================
# T4：泛化衰退瀑布式
# =============================================================================
def slide_t4(prs):
    sl = prs.slides.add_slide(prs.slide_layouts[6])
    header(sl, "T4  泛化衰退瀑布式",
           "訓練域（GL廠）→ 測試域（其他廠區）— mAP@0.5 衰退可視化")
    footer_note(sl,
        "📌 橘色 –.–– = 填入實際數值；箭頭長度可依衰退幅度拖動調整；灰色方塊 = 置入截圖")

    # ── 說明文字 ──
    txt(sl, "衰退率  =  (訓練域 mAP − 測試域 mAP) / 訓練域 mAP × 100%",
        Inches(0.35), Inches(1.08), Inches(13), Inches(0.32),
        size=Pt(12), color=C.NEUTRAL, italic=True)
    txt(sl, "衰退率越低  →  跨廠泛化性越強",
        Inches(8.5), Inches(1.08), Inches(4.8), Inches(0.32),
        size=Pt(12), color=C.BETTER, bold=True)

    # ── 左側：GroundingDINO 衰退圖 ──
    rect(sl, Inches(0.3), Inches(1.5), Inches(5.9), Inches(5.62),
         fill=C.GDINO_LT, line=C.GDINO, lw=Pt(1.0))
    rect(sl, Inches(0.3), Inches(1.5), Inches(5.9), Inches(0.4), fill=C.GDINO)
    txt(sl, "GroundingDINO",
        Inches(0.4), Inches(1.52), Inches(5.7), Inches(0.36),
        size=Pt(16), color=C.WHITE, bold=True, align=PP_ALIGN.CENTER)

    # GL廠基準
    rect(sl, Inches(0.55), Inches(2.05), Inches(5.4), Inches(0.55),
         fill=C.GDINO)
    txt(sl, "GL廠（訓練域）  mAP@0.5 =",
        Inches(0.65), Inches(2.1), Inches(3.2), Inches(0.45),
        size=Pt(13), color=C.WHITE, bold=True)
    rect(sl, Inches(3.9), Inches(2.05), Inches(1.5), Inches(0.55),
         fill=C.WHITE, line=C.PLACEHOLDER, lw=Pt(1.5))
    txt(sl, "–.–––", Inches(3.9), Inches(2.1),
        Inches(1.5), Inches(0.45),
        size=Pt(18), color=C.PLACEHOLDER, bold=True, align=PP_ALIGN.CENTER)

    # 箭頭與廠區衰退（3廠區）
    arrow_labels = ["廠區 A", "廠區 B", "廠區 C"]
    for i, label in enumerate(arrow_labels):
        y = Inches(2.78) + Inches(0.95) * i

        txt(sl, f"↓  {label}  衰退",
            Inches(0.65), y, Inches(2.0), Inches(0.35),
            size=Pt(12), color=C.GDINO, bold=True)
        # 衰退率佔位
        rect(sl, Inches(2.7), y, Inches(1.3), Inches(0.38),
             fill=C.WHITE, line=C.PLACEHOLDER, lw=Pt(1.2))
        txt(sl, "−.–– %", Inches(2.7), y + Inches(0.04),
            Inches(1.3), Inches(0.3),
            size=Pt(13), color=C.WORSE, bold=True, align=PP_ALIGN.CENTER)
        # 測試域數值
        txt(sl, f"{label} mAP =",
            Inches(4.15), y, Inches(1.1), Inches(0.38),
            size=Pt(11), color=C.NEUTRAL)
        rect(sl, Inches(5.2), y, Inches(0.85), Inches(0.38),
             fill=C.GDINO_LT, line=C.PLACEHOLDER, lw=Pt(1.0))
        txt(sl, "–.––", Inches(5.2), y + Inches(0.04),
            Inches(0.85), Inches(0.3),
            size=Pt(13), color=C.PLACEHOLDER, bold=True,
            align=PP_ALIGN.CENTER)

    # 平均衰退
    rect(sl, Inches(0.55), Inches(5.65), Inches(5.4), Inches(0.42),
         fill=C.GDINO)
    txt(sl, "平均衰退率（廠A-C）：",
        Inches(0.65), Inches(5.68), Inches(2.8), Inches(0.36),
        size=Pt(13), color=C.WHITE, bold=True)
    rect(sl, Inches(3.6), Inches(5.65), Inches(1.5), Inches(0.42),
         fill=C.WHITE, line=C.PLACEHOLDER, lw=Pt(1.5))
    txt(sl, "−.– %", Inches(3.6), Inches(5.69),
        Inches(1.5), Inches(0.34),
        size=Pt(16), color=C.WORSE, bold=True, align=PP_ALIGN.CENTER)

    # ── 右側：YOLO 衰退圖 ──
    rect(sl, Inches(6.75), Inches(1.5), Inches(5.9), Inches(5.62),
         fill=C.YOLO_LT, line=C.YOLO, lw=Pt(1.0))
    rect(sl, Inches(6.75), Inches(1.5), Inches(5.9), Inches(0.4), fill=C.YOLO)
    txt(sl, "YOLO",
        Inches(6.85), Inches(1.52), Inches(5.7), Inches(0.36),
        size=Pt(16), color=C.WHITE, bold=True, align=PP_ALIGN.CENTER)

    # GL廠基準
    rect(sl, Inches(7.0), Inches(2.05), Inches(5.4), Inches(0.55),
         fill=C.YOLO)
    txt(sl, "GL廠（訓練域）  mAP@0.5 =",
        Inches(7.1), Inches(2.1), Inches(3.2), Inches(0.45),
        size=Pt(13), color=C.WHITE, bold=True)
    rect(sl, Inches(10.35), Inches(2.05), Inches(1.5), Inches(0.55),
         fill=C.WHITE, line=C.PLACEHOLDER, lw=Pt(1.5))
    txt(sl, "–.–––", Inches(10.35), Inches(2.1),
        Inches(1.5), Inches(0.45),
        size=Pt(18), color=C.PLACEHOLDER, bold=True, align=PP_ALIGN.CENTER)

    for i, label in enumerate(arrow_labels):
        y = Inches(2.78) + Inches(0.95) * i
        txt(sl, f"↓  {label}  衰退",
            Inches(7.1), y, Inches(2.0), Inches(0.35),
            size=Pt(12), color=C.YOLO, bold=True)
        rect(sl, Inches(9.15), y, Inches(1.3), Inches(0.38),
             fill=C.WHITE, line=C.PLACEHOLDER, lw=Pt(1.2))
        txt(sl, "−.–– %", Inches(9.15), y + Inches(0.04),
            Inches(1.3), Inches(0.3),
            size=Pt(13), color=C.WORSE, bold=True, align=PP_ALIGN.CENTER)
        txt(sl, f"{label} mAP =",
            Inches(10.6), y, Inches(1.1), Inches(0.38),
            size=Pt(11), color=C.NEUTRAL)
        rect(sl, Inches(11.65), y, Inches(0.85), Inches(0.38),
             fill=C.YOLO_LT, line=C.PLACEHOLDER, lw=Pt(1.0))
        txt(sl, "–.––", Inches(11.65), y + Inches(0.04),
            Inches(0.85), Inches(0.3),
            size=Pt(13), color=C.PLACEHOLDER, bold=True,
            align=PP_ALIGN.CENTER)

    rect(sl, Inches(7.0), Inches(5.65), Inches(5.4), Inches(0.42),
         fill=C.YOLO)
    txt(sl, "平均衰退率（廠A-C）：",
        Inches(7.1), Inches(5.68), Inches(2.8), Inches(0.36),
        size=Pt(13), color=C.WHITE, bold=True)
    rect(sl, Inches(10.05), Inches(5.65), Inches(1.5), Inches(0.42),
         fill=C.WHITE, line=C.PLACEHOLDER, lw=Pt(1.5))
    txt(sl, "−.– %", Inches(10.05), Inches(5.69),
        Inches(1.5), Inches(0.34),
        size=Pt(16), color=C.WORSE, bold=True, align=PP_ALIGN.CENTER)

    # ── 中間判決 ──
    rect(sl, Inches(6.4), Inches(2.85), Inches(0.28), Inches(3.6),
         fill=C.DIVIDER)
    rect(sl, Inches(6.08), Inches(4.35), Inches(1.18), Inches(0.42),
         fill=C.NEUTRAL)
    txt(sl, "vs", Inches(6.08), Inches(4.37),
        Inches(1.18), Inches(0.38),
        size=Pt(18), color=C.WHITE, bold=True, align=PP_ALIGN.CENTER)


# =============================================================================
# T5：精簡執行摘要式
# =============================================================================
def slide_t5(prs):
    sl = prs.slides.add_slide(prs.slide_layouts[6])
    header(sl, "T5  精簡執行摘要式",
           "同工站跨廠區泛化性比較 — 一頁概覽")
    footer_note(sl,
        "📌 橘色 –.–– = 填入實際數值；[勝/敗] 標籤 = 根據比較結果手動更改顏色；灰色方塊 = 置入代表性截圖")

    # ── 廠區說明列 ──
    rect(sl, Inches(0.35), Inches(1.05), Inches(12.6), Inches(0.4),
         fill=C.NEUTRAL_LT)
    txt(sl, "工站：[ 填入工站代號 ]   |   訓練域：GL廠   |   測試域：廠區A、B、C（模型均未見過）",
        Inches(0.5), Inches(1.1), Inches(12.2), Inches(0.35),
        size=Pt(12), color=C.NEUTRAL, align=PP_ALIGN.CENTER)

    # ── 4 大指標 × 2 模型 ──
    card_w = Inches(1.6)
    card_h = Inches(1.45)
    START_X = Inches(0.35)
    ROW1_Y  = Inches(1.55)
    ROW2_Y  = Inches(3.2)

    model_labels = [("GroundingDINO", C.GDINO, C.GDINO_LT),
                    ("YOLO",          C.YOLO,  C.YOLO_LT)]

    for row, (model_name, model_color, model_lt) in enumerate(model_labels):
        ry = ROW1_Y if row == 0 else ROW2_Y

        # 模型標籤
        rect(sl, START_X, ry, Inches(1.3), card_h, fill=model_color)
        txt(sl, model_name,
            START_X + Inches(0.05), ry + Inches(0.4),
            Inches(1.2), Inches(0.65),
            size=Pt(14), color=C.WHITE, bold=True, align=PP_ALIGN.CENTER)

        for mi, metric in enumerate(METRICS):
            cx = START_X + Inches(1.45) + Inches(1.65) * mi

            rect(sl, cx, ry, card_w, card_h,
                 fill=model_lt, line=model_color, lw=Pt(0.8))
            txt(sl, metric,
                cx + Inches(0.08), ry + Inches(0.08),
                card_w - Inches(0.12), Inches(0.3),
                size=Pt(10.5), color=model_color, bold=True,
                align=PP_ALIGN.CENTER)
            txt(sl, "–.–––",
                cx + Inches(0.05), ry + Inches(0.38),
                card_w - Inches(0.1), Inches(0.7),
                size=Pt(30), color=C.PLACEHOLDER, bold=True,
                align=PP_ALIGN.CENTER)
            # 衰退率
            rect(sl, cx + Inches(0.1), ry + Inches(1.1),
                 card_w - Inches(0.2), Inches(0.28),
                 fill=model_color)
            txt(sl, "Δ = −.–– %",
                cx + Inches(0.1), ry + Inches(1.12),
                card_w - Inches(0.2), Inches(0.24),
                size=Pt(10), color=C.WHITE, align=PP_ALIGN.CENTER)

    # ── 右側：勝負判決 ──
    rect(sl, Inches(8.0), Inches(1.55), Inches(5.0), Inches(3.1),
         fill=C.NEUTRAL_LT, line=C.NEUTRAL, lw=Pt(0.5))
    txt(sl, "綜合判決",
        Inches(8.2), Inches(1.65), Inches(4.6), Inches(0.4),
        size=Pt(18), color=C.NEUTRAL, bold=True, align=PP_ALIGN.CENTER)

    verdict_items = [
        ("泛化衰退率",    "GroundingDINO  /  YOLO"),
        ("召回率穩定性",  "GroundingDINO  /  YOLO"),
        ("精確率穩定性",  "GroundingDINO  /  YOLO"),
        ("推薦標注方案",  "GroundingDINO  /  YOLO"),
    ]
    for i, (label, winner_placeholder) in enumerate(verdict_items):
        vy = Inches(2.15) + Inches(0.52) * i
        txt(sl, label,
            Inches(8.2), vy, Inches(2.0), Inches(0.42),
            size=Pt(12), color=C.NEUTRAL, bold=True)
        rect(sl, Inches(10.35), vy, Inches(2.45), Inches(0.42),
             fill=C.NEUTRAL_LT, line=C.PLACEHOLDER, lw=Pt(1.0))
        txt(sl, winner_placeholder,
            Inches(10.38), vy + Inches(0.06),
            Inches(2.35), Inches(0.32),
            size=Pt(11), color=C.PLACEHOLDER,
            align=PP_ALIGN.CENTER, italic=True)

    # ── 圖片區（左右各一）──
    img_placeholder(sl, Inches(0.35), Inches(4.8), Inches(6.0), Inches(2.3),
                    label="📷  代表性截圖（廠區A）",
                    note="GroundingDINO + YOLO 偵測結果對比")
    img_placeholder(sl, Inches(6.6), Inches(4.8), Inches(6.1), Inches(2.3),
                    label="📷  代表性截圖（廠區B / C）",
                    note="同工站不同廠區的圖像差異示意")


# =============================================================================
# 主程式
# =============================================================================
def generate(output_path: str):
    prs = Presentation()
    prs.slide_width  = C.W
    prs.slide_height = C.H

    print("[模板生成] 開始...")
    slide_guide(prs);  print("  ✓  P0  版型選擇指南")
    slide_t1(prs);     print("  ✓  T1  並排指標卡片式")
    slide_t2(prs);     print("  ✓  T2  視覺化條形儀表板式")
    slide_t3(prs);     print("  ✓  T3  多廠區對比表格式")
    slide_t4(prs);     print("  ✓  T4  泛化衰退瀑布式")
    slide_t5(prs);     print("  ✓  T5  精簡執行摘要式")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    prs.save(output_path)
    print(f"\n[完成]  已儲存：{output_path}")
    print("[提示]  共 6 頁，第 1 頁為版型選擇指南，第 2~6 頁為各版型模板")
    print("[提示]  橘色 [ –.–– ] = 待填入數值　灰色方塊 = 待置入圖片")


def main():
    parser = argparse.ArgumentParser(
        description="生成跨廠區泛化性比較投影片模板（5 種版型）"
    )
    parser.add_argument(
        "--output", "-o",
        default="output/comparison_templates.pptx",
        help="輸出路徑（預設：output/comparison_templates.pptx）"
    )
    args = parser.parse_args()
    generate(args.output)


if __name__ == "__main__":
    main()
