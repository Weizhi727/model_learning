"""
generate_ppt.py — GroundingDINO vs YOLO 泛化性評估 PPT 生成腳本

生成包含以下 11 張投影片的 .pptx 簡報：
  1.  標題頁
  2.  研究背景與動機
  3.  模型訓練資料設定
  4.  核心架構差異
  5.  評估場景一：跨廠區泛化
  6.  評估場景二：機台調整期間
  7.  評估場景三：數據增強測試
  8.  實驗設計對照矩陣
  9.  評估指標定義
  10. 預期假設
  11. 結論與下一步

使用方式：
  pip install python-pptx
  python scripts/generate_ppt.py
  python scripts/generate_ppt.py --output output/my_report.pptx
  python scripts/generate_ppt.py --lang en   # 英文版（預設中文）
"""

import argparse
import os
import sys
from pathlib import Path

try:
    from pptx import Presentation
    from pptx.util import Inches, Pt, Emu
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN
    from pptx.oxml.ns import qn
    from pptx.util import Inches, Pt
    import pptx.oxml as oxml
except ImportError:
    print("[錯誤] 請先安裝 python-pptx：pip install python-pptx")
    sys.exit(1)


# =============================================================================
# 設計系統（Design Tokens）
# =============================================================================

class Theme:
    # 主色調
    DARK_BLUE    = RGBColor(0x1F, 0x4E, 0x79)   # 深藍（標題背景）
    MID_BLUE     = RGBColor(0x2E, 0x75, 0xB6)   # 中藍（次要標題、強調）
    LIGHT_BLUE   = RGBColor(0xBD, 0xD7, 0xEE)   # 淺藍（背景色塊）
    ORANGE       = RGBColor(0xED, 0x7D, 0x31)   # 橘色（重點標記）
    GREEN        = RGBColor(0x70, 0xAD, 0x47)   # 綠色（正面指標）
    RED          = RGBColor(0xFF, 0x4D, 0x4D)   # 紅色（警示）
    YELLOW       = RGBColor(0xFF, 0xC0, 0x00)   # 黃色（說明標籤）

    # 中性色
    WHITE        = RGBColor(0xFF, 0xFF, 0xFF)
    DARK_GRAY    = RGBColor(0x26, 0x26, 0x26)
    MID_GRAY     = RGBColor(0x59, 0x59, 0x59)
    LIGHT_GRAY   = RGBColor(0xF2, 0xF2, 0xF2)
    TABLE_HEADER = RGBColor(0x1F, 0x4E, 0x79)
    TABLE_ALT    = RGBColor(0xED, 0xF3, 0xFB)

    # 字型
    FONT_TITLE   = "Microsoft JhengHei"   # 微軟正黑體（繁體中文）
    FONT_BODY    = "Microsoft JhengHei"
    FONT_MONO    = "Consolas"

    # 投影片尺寸（16:9）
    SLIDE_W      = Inches(13.33)
    SLIDE_H      = Inches(7.50)


# =============================================================================
# 底層繪圖輔助函式
# =============================================================================

def _rgb(r, g, b) -> RGBColor:
    return RGBColor(r, g, b)


def add_rect(slide, left, top, width, height, fill_color=None, line_color=None, line_width=Pt(0)):
    """新增矩形色塊。"""
    from pptx.util import Emu
    shape = slide.shapes.add_shape(
        1,  # MSO_SHAPE_TYPE.RECTANGLE
        left, top, width, height
    )
    shape.line.width = line_width
    if fill_color:
        shape.fill.solid()
        shape.fill.fore_color.rgb = fill_color
    else:
        shape.fill.background()
    if line_color:
        shape.line.color.rgb = line_color
    else:
        shape.line.fill.background()
    return shape


def add_textbox(
    slide, text, left, top, width, height,
    font_size=Pt(16), font_color=None, bold=False, italic=False,
    align=PP_ALIGN.LEFT, font_name=None, word_wrap=True
):
    """新增文字框。"""
    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf = txBox.text_frame
    tf.word_wrap = word_wrap
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.size = font_size
    run.font.bold = bold
    run.font.italic = italic
    run.font.name = font_name or Theme.FONT_BODY
    if font_color:
        run.font.color.rgb = font_color
    return txBox


def add_text_frame(
    slide, lines, left, top, width, height,
    base_font_size=Pt(14), base_color=None, font_name=None,
    line_spacing=1.2
):
    """
    新增多行文字框，lines 格式：
      [{"text": "...", "size": Pt(16), "bold": True, "color": RGBColor, "bullet": True}, ...]
    """
    from pptx.util import Pt as _Pt
    from pptx.oxml.ns import qn as _qn
    import lxml.etree as etree

    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf = txBox.text_frame
    tf.word_wrap = True

    for i, line in enumerate(lines):
        if i == 0:
            para = tf.paragraphs[0]
        else:
            para = tf.add_paragraph()

        para.alignment = line.get("align", PP_ALIGN.LEFT)
        if line.get("space_before"):
            para.space_before = line["space_before"]

        run = para.add_run()
        run.text = line.get("text", "")
        run.font.size = line.get("size", base_font_size)
        run.font.bold = line.get("bold", False)
        run.font.italic = line.get("italic", False)
        run.font.name = line.get("font", font_name or Theme.FONT_BODY)
        color = line.get("color", base_color)
        if color:
            run.font.color.rgb = color

    return txBox


def add_table(
    slide, data, col_widths, left, top, row_height=Inches(0.42),
    header_fill=None, alt_fill=None, font_size=Pt(12),
    header_font_size=Pt(13), font_name=None
):
    """
    新增表格。
    data: [[header1, header2, ...], [row1_col1, ...], ...]
    col_widths: [Inches(x), ...]
    """
    rows = len(data)
    cols = len(data[0])
    total_width = sum(col_widths)
    total_height = row_height * rows

    tbl = slide.shapes.add_table(rows, cols, left, top, total_width, total_height)

    for ci, w in enumerate(col_widths):
        tbl.table.columns[ci].width = w

    for ri, row_data in enumerate(data):
        for ci, cell_text in enumerate(row_data):
            cell = tbl.table.cell(ri, ci)
            cell.text = str(cell_text)

            # 字型
            for para in cell.text_frame.paragraphs:
                para.alignment = PP_ALIGN.CENTER
                for run in para.runs:
                    run.font.name = font_name or Theme.FONT_BODY
                    run.font.size = header_font_size if ri == 0 else font_size
                    run.font.bold = (ri == 0)
                    if ri == 0:
                        run.font.color.rgb = Theme.WHITE

            # 填色
            fill = cell.fill
            fill.solid()
            if ri == 0:
                fill.fore_color.rgb = header_fill or Theme.TABLE_HEADER
            elif ri % 2 == 0:
                fill.fore_color.rgb = alt_fill or Theme.TABLE_ALT
            else:
                fill.fore_color.rgb = Theme.WHITE

    return tbl


# =============================================================================
# 共用版面元件
# =============================================================================

def add_slide_header(slide, title_text, subtitle_text=None, bg_color=None):
    """頂部標題色帶（非標題頁使用）。"""
    bg = bg_color or Theme.DARK_BLUE
    # 頂部色帶
    add_rect(slide, Inches(0), Inches(0), Theme.SLIDE_W, Inches(1.15), fill_color=bg)
    # 標題文字
    add_textbox(
        slide, title_text,
        Inches(0.4), Inches(0.15), Inches(12), Inches(0.7),
        font_size=Pt(28), font_color=Theme.WHITE, bold=True,
        align=PP_ALIGN.LEFT
    )
    # 副標題
    if subtitle_text:
        add_textbox(
            slide, subtitle_text,
            Inches(0.4), Inches(0.80), Inches(12), Inches(0.35),
            font_size=Pt(13), font_color=Theme.LIGHT_BLUE,
            align=PP_ALIGN.LEFT
        )


def add_slide_footer(slide, page_num, total_pages):
    """底部頁碼列。"""
    add_rect(slide, Inches(0), Inches(7.2), Theme.SLIDE_W, Inches(0.3), fill_color=Theme.LIGHT_GRAY)
    add_textbox(
        slide, f"{page_num} / {total_pages}",
        Inches(12.5), Inches(7.2), Inches(0.8), Inches(0.3),
        font_size=Pt(9), font_color=Theme.MID_GRAY, align=PP_ALIGN.RIGHT
    )


def add_badge(slide, text, left, top, width=Inches(1.8), height=Inches(0.38),
              fill=None, text_color=None, font_size=Pt(12)):
    """小標籤色塊（用於標示類別）。"""
    add_rect(slide, left, top, width, height,
             fill_color=fill or Theme.MID_BLUE, line_color=None)
    add_textbox(
        slide, text,
        left + Inches(0.06), top + Inches(0.03), width - Inches(0.1), height - Inches(0.05),
        font_size=font_size, font_color=text_color or Theme.WHITE,
        bold=True, align=PP_ALIGN.CENTER
    )


def add_callout_box(slide, title, body_lines, left, top, width, height,
                    title_bg=None, body_bg=None, title_color=None):
    """標題 + 內容的資訊框。"""
    title_h = Inches(0.4)
    add_rect(slide, left, top, width, title_h,
             fill_color=title_bg or Theme.MID_BLUE)
    add_textbox(
        slide, title,
        left + Inches(0.1), top + Inches(0.04), width - Inches(0.2), title_h,
        font_size=Pt(13), font_color=title_color or Theme.WHITE,
        bold=True, align=PP_ALIGN.LEFT
    )
    body_h = height - title_h
    add_rect(slide, left, top + title_h, width, body_h,
             fill_color=body_bg or Theme.LIGHT_GRAY)
    y = top + title_h + Inches(0.1)
    for line in body_lines:
        add_textbox(
            slide, f"  {line}",
            left + Inches(0.08), y, width - Inches(0.18), Inches(0.32),
            font_size=Pt(12), font_color=Theme.DARK_GRAY, align=PP_ALIGN.LEFT
        )
        y += Inches(0.31)


def add_arrow(slide, x1, y1, x2, y2, color=None, width=Pt(2)):
    """在兩點之間畫箭頭連接線。"""
    from pptx.util import Emu
    connector = slide.shapes.add_connector(
        2,  # MSO_CONNECTOR_TYPE.STRAIGHT
        x1, y1, x2, y2
    )
    connector.line.width = width
    connector.line.color.rgb = color or Theme.MID_BLUE
    # 設定終點箭頭
    ln = connector.line._ln
    tail = oxml.parse_xml(
        '<a:tailEnd xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'type="arrow" w="med" len="med"/>'
    )
    ln.append(tail)


# =============================================================================
# 投影片 1：標題頁
# =============================================================================

def slide_01_title(prs):
    layout = prs.slide_layouts[6]  # Blank
    slide = prs.slides.add_slide(layout)

    # 深藍背景
    add_rect(slide, Inches(0), Inches(0), Theme.SLIDE_W, Theme.SLIDE_H,
             fill_color=Theme.DARK_BLUE)

    # 左側橘色邊條
    add_rect(slide, Inches(0), Inches(0), Inches(0.18), Theme.SLIDE_H,
             fill_color=Theme.ORANGE)

    # 主標題
    add_textbox(
        slide,
        "GroundingDINO  vs  YOLO",
        Inches(0.5), Inches(1.5), Inches(12.3), Inches(1.2),
        font_size=Pt(44), font_color=Theme.WHITE, bold=True,
        align=PP_ALIGN.LEFT
    )

    # 副標題
    add_textbox(
        slide,
        "工業生產場景　模型泛化性評估",
        Inches(0.5), Inches(2.7), Inches(12), Inches(0.7),
        font_size=Pt(26), font_color=Theme.LIGHT_BLUE,
        align=PP_ALIGN.LEFT
    )

    # 分隔線（用矩形模擬）
    add_rect(slide, Inches(0.5), Inches(3.55), Inches(9), Inches(0.04),
             fill_color=Theme.ORANGE)

    # 三個場景標籤
    scenarios = [
        "場景一  跨廠區泛化",
        "場景二  機台調整期間",
        "場景三  數據增強測試",
    ]
    for i, s in enumerate(scenarios):
        add_textbox(
            slide, f"  {i+1}.  {s}",
            Inches(0.5), Inches(3.75) + Inches(0.48) * i, Inches(8), Inches(0.42),
            font_size=Pt(16), font_color=Theme.LIGHT_BLUE, align=PP_ALIGN.LEFT
        )

    # 右下角裝飾文字
    add_textbox(
        slide, "Generalization Benchmark",
        Inches(8.5), Inches(6.8), Inches(4.5), Inches(0.4),
        font_size=Pt(11), font_color=Theme.MID_BLUE, italic=True,
        align=PP_ALIGN.RIGHT
    )


# =============================================================================
# 投影片 2：研究背景與動機
# =============================================================================

def slide_02_background(prs):
    layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(layout)
    add_slide_header(slide, "研究背景與動機",
                     "為什麼工業場景的模型泛化性尤其重要？")
    add_slide_footer(slide, 2, 11)

    # 左側：三個痛點
    pain_points = [
        ("跨廠區差異",
         "同一工站部署在不同廠區時，\n因設備批次、廠房光源、安裝角度不同，\n影像品質可能有顯著差異。"),
        ("機台調整頻繁",
         "工程人員在開發或調機階段\n會改變攝影機曝光、焦距或角度，\n導致訓練時與部署時的圖像分布不同。"),
        ("標注成本高",
         "每次場景變化都需要重新標注，\n人力成本昂貴，且容易造成\n標注不一致的品質問題。"),
    ]

    colors = [Theme.MID_BLUE, Theme.ORANGE, Theme.GREEN]
    for i, (title, body) in enumerate(pain_points):
        y = Inches(1.35) + Inches(1.75) * i
        add_rect(slide, Inches(0.35), y, Inches(5.8), Inches(1.6),
                 fill_color=Theme.LIGHT_GRAY)
        add_rect(slide, Inches(0.35), y, Inches(0.12), Inches(1.6),
                 fill_color=colors[i])
        add_textbox(slide, title,
                    Inches(0.6), y + Inches(0.1), Inches(5.4), Inches(0.4),
                    font_size=Pt(16), bold=True, font_color=colors[i])
        add_textbox(slide, body,
                    Inches(0.6), y + Inches(0.48), Inches(5.3), Inches(1.0),
                    font_size=Pt(13), font_color=Theme.DARK_GRAY)

    # 右側：研究問題
    add_rect(slide, Inches(6.5), Inches(1.35), Inches(6.5), Inches(5.8),
             fill_color=Theme.LIGHT_BLUE)
    add_textbox(slide, "核心研究問題",
                Inches(6.7), Inches(1.5), Inches(6.0), Inches(0.5),
                font_size=Pt(18), bold=True, font_color=Theme.DARK_BLUE)

    questions = [
        "在訓練資料不包含目標廠區圖片的情況下，",
        "GroundingDINO 與 YOLO 的泛化能力",
        "各有多強？",
        "",
        "•  哪個模型在未見過的場景中",
        "   更能維持標注精度？",
        "",
        "•  多工站聯合訓練（GroundingDINO）",
        "   vs. 單工站特化訓練（YOLO），",
        "   誰的跨場景泛化性更好？",
        "",
        "•  數據增強能彌補哪個模型的",
        "   哪些短板？",
    ]
    y = Inches(2.1)
    for q in questions:
        add_textbox(slide, q,
                    Inches(6.8), y, Inches(5.8), Inches(0.33),
                    font_size=Pt(12.5), font_color=Theme.DARK_GRAY)
        y += Inches(0.28)


# =============================================================================
# 投影片 3：模型訓練資料設定
# =============================================================================

def slide_03_data_setup(prs):
    layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(layout)
    add_slide_header(slide, "模型訓練資料設定",
                     "YOLO 與 GroundingDINO 的訓練資料來源差異（GL 廠資料）")
    add_slide_footer(slide, 3, 11)

    # ── YOLO 左側 ──
    add_rect(slide, Inches(0.3), Inches(1.25), Inches(5.9), Inches(5.8),
             fill_color=Theme.LIGHT_GRAY)
    add_rect(slide, Inches(0.3), Inches(1.25), Inches(5.9), Inches(0.5),
             fill_color=Theme.MID_BLUE)
    add_textbox(slide, "YOLO　（每工站獨立模型）",
                Inches(0.4), Inches(1.28), Inches(5.7), Inches(0.45),
                font_size=Pt(15), bold=True, font_color=Theme.WHITE)

    yolo_items = [
        "訓練來源：GL 廠  特定工站  資料",
        "模型數量：10 個工站 → 10 個獨立 YOLO 模型",
        "每個模型只見過該工站的圖片",
        "類別：固定於訓練時，不可動態新增",
        "",
        "工站 A  →  YOLO_A  （只認識工站A的物件）",
        "工站 B  →  YOLO_B  （只認識工站B的物件）",
        "   ...          ...",
        "工站 J  →  YOLO_J  （只認識工站J的物件）",
    ]
    y = Inches(1.9)
    for item in yolo_items:
        color = Theme.MID_BLUE if "→" in item else Theme.DARK_GRAY
        bold = "→" in item
        add_textbox(slide, item,
                    Inches(0.5), y, Inches(5.5), Inches(0.33),
                    font_size=Pt(12.5), font_color=color, bold=bold)
        y += Inches(0.31)

    # 未見標記
    add_badge(slide, "❌ 未見其他廠區圖片",
              Inches(0.5), Inches(6.6), width=Inches(3.4), height=Inches(0.38),
              fill=Theme.RED)

    # ── GroundingDINO 右側 ──
    add_rect(slide, Inches(6.8), Inches(1.25), Inches(6.2), Inches(5.8),
             fill_color=Theme.LIGHT_BLUE)
    add_rect(slide, Inches(6.8), Inches(1.25), Inches(6.2), Inches(0.5),
             fill_color=Theme.DARK_BLUE)
    add_textbox(slide, "GroundingDINO　（單一通用模型）",
                Inches(6.9), Inches(1.28), Inches(5.9), Inches(0.45),
                font_size=Pt(15), bold=True, font_color=Theme.WHITE)

    gdino_items = [
        "訓練來源：GL 廠  全部 10 個工站  資料",
        "模型數量：1 個統一模型",
        "見過全部工站的圖片（多樣性更高）",
        "類別：推論時由文字提示動態指定",
        "",
        "工站 A 資料 ┐",
        "工站 B 資料 ┤",
        "   ...      ├──→  GroundingDINO  (1 個模型)",
        "工站 J 資料 ┘",
        "",
        "推論時：\"screw . bolt . glove .\"  →  偵測",
    ]
    y = Inches(1.9)
    for item in gdino_items:
        color = Theme.DARK_BLUE if ("→" in item or "┐" in item or "┤" in item or "┘" in item) else Theme.DARK_GRAY
        bold = "→" in item and "GroundingDINO" in item
        add_textbox(slide, item,
                    Inches(7.0), y, Inches(5.8), Inches(0.33),
                    font_size=Pt(12.5), font_color=color, bold=bold)
        y += Inches(0.31)

    add_badge(slide, "❌ 未見其他廠區圖片",
              Inches(7.0), Inches(6.6), width=Inches(3.4), height=Inches(0.38),
              fill=Theme.RED)
    add_badge(slide, "✓ 訓練多樣性更高",
              Inches(10.6), Inches(6.6), width=Inches(2.2), height=Inches(0.38),
              fill=Theme.GREEN)

    # 中間分隔
    add_rect(slide, Inches(6.35), Inches(1.35), Inches(0.05), Inches(5.7),
             fill_color=Theme.MID_BLUE)
    add_textbox(slide, "vs",
                Inches(6.1), Inches(4.0), Inches(0.55), Inches(0.5),
                font_size=Pt(18), bold=True, font_color=Theme.MID_BLUE,
                align=PP_ALIGN.CENTER)

    # 底部共同說明
    add_rect(slide, Inches(0.3), Inches(7.1), Inches(12.7), Inches(0.28),
             fill_color=Theme.ORANGE)
    add_textbox(
        slide,
        "⚠  兩個模型共同點：均未見過其他廠區的同工站圖片  →  這正是本次評估的「未知測試集」",
        Inches(0.5), Inches(7.1), Inches(12.5), Inches(0.28),
        font_size=Pt(12), font_color=Theme.WHITE, bold=True
    )


# =============================================================================
# 投影片 4：核心架構差異
# =============================================================================

def slide_04_arch_diff(prs):
    layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(layout)
    add_slide_header(slide, "核心架構差異",
                     "開放集（Open-vocabulary） vs 封閉集（Closed-set）")
    add_slide_footer(slide, 4, 11)

    data = [
        ["比較維度", "GroundingDINO", "YOLO"],
        ["偵測類型", "開放集（Open-vocabulary）", "封閉集（Closed-set）"],
        ["類別定義", "推論時文字描述，隨時可改", "訓練時固定，不可動態新增"],
        ["零樣本能力", "強（未訓練類別也能偵測）", "無（未訓練類別 = 看不到）"],
        ["訓練資料需求", "不需要（可直接零樣本使用）", "需要標注資料才能訓練"],
        ["新增類別成本", "改文字提示，零成本", "重新收集、標注、訓練"],
        ["推論速度", "慢（Swin-T + BERT 雙編碼器）", "快（10~100x 快於 GroundingDINO）"],
        ["模型大小", "大（~172MB~800MB+）", "小（YOLOv8n ~6MB）"],
        ["邊緣設備部署", "困難", "容易（Jetson、工控機）"],
        ["多工站共用", "單一模型，文字切換工站", "每工站需一個獨立模型"],
    ]

    col_widths = [Inches(2.8), Inches(4.8), Inches(4.8)]
    add_table(slide, data, col_widths,
              left=Inches(0.4), top=Inches(1.25),
              row_height=Inches(0.46),
              font_size=Pt(12), header_font_size=Pt(14))

    # 底部結論
    add_rect(slide, Inches(0.4), Inches(6.85), Inches(12.5), Inches(0.35),
             fill_color=Theme.LIGHT_BLUE)
    add_textbox(
        slide,
        "本評估聚焦於：在相同訓練資料量的公平前提下，多樣性（多工站）vs. 專一性（單工站）誰的跨場景泛化性更佳？",
        Inches(0.55), Inches(6.88), Inches(12.2), Inches(0.3),
        font_size=Pt(12), font_color=Theme.DARK_BLUE, bold=True
    )


# =============================================================================
# 投影片 5：評估場景一
# =============================================================================

def slide_05_scenario1(prs):
    layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(layout)
    add_slide_header(slide, "評估場景一：跨廠區泛化",
                     "同工站，不同廠區 — 兩個模型都未見過目標廠區圖片")
    add_slide_footer(slide, 5, 11)

    add_badge(slide, "SCENARIO 1",
              Inches(11.8), Inches(0.2), width=Inches(1.3), height=Inches(0.32),
              fill=Theme.ORANGE, font_size=Pt(10))

    # 場景說明
    add_textbox(slide, "場景描述",
                Inches(0.4), Inches(1.3), Inches(5), Inches(0.38),
                font_size=Pt(16), bold=True, font_color=Theme.DARK_BLUE)

    desc_lines = [
        "同一工站（相同類別、相似作業流程）",
        "部署在不同廠區，因環境差異導致：",
        "",
        "  •  曝光不同（廠房燈光強弱）",
        "  •  拍攝角度略有偏差（安裝誤差）",
        "  •  背景色調、材質紋理有差異",
        "  •  相機型號或鏡頭焦段不同",
    ]
    y = Inches(1.75)
    for line in desc_lines:
        add_textbox(slide, line,
                    Inches(0.4), y, Inches(5.5), Inches(0.33),
                    font_size=Pt(13), font_color=Theme.DARK_GRAY)
        y += Inches(0.3)

    # 訓練/測試分割說明
    add_textbox(slide, "訓練 / 測試 資料分割",
                Inches(0.4), Inches(4.05), Inches(5.5), Inches(0.38),
                font_size=Pt(16), bold=True, font_color=Theme.DARK_BLUE)

    split_data = [
        ["", "訓練集", "測試集"],
        ["YOLO",           "GL 廠 特定工站", "其他廠區 同工站"],
        ["GroundingDINO",  "GL 廠 全部工站", "其他廠區 同工站"],
    ]
    add_table(slide, split_data,
              col_widths=[Inches(1.8), Inches(1.9), Inches(1.9)],
              left=Inches(0.4), top=Inches(4.5),
              row_height=Inches(0.42), font_size=Pt(12))

    # 右側：預期挑戰圖
    add_rect(slide, Inches(6.5), Inches(1.25), Inches(6.5), Inches(5.85),
             fill_color=Theme.LIGHT_BLUE)
    add_textbox(slide, "預期挑戰與假設",
                Inches(6.7), Inches(1.35), Inches(6.0), Inches(0.4),
                font_size=Pt(16), bold=True, font_color=Theme.DARK_BLUE)

    hypotheses = [
        ("GroundingDINO 預期較佳", Theme.GREEN,
         "訓練資料包含 10 個工站的多樣圖像，\n見過更廣泛的光源與角度分布，\n泛化性理論上更強。"),
        ("YOLO 預期較弱", Theme.ORANGE,
         "每個 YOLO 只見過 GL 廠特定工站，\n對同工站在不同廠區的外觀差異\n沒有直接訓練訊號。"),
        ("關鍵觀測指標", Theme.MID_BLUE,
         "mAP 下降幅度（相對 GL 廠內測試）\n→ 下降越少代表泛化越強。"),
    ]
    y = Inches(1.85)
    for title, color, body in hypotheses:
        add_rect(slide, Inches(6.6), y, Inches(6.1), Inches(1.4),
                 fill_color=Theme.WHITE)
        add_rect(slide, Inches(6.6), y, Inches(0.12), Inches(1.4),
                 fill_color=color)
        add_textbox(slide, title,
                    Inches(6.85), y + Inches(0.08), Inches(5.7), Inches(0.38),
                    font_size=Pt(14), bold=True, font_color=color)
        add_textbox(slide, body,
                    Inches(6.85), y + Inches(0.44), Inches(5.7), Inches(0.85),
                    font_size=Pt(12), font_color=Theme.DARK_GRAY)
        y += Inches(1.55)


# =============================================================================
# 投影片 6：評估場景二
# =============================================================================

def slide_06_scenario2(prs):
    layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(layout)
    add_slide_header(slide, "評估場景二：機台調整期間",
                     "工程人員調機導致成像參數改變 — 模擬實際開發生命週期")
    add_slide_footer(slide, 6, 11)

    add_badge(slide, "SCENARIO 2",
              Inches(11.8), Inches(0.2), width=Inches(1.3), height=Inches(0.32),
              fill=Theme.MID_BLUE, font_size=Pt(10))

    # 左側：機台調整類型
    add_textbox(slide, "典型機台調整類型",
                Inches(0.4), Inches(1.3), Inches(6), Inches(0.4),
                font_size=Pt(16), bold=True, font_color=Theme.DARK_BLUE)

    adjustment_types = [
        ("曝光調整",   "因生產環境燈光改變或\n感測器老化，調整相機 EV 值"),
        ("角度微調",   "重新固定攝影機支架後\n產生的角度偏移（通常 < 5°）"),
        ("焦距變化",   "更換鏡頭或調整焦段，\n導致物件大小比例改變"),
        ("白平衡漂移", "不同時間段的色溫差異\n造成影像色調偏移"),
    ]

    y = Inches(1.8)
    for i, (t, d) in enumerate(adjustment_types):
        col = [Theme.MID_BLUE, Theme.ORANGE, Theme.GREEN, Theme.DARK_BLUE][i]
        add_rect(slide, Inches(0.4), y, Inches(2.9), Inches(1.1),
                 fill_color=Theme.LIGHT_GRAY)
        add_rect(slide, Inches(0.4), y, Inches(0.08), Inches(1.1), fill_color=col)
        add_textbox(slide, t,
                    Inches(0.58), y + Inches(0.05), Inches(2.6), Inches(0.35),
                    font_size=Pt(13), bold=True, font_color=col)
        add_textbox(slide, d,
                    Inches(0.58), y + Inches(0.38), Inches(2.6), Inches(0.65),
                    font_size=Pt(11.5), font_color=Theme.DARK_GRAY)
        if i % 2 == 0:
            next_x = Inches(3.5)
            next_y = y
        else:
            next_x = Inches(0.4)
            next_y = y + Inches(1.25)
        if i % 2 == 0:
            y_next_col = y
        y = next_y if i % 2 != 0 else y
        if i == 0:
            second_left = Inches(3.5)
        if i % 2 == 0 and i > 0:
            pass

    # 重新繪製（2x2 排列）
    for shape in list(slide.shapes):
        if hasattr(shape, 'text') and shape.text in [t for t, _ in adjustment_types]:
            pass

    # 用更簡單的方式重繪 2x2 佈局
    positions = [
        (Inches(0.4),  Inches(1.8)),
        (Inches(3.55), Inches(1.8)),
        (Inches(0.4),  Inches(3.15)),
        (Inches(3.55), Inches(3.15)),
    ]
    # 先刪除上方繪製的，改用下方的版本（直接用 positions 繪製）
    # 注意：pptx 無法刪除已加入的 shape，直接在正確位置繪製
    colors2 = [Theme.MID_BLUE, Theme.ORANGE, Theme.GREEN, Theme.DARK_BLUE]
    for i, (ax, ay) in enumerate(positions):
        t, d = adjustment_types[i]
        col = colors2[i]
        add_rect(slide, ax + Inches(3.2), ay, Inches(2.9), Inches(1.1),
                 fill_color=Theme.WHITE)  # 覆蓋前面的多餘繪圖

    # 清潔版本：重新在固定位置繪製 4 個方塊
    for i, (ax, ay) in enumerate(positions):
        t, d = adjustment_types[i]
        col = colors2[i]
        add_rect(slide, ax, ay, Inches(2.9), Inches(1.1), fill_color=Theme.LIGHT_GRAY)
        add_rect(slide, ax, ay, Inches(0.08), Inches(1.1), fill_color=col)
        add_textbox(slide, t, ax + Inches(0.15), ay + Inches(0.08),
                    Inches(2.6), Inches(0.35), font_size=Pt(13), bold=True, font_color=col)
        add_textbox(slide, d, ax + Inches(0.15), ay + Inches(0.44),
                    Inches(2.6), Inches(0.65), font_size=Pt(11.5), font_color=Theme.DARK_GRAY)

    # 右側：評估設計
    add_rect(slide, Inches(6.8), Inches(1.25), Inches(6.2), Inches(5.85),
             fill_color=Theme.LIGHT_GRAY)
    add_textbox(slide, "評估設計",
                Inches(7.0), Inches(1.35), Inches(5.8), Inches(0.4),
                font_size=Pt(16), bold=True, font_color=Theme.DARK_BLUE)

    eval_steps = [
        ("① 基準測試",
         "用 GL 廠原始圖片測試兩個模型\n取得 baseline mAP 作為參考"),
        ("② 調機後測試",
         "用調機後的圖片（曝光 ±2EV、\n角度 ±5°）重新測試兩個模型"),
        ("③ 計算衰退率",
         "衰退率 = (baseline − post) / baseline\n→ 值越小代表模型越穩健"),
        ("④ 分析原因",
         "哪種調整類型對哪個模型\n影響最大？是否有規律可循？"),
    ]
    y = Inches(1.85)
    for step_title, step_body in eval_steps:
        add_rect(slide, Inches(6.9), y, Inches(5.8), Inches(1.1),
                 fill_color=Theme.WHITE)
        add_textbox(slide, step_title,
                    Inches(7.05), y + Inches(0.08), Inches(5.5), Inches(0.38),
                    font_size=Pt(13), bold=True, font_color=Theme.DARK_BLUE)
        add_textbox(slide, step_body,
                    Inches(7.05), y + Inches(0.45), Inches(5.5), Inches(0.6),
                    font_size=Pt(12), font_color=Theme.DARK_GRAY)
        y += Inches(1.2)

    # 底部說明
    add_rect(slide, Inches(0.4), Inches(4.55), Inches(6.1), Inches(0.55),
             fill_color=Theme.LIGHT_BLUE)
    add_textbox(slide,
                "此場景特殊性：模型在「開發期間」就必須穩定工作，\n不能每次調機就需要重新訓練。",
                Inches(0.55), Inches(4.58), Inches(5.8), Inches(0.5),
                font_size=Pt(12), font_color=Theme.DARK_BLUE)


# =============================================================================
# 投影片 7：評估場景三
# =============================================================================

def slide_07_scenario3(prs):
    layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(layout)
    add_slide_header(slide, "評估場景三：數據增強測試",
                     "使用現有資料集進行增強 — 測試模型對圖像變化的魯棒性")
    add_slide_footer(slide, 7, 11)

    add_badge(slide, "SCENARIO 3",
              Inches(11.8), Inches(0.2), width=Inches(1.3), height=Inches(0.32),
              fill=Theme.GREEN, font_size=Pt(10))

    # 增強方式列表（3x2 排列）
    aug_methods = [
        ("旋轉",       "±15° / ±30° / ±45°",      Theme.MID_BLUE),
        ("平移",       "水平 / 垂直  ±10%~20%",    Theme.ORANGE),
        ("縮放",       "0.7x ~ 1.3x（含裁切）",    Theme.GREEN),
        ("對比度調整", "±30%（Contrast）",           Theme.DARK_BLUE),
        ("亮度調整",   "±20%（Brightness / EV）",   Theme.MID_BLUE),
        ("複合增強",   "旋轉 + 縮放 + 亮度 同時",  Theme.ORANGE),
    ]

    add_textbox(slide, "六種增強方式",
                Inches(0.4), Inches(1.25), Inches(6), Inches(0.4),
                font_size=Pt(16), bold=True, font_color=Theme.DARK_BLUE)

    positions_3 = [
        (Inches(0.35),  Inches(1.75)),
        (Inches(3.25),  Inches(1.75)),
        (Inches(0.35),  Inches(2.9)),
        (Inches(3.25),  Inches(2.9)),
        (Inches(0.35),  Inches(4.05)),
        (Inches(3.25),  Inches(4.05)),
    ]
    for (ax, ay), (title, param, color) in zip(positions_3, aug_methods):
        add_rect(slide, ax, ay, Inches(2.7), Inches(0.95), fill_color=Theme.LIGHT_GRAY)
        add_rect(slide, ax, ay, Inches(0.08), Inches(0.95), fill_color=color)
        add_textbox(slide, title,
                    ax + Inches(0.14), ay + Inches(0.06), Inches(2.45), Inches(0.32),
                    font_size=Pt(13), bold=True, font_color=color)
        add_textbox(slide, param,
                    ax + Inches(0.14), ay + Inches(0.42), Inches(2.45), Inches(0.45),
                    font_size=Pt(12), font_color=Theme.DARK_GRAY)

    # 增強目的說明
    add_rect(slide, Inches(0.35), Inches(5.2), Inches(6.0), Inches(1.0),
             fill_color=Theme.LIGHT_BLUE)
    add_textbox(slide, "此場景的評估目的",
                Inches(0.5), Inches(5.25), Inches(5.7), Inches(0.35),
                font_size=Pt(14), bold=True, font_color=Theme.DARK_BLUE)
    add_textbox(slide,
                "以可控方式模擬場景一、二的圖像變化，\n量化每種增強對兩個模型精度的影響程度。",
                Inches(0.5), Inches(5.62), Inches(5.7), Inches(0.55),
                font_size=Pt(12.5), font_color=Theme.DARK_GRAY)

    # 右側：評估矩陣
    add_rect(slide, Inches(6.8), Inches(1.25), Inches(6.2), Inches(5.85),
             fill_color=Theme.LIGHT_GRAY)
    add_textbox(slide, "預期差異分析",
                Inches(7.0), Inches(1.35), Inches(5.8), Inches(0.4),
                font_size=Pt(16), bold=True, font_color=Theme.DARK_BLUE)

    aug_analysis = [
        ("旋轉 / 平移 / 縮放",
         "YOLO：在訓練時通常已加入這三類增強，\n預期較為穩健。\n"
         "GroundingDINO：預訓練多樣性高，但對\n工業特定角度的旋轉仍可能下降。"),
        ("曝光 / 亮度 / 對比度",
         "GroundingDINO：預訓練資料包含大量\n不同光線條件，預期較強。\n"
         "YOLO：GL 廠資料光線條件相對固定，\n對大幅光線變化可能較敏感。"),
        ("複合增強",
         "最接近真實場景（機台調整 = 多種變化同時發生）。\n"
         "兩個模型的衰退程度差距在此最為顯著。"),
    ]
    y = Inches(1.85)
    for title, body in aug_analysis:
        add_rect(slide, Inches(6.9), y, Inches(5.8), Inches(1.5),
                 fill_color=Theme.WHITE)
        add_textbox(slide, title,
                    Inches(7.05), y + Inches(0.08), Inches(5.5), Inches(0.38),
                    font_size=Pt(13), bold=True, font_color=Theme.DARK_BLUE)
        add_textbox(slide, body,
                    Inches(7.05), y + Inches(0.45), Inches(5.5), Inches(1.0),
                    font_size=Pt(11.5), font_color=Theme.DARK_GRAY)
        y += Inches(1.65)


# =============================================================================
# 投影片 8：實驗設計對照矩陣
# =============================================================================

def slide_08_experiment_matrix(prs):
    layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(layout)
    add_slide_header(slide, "實驗設計對照矩陣",
                     "三個場景 × 兩個模型的完整評估框架")
    add_slide_footer(slide, 8, 11)

    data = [
        ["評估維度",          "場景一  跨廠區泛化",       "場景二  機台調整",          "場景三  數據增強"],
        ["測試資料來源",      "其他廠區同工站圖片",        "調機前後的同工站圖片",      "GL廠圖片 + 增強版本"],
        ["兩模型是否見過",    "❌ 均未見過",               "❌ 均未見過調機後版本",     "⚠ 部分增強類型已見"],
        ["YOLO 預期表現",     "中等（單廠資料有限）",      "隨調整類型不同而有差異",    "旋轉/縮放強，光線弱"],
        ["GroundingDINO 預期","較佳（多工站多樣性）",      "光線變化強，角度變化中等",  "光線強，旋轉視情況"],
        ["核心觀測指標",      "跨廠 mAP 下降幅度",         "調機前後 mAP 衰退率",       "各增強類型獨立 mAP"],
        ["預期勝出模型",      "GroundingDINO",             "視調整類型而定",            "視增強類型而定"],
    ]

    col_widths = [Inches(2.5), Inches(3.3), Inches(3.3), Inches(3.3)]
    add_table(slide, data, col_widths,
              left=Inches(0.35), top=Inches(1.28),
              row_height=Inches(0.53),
              font_size=Pt(11), header_font_size=Pt(13))

    # 底部說明
    add_rect(slide, Inches(0.35), Inches(6.85), Inches(12.6), Inches(0.35),
             fill_color=Theme.LIGHT_BLUE)
    add_textbox(
        slide,
        "公平性保證：三個場景的測試集對兩個模型均為完全未見過的資料，確保評估具有可比性。",
        Inches(0.5), Inches(6.88), Inches(12.3), Inches(0.3),
        font_size=Pt(12), font_color=Theme.DARK_BLUE, bold=True
    )


# =============================================================================
# 投影片 9：評估指標定義
# =============================================================================

def slide_09_metrics(prs):
    layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(layout)
    add_slide_header(slide, "評估指標定義",
                     "量化標準：確保跨場景、跨模型的可比性")
    add_slide_footer(slide, 9, 11)

    # 主要指標（左側）
    add_textbox(slide, "主要評估指標",
                Inches(0.4), Inches(1.28), Inches(6), Inches(0.4),
                font_size=Pt(16), bold=True, font_color=Theme.DARK_BLUE)

    metrics = [
        ("mAP@0.5",
         "平均精確率（Mean Average Precision）",
         "IoU 閾值 0.5 下各類別 AP 的平均值，\n核心比較指標。"),
        ("mAP@0.5:0.95",
         "嚴格版 mAP（COCO 標準）",
         "IoU 從 0.5 到 0.95 取平均，\n反映模型的框定位精度。"),
        ("Precision",
         "精確率",
         "預測為正的樣本中，真正為正的比例。\n越高代表誤報越少。"),
        ("Recall",
         "召回率",
         "所有真正為正的樣本中，被正確偵測的比例。\n越高代表漏報越少。"),
    ]
    y = Inches(1.78)
    colors3 = [Theme.MID_BLUE, Theme.DARK_BLUE, Theme.GREEN, Theme.ORANGE]
    for (short, full, desc), color in zip(metrics, colors3):
        add_rect(slide, Inches(0.4), y, Inches(6.0), Inches(1.1),
                 fill_color=Theme.LIGHT_GRAY)
        add_rect(slide, Inches(0.4), y, Inches(0.1), Inches(1.1), fill_color=color)
        add_textbox(slide, short,
                    Inches(0.6), y + Inches(0.06), Inches(1.5), Inches(0.38),
                    font_size=Pt(16), bold=True, font_color=color)
        add_textbox(slide, full,
                    Inches(2.1), y + Inches(0.1), Inches(4.1), Inches(0.38),
                    font_size=Pt(13), bold=True, font_color=Theme.DARK_GRAY)
        add_textbox(slide, desc,
                    Inches(0.6), y + Inches(0.5), Inches(5.7), Inches(0.55),
                    font_size=Pt(11.5), font_color=Theme.DARK_GRAY)
        y += Inches(1.22)

    # 右側：衍生指標
    add_rect(slide, Inches(6.8), Inches(1.25), Inches(6.2), Inches(5.85),
             fill_color=Theme.LIGHT_BLUE)
    add_textbox(slide, "衍生泛化指標",
                Inches(7.0), Inches(1.35), Inches(5.8), Inches(0.4),
                font_size=Pt(16), bold=True, font_color=Theme.DARK_BLUE)

    derived = [
        ("泛化衰退率",
         "Δ mAP = mAP(in-domain) − mAP(out-domain)\n"
         "值越小 → 泛化性越強\n"
         "用於場景一、二的主要比較指標"),
        ("相對衰退率",
         "Δ% = Δ mAP / mAP(in-domain) × 100%\n"
         "排除兩模型基準線差異，\n更公平地比較泛化能力"),
        ("增強魯棒性指數",
         "Robustness = mAP(augmented) / mAP(original)\n"
         "值越接近 1.0 → 對該增強越穩健\n"
         "用於場景三各增強類型比較"),
    ]
    y = Inches(1.85)
    for title, body in derived:
        add_rect(slide, Inches(6.9), y, Inches(5.8), Inches(1.55),
                 fill_color=Theme.WHITE)
        add_textbox(slide, title,
                    Inches(7.05), y + Inches(0.08), Inches(5.5), Inches(0.38),
                    font_size=Pt(14), bold=True, font_color=Theme.DARK_BLUE)
        add_textbox(slide, body,
                    Inches(7.05), y + Inches(0.48), Inches(5.5), Inches(1.0),
                    font_size=Pt(12), font_color=Theme.DARK_GRAY,
                    font_name=Theme.FONT_MONO)
        y += Inches(1.72)


# =============================================================================
# 投影片 10：預期假設
# =============================================================================

def slide_10_hypotheses(prs):
    layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(layout)
    add_slide_header(slide, "預期假設與研究價值",
                     "基於模型架構與訓練資料差異的先驗推斷")
    add_slide_footer(slide, 10, 11)

    # 主假設表格
    data_h = [
        ["場景",       "假設",                                    "理由",                            "驗證方式"],
        ["場景一\n跨廠區",
         "GroundingDINO\n泛化衰退率較低",
         "訓練資料包含10個工站的\n多樣光線/角度，分布更廣",
         "Δ% 比較\n（兩模型各自\nvs 廠內測試）"],
        ["場景二\n機台調整",
         "曝光類：GroundingDINO 較強\n角度類：YOLO 有增強加持",
         "GroundingDINO預訓練光線多樣；\nYOLO 訓練時常加入幾何增強",
         "分類型測試\n各自的衰退率"],
        ["場景三\n數據增強",
         "複合增強下\nGroundingDINO 優勢最明顯",
         "多工站訓練 ≈ 天然的\n多樣化增強效果",
         "增強魯棒性指數\n各類型比較"],
    ]

    col_widths_h = [Inches(1.5), Inches(3.0), Inches(4.5), Inches(4.0)]
    add_table(slide, data_h, col_widths_h,
              left=Inches(0.35), top=Inches(1.28),
              row_height=Inches(0.72),
              font_size=Pt(11), header_font_size=Pt(13))

    # 研究價值
    add_rect(slide, Inches(0.35), Inches(4.85), Inches(12.6), Inches(2.35),
             fill_color=Theme.LIGHT_BLUE)
    add_textbox(slide, "研究價值與實際意義",
                Inches(0.55), Inches(4.92), Inches(12), Inches(0.4),
                font_size=Pt(15), bold=True, font_color=Theme.DARK_BLUE)

    values = [
        "✓  量化「多工站聯合訓練」vs「單工站特化訓練」的跨廠泛化差距，提供模型選型依據",
        "✓  找出 YOLO 與 GroundingDINO 各自對哪種圖像變化最敏感，指導資料收集策略",
        "✓  評估現有標注資料在不重新採集的情況下，能透過增強覆蓋多少現實場景變化",
        "✓  建立可重複使用的評估 pipeline，供後續新工站、新廠區上線時快速驗證",
    ]
    y = Inches(5.42)
    for v in values:
        add_textbox(slide, v,
                    Inches(0.6), y, Inches(12.1), Inches(0.35),
                    font_size=Pt(12.5), font_color=Theme.DARK_GRAY)
        y += Inches(0.38)


# =============================================================================
# 投影片 11：結論與下一步
# =============================================================================

def slide_11_conclusion(prs):
    layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(layout)
    add_slide_header(slide, "結論與下一步",
                     "評估完成後的行動建議")
    add_slide_footer(slide, 11, 11)

    # 左側：決策矩陣
    add_textbox(slide, "模型選用決策矩陣",
                Inches(0.4), Inches(1.28), Inches(6), Inches(0.4),
                font_size=Pt(16), bold=True, font_color=Theme.DARK_BLUE)

    decision_data = [
        ["使用場景",               "建議模型"],
        ["全新工站冷啟動",         "GroundingDINO"],
        ["跨廠區泛化需求高",       "GroundingDINO"],
        ["類別固定、速度優先",     "YOLO"],
        ["部署到邊緣設備",         "YOLO"],
        ["機台調整後快速適應",     "GroundingDINO（光線）\nYOLO（角度）"],
        ["多工站統一服務",         "GroundingDINO"],
    ]
    add_table(slide, decision_data,
              col_widths=[Inches(3.2), Inches(2.9)],
              left=Inches(0.4), top=Inches(1.75),
              row_height=Inches(0.48),
              font_size=Pt(12))

    # 右側：下一步行動
    add_rect(slide, Inches(6.8), Inches(1.25), Inches(6.2), Inches(5.85),
             fill_color=Theme.LIGHT_GRAY)
    add_textbox(slide, "下一步行動計畫",
                Inches(7.0), Inches(1.35), Inches(5.8), Inches(0.4),
                font_size=Pt(16), bold=True, font_color=Theme.DARK_BLUE)

    next_steps = [
        ("短期（立即可執行）",  Theme.GREEN, [
            "用現有 GL 廠資料執行場景三（增強測試）",
            "評估兩個模型的增強魯棒性基準",
            "找出各自的弱點增強類型",
        ]),
        ("中期（收集新資料後）", Theme.ORANGE, [
            "收集其他廠區同工站圖片作為測試集",
            "執行場景一（跨廠區泛化）評估",
            "根據結果調整訓練資料多樣性策略",
        ]),
        ("長期（迭代優化）",     Theme.MID_BLUE, [
            "建立持續評估 pipeline（CI/CD 式）",
            "新工站 / 新廠區自動觸發泛化評估",
            "根據評估結果動態決定標注優先級",
        ]),
    ]
    y = Inches(1.85)
    for phase, color, items in next_steps:
        add_rect(slide, Inches(6.9), y, Inches(5.8), Inches(0.35),
                 fill_color=color)
        add_textbox(slide, phase,
                    Inches(7.0), y + Inches(0.03), Inches(5.6), Inches(0.3),
                    font_size=Pt(13), bold=True, font_color=Theme.WHITE)
        y += Inches(0.38)
        for item in items:
            add_textbox(slide, f"  •  {item}",
                        Inches(6.9), y, Inches(5.8), Inches(0.32),
                        font_size=Pt(12), font_color=Theme.DARK_GRAY)
            y += Inches(0.3)
        y += Inches(0.12)

    # 最終結論
    add_rect(slide, Inches(0.35), Inches(6.82), Inches(12.6), Inches(0.4),
             fill_color=Theme.DARK_BLUE)
    add_textbox(
        slide,
        "核心結論：GroundingDINO 是「泛化性更強的探索者」，YOLO 是「效率更高的執行者」— 兩者分工互補，缺一不可。",
        Inches(0.5), Inches(6.85), Inches(12.3), Inches(0.35),
        font_size=Pt(12.5), font_color=Theme.WHITE, bold=True
    )


# =============================================================================
# 主程式
# =============================================================================

def generate(output_path: str = "output/evaluation_report.pptx"):
    prs = Presentation()
    prs.slide_width  = Theme.SLIDE_W
    prs.slide_height = Theme.SLIDE_H

    print("[PPT] 開始生成投影片...")

    slide_01_title(prs);              print("  ✓ Slide  1 / 11  標題頁")
    slide_02_background(prs);        print("  ✓ Slide  2 / 11  研究背景")
    slide_03_data_setup(prs);        print("  ✓ Slide  3 / 11  訓練資料設定")
    slide_04_arch_diff(prs);         print("  ✓ Slide  4 / 11  核心架構差異")
    slide_05_scenario1(prs);         print("  ✓ Slide  5 / 11  場景一：跨廠區")
    slide_06_scenario2(prs);         print("  ✓ Slide  6 / 11  場景二：機台調整")
    slide_07_scenario3(prs);         print("  ✓ Slide  7 / 11  場景三：數據增強")
    slide_08_experiment_matrix(prs); print("  ✓ Slide  8 / 11  實驗設計矩陣")
    slide_09_metrics(prs);           print("  ✓ Slide  9 / 11  評估指標")
    slide_10_hypotheses(prs);        print("  ✓ Slide 10 / 11  預期假設")
    slide_11_conclusion(prs);        print("  ✓ Slide 11 / 11  結論與下一步")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    prs.save(output_path)
    print(f"\n[完成] 已儲存：{output_path}")
    print(f"[提示] 使用 PowerPoint 或 LibreOffice Impress 開啟。")


def main():
    parser = argparse.ArgumentParser(
        description="生成 GroundingDINO vs YOLO 泛化性評估 PPT"
    )
    parser.add_argument(
        "--output", "-o",
        default="output/evaluation_report.pptx",
        help="輸出路徑（預設：output/evaluation_report.pptx）"
    )
    args = parser.parse_args()
    generate(args.output)


if __name__ == "__main__":
    main()
