"""Generate docs/RS232_Tap_Wiring.pdf: passive two-direction RS-232 tap guide.

    python docs/make_wiring_pdf.py
"""

from pathlib import Path

from reportlab.graphics.shapes import Drawing, Line, PolyLine, Rect, String, Circle
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

OUT = Path(__file__).with_name("RS232_Tap_Wiring.pdf")
FONTS = Path("C:/Windows/Fonts")
pdfmetrics.registerFont(TTFont("Arial", FONTS / "arial.ttf"))
pdfmetrics.registerFont(TTFont("Arial-Bold", FONTS / "arialbd.ttf"))
pdfmetrics.registerFont(TTFont("Arial-Italic", FONTS / "ariali.ttf"))
pdfmetrics.registerFont(TTFont("Mono", FONTS / "consola.ttf"))
pdfmetrics.registerFont(TTFont("Mono-Bold", FONTS / "consolab.ttf"))
pdfmetrics.registerFontFamily("Arial", normal="Arial", bold="Arial-Bold", italic="Arial-Italic")

# Palette
INK = colors.HexColor("#1F2937")
MUTED = colors.HexColor("#6B7280")
LINE = colors.HexColor("#D1D5DB")
PANEL = colors.HexColor("#F3F4F6")
ACCENT = colors.HexColor("#1D4ED8")
TX_PC = colors.HexColor("#2563EB")    # PC -> controller
TX_CTRL = colors.HexColor("#059669")  # controller -> PC
GND = colors.HexColor("#111827")
OPT_A = colors.HexColor("#D97706")
OPT_B = colors.HexColor("#7C3AED")
DANGER = colors.HexColor("#DC2626")
DANGER_BG = colors.HexColor("#FEF2F2")
WARN_BG = colors.HexColor("#FFFBEB")

W = A4[0] - 40 * mm  # usable width

ss = {
    "title": ParagraphStyle("title", fontName="Arial-Bold", fontSize=20, leading=24, textColor=INK),
    "subtitle": ParagraphStyle("subtitle", fontName="Arial", fontSize=10.5, leading=14, textColor=MUTED),
    "h1": ParagraphStyle("h1", fontName="Arial-Bold", fontSize=14, leading=18, textColor=INK,
                         spaceBefore=10, spaceAfter=6),
    "h2": ParagraphStyle("h2", fontName="Arial-Bold", fontSize=11, leading=14, textColor=INK,
                         spaceBefore=8, spaceAfter=4),
    "body": ParagraphStyle("body", fontName="Arial", fontSize=9.5, leading=13, textColor=INK),
    "small": ParagraphStyle("small", fontName="Arial", fontSize=8.5, leading=11, textColor=INK),
    "muted": ParagraphStyle("muted", fontName="Arial", fontSize=8.5, leading=11, textColor=MUTED),
    "cell": ParagraphStyle("cell", fontName="Arial", fontSize=8.5, leading=11, textColor=INK, alignment=TA_LEFT),
    "cellb": ParagraphStyle("cellb", fontName="Arial-Bold", fontSize=8.5, leading=11, textColor=INK),
    "code": ParagraphStyle("code", fontName="Mono", fontSize=8.5, leading=11.5, textColor=INK),
}


def P(text, style="body"):
    return Paragraph(text, ss[style])


def table(rows, widths, header=True, zebra=True, extra=()):
    data = [[c if not isinstance(c, str) else P(c, "cellb" if header and i == 0 else "cell")
             for c in row] for i, row in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), PANEL), ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK)]
    t.setStyle(TableStyle(style + list(extra)))
    return t


def callout(text, bg=WARN_BG, edge=OPT_A):
    t = Table([[P(text, "small")]], colWidths=[W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("LINEBEFORE", (0, 0), (0, -1), 3, edge),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


# ---------------------------------------------------------------- drawings

def box(d, x, y, w, h, title, lines=(), fill=colors.white, stroke=INK, bold_color=INK):
    d.add(Rect(x, y, w, h, rx=4, ry=4, fillColor=fill, strokeColor=stroke, strokeWidth=1))
    d.add(String(x + w / 2, y + h - 13, title, fontName="Arial-Bold", fontSize=9,
                 fillColor=bold_color, textAnchor="middle"))
    for i, line in enumerate(lines):
        d.add(String(x + w / 2, y + h - 25 - i * 10, line, fontName="Arial", fontSize=7.5,
                     fillColor=MUTED, textAnchor="middle"))


def label(d, x, y, text, size=7.5, color=MUTED, anchor="middle", font="Arial"):
    d.add(String(x, y, text, fontName=font, fontSize=size, fillColor=color, textAnchor=anchor))


def overview():
    d = Drawing(W, 395)
    cx = W / 2
    bw, bh = 112, 46

    # Row 1: PC - Y - Controller
    y1 = 330
    box(d, 0, y1, bw, bh + 6, "Old PC (Proteus)", ["Win9x, onboard COM port", "DB9 MALE"])
    box(d, cx - 56, y1, 112, bh + 6, "Y-cable", ["1× male, 2× female", "straight, all 9 pins"],
        fill=PANEL)
    box(d, W - bw, y1, bw, bh + 6, "DigiMaxx C-20", ["via existing cable", "cable end: DB9 FEMALE"])
    d.add(Line(bw, y1 + 26, cx - 56, y1 + 26, strokeColor=INK, strokeWidth=1.4))
    label(d, (bw + cx - 56) / 2, y1 + 31, "Y female #1")
    label(d, (bw + cx - 56) / 2, y1 + 14, "on PC COM port")
    d.add(Line(cx + 56, y1 + 26, W - bw, y1 + 26, strokeColor=INK, strokeWidth=1.4))
    label(d, (cx + 56 + W - bw) / 2, y1 + 31, "Y male end")
    label(d, (cx + 56 + W - bw) / 2, y1 + 14, "← controller cable")

    # Row 2: male terminal board
    y2 = 245
    d.add(Line(cx, y1, cx, y2 + bh, strokeColor=INK, strokeWidth=1.4))
    label(d, cx + 5, y2 + bh + 16, "Y female #2", anchor="start")
    box(d, cx - 75, y2, 150, bh, "MALE DB9 terminal board", ["the tap point (screw terminals)"],
        fill=colors.HexColor("#EFF6FF"), stroke=ACCENT)

    # Row 3: female boards
    y3 = 150
    ax, bx = 20, W - 20 - 150
    box(d, ax, y3, 150, bh, "FEMALE board A", ["gets line pin 3 + GND"], stroke=TX_PC)
    box(d, bx, y3, 150, bh, "FEMALE board B", ["gets line pin 2 + GND"], stroke=TX_CTRL)
    d.add(PolyLine([cx - 30, y2, cx - 30, y3 + bh + 20, ax + 75, y3 + bh + 20, ax + 75, y3 + bh],
                   strokeColor=TX_PC, strokeWidth=1.4))
    d.add(PolyLine([cx + 30, y2, cx + 30, y3 + bh + 20, bx + 75, y3 + bh + 20, bx + 75, y3 + bh],
                   strokeColor=TX_CTRL, strokeWidth=1.4))
    label(d, (cx - 30 + ax + 75) / 2, y3 + bh + 24, "wires: pin 3, GND", color=TX_PC)
    label(d, (cx + 30 + bx + 75) / 2, y3 + bh + 24, "wires: pin 2, GND", color=TX_CTRL)

    # Row 4: Digitus adapters
    y4 = 70
    box(d, ax, y4, 150, bh, "Digitus DA-70156  A", ["FTDI FT232RL · e.g. COM5", "hears PC → controller"])
    box(d, bx, y4, 150, bh, "Digitus DA-70156  B", ["FTDI FT232RL · e.g. COM6", "hears controller → PC"])
    d.add(Line(ax + 75, y3, ax + 75, y4 + bh, strokeColor=INK, strokeWidth=1.4))
    d.add(Line(bx + 75, y3, bx + 75, y4 + bh, strokeColor=INK, strokeWidth=1.4))
    label(d, ax + 80, y4 + bh + 8, "plugs in (DB9 male)", anchor="start")
    label(d, bx + 80, y4 + bh + 8, "plugs in (DB9 male)", anchor="start")

    # Row 5: laptop
    y5 = 0
    box(d, cx - 80, y5, 160, bh, "Capture laptop", ["python tools/sniff.py", "run on BATTERY"], fill=PANEL)
    d.add(PolyLine([ax + 75, y4, ax + 75, y5 + bh / 2, cx - 80, y5 + bh / 2], strokeColor=INK, strokeWidth=1.4))
    d.add(PolyLine([bx + 75, y4, bx + 75, y5 + bh / 2, cx + 80, y5 + bh / 2], strokeColor=INK, strokeWidth=1.4))
    label(d, ax + 80, y5 + bh / 2 + 5, "USB", anchor="start")
    label(d, bx + 70, y5 + bh / 2 + 5, "USB", anchor="end")
    return d


LINE_PINS = {  # DB9 pin: (name, meaning on the tapped line, as seen at the PC connector)
    1: ("DCD", "carrier detect (ctrl→PC)"),
    2: ("RXD", "controller TX → PC"),
    3: ("TXD", "PC TX → controller"),
    4: ("DTR", "PC output"),
    5: ("GND", "signal ground"),
    6: ("DSR", "controller output"),
    7: ("RTS", "PC output"),
    8: ("CTS", "controller output"),
    9: ("RI", "ring indicator"),
}
DIGITUS_PINS = {1: "DCD in", 2: "RXD in", 3: "TXD OUT", 4: "DTR OUT", 5: "GND", 6: "DSR in", 7: "RTS OUT",
                8: "CTS in", 9: "RI in"}
FORBIDDEN = {3, 4, 7}


def terminal_strip(d, x, top, title, subtitle, pins_text, stroke, forbidden=(), side="right", w=118):
    """Vertical 9-terminal board. Returns {pin: (x_of_connection_edge, y)}."""
    pitch = 19
    h = 9 * pitch + 30
    d.add(Rect(x, top - h, w, h, rx=4, ry=4, fillColor=colors.white, strokeColor=stroke, strokeWidth=1.3))
    label(d, x + w / 2, top + 14, title, size=9, color=INK, font="Arial-Bold")
    label(d, x + w / 2, top + 4, subtitle, size=7.2)
    points = {}
    for pin in range(1, 10):
        y = top - 22 - (pin - 1) * pitch
        tx = x + w - 12 if side == "right" else x + 12
        bad = pin in forbidden
        d.add(Rect(tx - 6, y - 6, 12, 12, fillColor=DANGER_BG if bad else PANEL,
                   strokeColor=DANGER if bad else MUTED, strokeWidth=0.8))
        d.add(Circle(tx, y, 2.2, fillColor=MUTED, strokeColor=None))
        text_x = x + 8 if side == "right" else x + 24
        d.add(String(text_x, y - 3, f"{pin}", fontName="Mono-Bold", fontSize=8.5, fillColor=INK))
        d.add(String(text_x + 12, y - 3, pins_text[pin], fontName="Arial", fontSize=7.2,
                     fillColor=DANGER if bad else INK))
        if bad:
            d.add(Line(tx - 4, y - 4, tx + 4, y + 4, strokeColor=DANGER, strokeWidth=1.2))
            d.add(Line(tx - 4, y + 4, tx + 4, y - 4, strokeColor=DANGER, strokeWidth=1.2))
        points[pin] = (tx, y)
    return points


def wire(d, a, b, channel_x, color, dashed=False, text=None, text_y=None):
    pts = [a[0], a[1], channel_x, a[1], channel_x, b[1], b[0], b[1]]
    d.add(PolyLine(pts, strokeColor=color, strokeWidth=1.8, strokeDashArray=[4, 3] if dashed else None))
    for p in (a, b):
        d.add(Circle(p[0], p[1], 3, fillColor=color, strokeColor=None))
    if text:
        label(d, b[0] - 20, (text_y if text_y is not None else b[1]) + 4, text, size=7,
              color=color, font="Arial-Bold", anchor="end")


def detail():
    d = Drawing(W, 510)
    male_txt = {p: f"{n}  {m}" for p, (n, m) in LINE_PINS.items()}
    fem_txt = {p: DIGITUS_PINS[p] for p in range(1, 10)}
    male = terminal_strip(d, 0, 370, "MALE board (on Y female #2)", "line signals, PC-side numbering",
                          male_txt, ACCENT, w=160)
    ax = W - 118
    a = terminal_strip(d, ax, 490, "FEMALE board A → Digitus A", "listens PC → controller",
                       fem_txt, TX_PC, FORBIDDEN, side="left")
    b = terminal_strip(d, ax, 245, "FEMALE board B → Digitus B", "listens controller → PC",
                       fem_txt, TX_CTRL, FORBIDDEN, side="left")

    wire(d, male[3], a[2], 190, TX_PC, text="pin 3 → A2", text_y=a[2][1])
    wire(d, male[5], a[5], 210, GND, text="GND → A5")
    wire(d, male[7], a[8], 230, OPT_A, dashed=True, text="opt. RTS → A8")
    wire(d, male[2], b[2], 250, TX_CTRL, text="pin 2 → B2")
    wire(d, male[5], b[5], 270, GND, text="GND → B5")
    wire(d, male[8], b[8], 290, OPT_B, dashed=True, text="opt. CTS → B8")

    # legend
    ly = 24
    items = [(TX_PC, False, "PC → controller data"), (TX_CTRL, False, "controller → PC data"),
             (GND, False, "ground"), (OPT_A, True, "optional handshake")]
    x = 0
    for color, dashed, text in items:
        d.add(Line(x, ly, x + 22, ly, strokeColor=color, strokeWidth=1.8,
                   strokeDashArray=[4, 3] if dashed else None))
        label(d, x + 27, ly - 3, text, size=7.5, color=INK, anchor="start")
        x += 118
    d.add(Rect(0, ly - 26, 10, 10, fillColor=DANGER_BG, strokeColor=DANGER, strokeWidth=0.8))
    d.add(Line(1.5, ly - 24.5, 8.5, ly - 17.5, strokeColor=DANGER, strokeWidth=1.2))
    d.add(Line(1.5, ly - 17.5, 8.5, ly - 24.5, strokeColor=DANGER, strokeWidth=1.2))
    label(d, 15, ly - 24, "Digitus OUTPUT pin — must stay EMPTY (would fight the PC's drivers on the live line)",
          size=7.5, color=DANGER, anchor="start")
    return d


# ---------------------------------------------------------------- document

def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont("Arial", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(20 * mm, 12 * mm, "PressController · passive RS-232 tap for Proteus ↔ DigiMaxx C-20")
    canvas.drawRightString(A4[0] - 20 * mm, 12 * mm, f"Page {doc.page}")
    canvas.setStrokeColor(LINE)
    canvas.line(20 * mm, 15 * mm, A4[0] - 20 * mm, 15 * mm)
    canvas.restoreState()


def build():
    doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=22 * mm,
                            title="RS-232 Passive Tap – Wiring Guide", author="PressController project",
                            subject="Sniffing Proteus <-> DigiMaxx C-20 serial traffic")
    s = []

    # Page 1 — overview
    s += [P("RS-232 Passive Tap — Wiring Guide", "title"), Spacer(1, 3),
          P("Listening to both directions of the Proteus PC ↔ FORM+TEST DigiMaxx C-20 serial link, "
            "without interrupting it. University of Patras · 4000 kN compression press.", "subtitle"),
          Spacer(1, 10)]
    s += [P("How it works", "h1"),
          P("RS-232 uses one wire per direction: <b>pin 3</b> carries the PC's commands and <b>pin 2</b> carries the "
            "controller's replies (numbering at the PC connector). The Y-cable exposes every line on a spare "
            "connector. A male terminal board breaks those lines out to screw terminals, and only the two data "
            "lines plus ground are wired onward, each to the <b>receive input</b> of its own USB adapter. "
            "The adapters' outputs are never connected, so the tap is electrically listen-only."),
          Spacer(1, 10), overview(), Spacer(1, 10)]
    s += [callout("<b>Orientation matters.</b> The Y-cable must sit at the <b>PC end</b> of the link (Y female #1 "
                  "directly on the PC's COM port). All pin numbers in this guide are as seen at the PC connector, "
                  "regardless of how the controller's own cable is wired internally.", PANEL, ACCENT)]
    s.append(PageBreak())

    # Page 2 — terminal wiring
    s += [P("Terminal wiring", "h1"),
          P("Four wires are required; two more are optional and only add handshake-line logging "
            "(<font face='Mono'>--lines</font>). Two wires share the male board's GND terminal "
            "(or use its extra GND terminal, if present)."),
          Spacer(1, 8),
          callout("<b>Never connect pins 3, 4 or 7 on boards A or B.</b> Those are the Digitus adapters' TXD, DTR "
                  "and RTS <i>outputs</i>. Connected to the tap they would drive the same wires as the PC and "
                  "corrupt the command stream while the press is under load. Software cannot switch them off.",
                  DANGER_BG, DANGER),
          Spacer(1, 14), detail()]
    s.append(PageBreak())
    s += [P("Wire list", "h1"), table([
        ["#", "From: MALE board", "To", "Carries", "Required"],
        ["1", "pin 3 (TXD)", "board A pin 2 (RXD in)", "PC → controller data", "yes"],
        ["2", "pin 2 (RXD)", "board B pin 2 (RXD in)", "controller → PC data", "yes"],
        ["3", "pin 5 (GND)", "board A pin 5 (GND)", "signal ground", "yes"],
        ["4", "pin 5 (GND)", "board B pin 5 (GND)", "signal ground", "yes"],
        ["5", "pin 7 (RTS)", "board A pin 8 (CTS in)", "PC RTS handshake", "optional"],
        ["6", "pin 8 (CTS)", "board B pin 8 (CTS in)", "controller CTS handshake", "optional"],
    ], [8 * mm, 32 * mm, 45 * mm, 50 * mm, W - 135 * mm])]

    # parts
    s += [Spacer(1, 6), P("Parts list", "h1")]
    s += [table([
        ["#", "Part", "Qty", "Status", "Notes"],
        ["1", "<b>MEIRIYFA DB9 Y-splitter</b>, 1× male → 2× female, straight-through, 50 cm", "1", "ordered",
         "Amazon B0DQW2H1CC. Verify 1:1 continuity on all 9 pins before use."],
        ["2", "<b>Digitus DA-70156</b> USB 2.0 → RS-232, FTDI FT232RL, DB9 male", "2", "have",
         "Set Latency Timer to 1 ms (Device Manager → Port Settings → Advanced)."],
        ["3", "<b>DB9 MALE → screw-terminal board</b> (solderless breakout, 3.96 mm terminals)", "1", "to buy",
         "Plugs into Y female #2. Local: GRobotronics (grobotronics.com)."],
        ["4", "<b>DB9 FEMALE → screw-terminal board</b>", "2", "to buy",
         "Digitus A and B plug into these. Prefer versions with a case."],
        ["5", "Hook-up wire, 22 AWG, stranded, ~15 cm pieces", "4 (+2)", "to buy",
         "Use different colours for pin 3, pin 2 and GND."],
        ["6", "Capture laptop, Python 3 + pyserial, 2 free USB ports", "1", "have", "Run on battery during capture."],
        ["7", "Multimeter with continuity beeper", "1", "—", "For the pre-connection checks."],
        ["8", "Slotted screwdriver, 2 mm", "1", "—", "For the terminal screws."],
    ], [8 * mm, 62 * mm, 13 * mm, 16 * mm, W - 99 * mm])]
    s += [Spacer(1, 4),
          P("Easiest purchase for items 3–4: two <b>male + female</b> breakout packs, e.g. YIOVVOM DB9 breakout "
            "M+F with case (Amazon B07DKZCL5B) or Twinklebay DB9 breakout M+F (Amazon B073RGGDKH). That yields "
            "2 male + 2 female boards; the extra male board is a spare.", "muted")]

    s += [KeepTogether([P("DB9 pinout reference", "h1"),
          table([["Pin", "Signal", "On the tapped line (PC connector)", "On the Digitus (DTE)", "Tap it?"]] +
                [[str(p), n, m, DIGITUS_PINS[p],
                  {2: "yes → B2", 3: "yes → A2", 5: "yes → A5, B5", 7: "optional → A8",
                   8: "optional → B8"}.get(p, "no")]
                 for p, (n, m) in LINE_PINS.items()],
                [11 * mm, 16 * mm, 55 * mm, 38 * mm, W - 120 * mm],
                extra=[("TEXTCOLOR", (3, r), (3, r), DANGER) for r in (3, 4, 7)])])]
    s.append(PageBreak())

    # Page 4 — procedure
    s += [P("Checks before touching the press", "h1")]
    steps = [
        "<b>Y-cable continuity.</b> With nothing plugged in, confirm each of pins 1–9 on the male end beeps "
        "through to the same pin on <i>both</i> female ends, and no pin shorts to a neighbour.",
        "<b>Tap assembly continuity.</b> With the Digitus adapters unplugged, confirm only: male 3 ↔ A2, "
        "male 2 ↔ B2, male 5 ↔ A5 and B5 (plus the optional 7 ↔ A8, 8 ↔ B8). "
        "A3, A4, A7, B3, B4 and B7 must connect to <b>nothing</b>.",
        "<b>Baseline.</b> Insert the Y-cable between PC and controller cable, with nothing on Y female #2. "
        "Start Proteus and confirm the status bar shows <b>HARDWARE OK</b>.",
        "<b>Add the tap.</b> Plug the male board into Y female #2. Confirm HARDWARE OK still shows.",
        "<b>Add the adapters.</b> Plug Digitus A and B into boards A and B, USB into the laptop (on battery). "
        "Note their COM numbers and set Latency Timer = 1 ms on both. Confirm HARDWARE OK once more.",
        "<b>Rollback</b> at any sign of trouble: unplug the Y-cable and reconnect the controller cable "
        "directly to the PC.",
    ]
    s += [table([[f"{i}", P(t, "small")] for i, t in enumerate(steps, 1)], [8 * mm, W - 8 * mm],
                header=False, zebra=False)]

    s += [P("Capture", "h1"),
          P("Find the baud rate first (keep Proteus' measurement window open so it is polling), then record "
            "sessions. Type a short note + Enter during capture to mark what you did (e.g. <i>clicked Zero</i>)."),
          Spacer(1, 4)]
    code = [
        "python tools/sniff.py --list",
        "python tools/sniff.py --scan --pc-port COM5 --ctrl-port COM6",
        "python tools/sniff.py --pc-port COM5 --ctrl-port COM6 --baud 9600",
        "python tools/sniff.py --pc-port COM5 --ctrl-port COM6 --baud 9600 --lines   # with optional wires",
    ]
    ct = Table([[P(c.replace(" ", "&nbsp;"), "code")] for c in code], colWidths=[W])
    ct.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PANEL), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    s += [ct, Spacer(1, 4),
          P("If replies show up labelled <font face='Mono'>PC&gt;CTRL</font>, the two COM numbers are swapped.",
            "muted")]

    s += [KeepTogether([P("Safety notes", "h1"), table([[P(t, "small")] for t in [
        "The tap is listen-only by design. Do not wire any Digitus output and do not send anything from the laptop "
        "to the controller at this stage.",
        "Run the laptop on battery. Its ground is joined to the press's signal ground through the tap; a mains-powered "
        "laptop can create a ground loop and inject noise.",
        "Do not use Proteus' <b>Calibrate</b> menu while capturing until the protocol is understood — "
        "it may write to the controller.",
        "The controller's hardware STOP and the press emergency stop remain the primary safety devices at all times.",
    ]], [W], header=False)])]

    doc.build(s, onFirstPage=on_page, onLaterPages=on_page)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    build()
