import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPainter, QPixmap, QColor, QPen, QBrush, QPainterPath
from PyQt6.QtCore import Qt, QRectF

app = QApplication(sys.argv)

SIZE = 256
px = QPixmap(SIZE, SIZE)
px.fill(Qt.GlobalColor.transparent)

p = QPainter(px)
p.setRenderHint(QPainter.RenderHint.Antialiasing)

p.setBrush(QBrush(QColor("#c0392b")))
p.setPen(Qt.PenStyle.NoPen)
p.drawEllipse(0, 0, SIZE, SIZE)

p.setBrush(QBrush(QColor("#ffffff")))
mic_w, mic_h = 70, 90
mic_x = (SIZE - mic_w) // 2
mic_y = 55
radius = mic_w // 2
path = QPainterPath()
path.addRoundedRect(QRectF(mic_x, mic_y, mic_w, mic_h), radius, radius)
p.drawPath(path)

pen = QPen(QColor("#ffffff"))
pen.setWidth(10)
pen.setCapStyle(Qt.PenCapStyle.RoundCap)
p.setPen(pen)
p.setBrush(Qt.BrushStyle.NoBrush)
arc_rect = QRectF(SIZE // 2 - 48, mic_y + mic_h - 30, 96, 80)
p.drawArc(arc_rect, 0, -180 * 16)

p.drawLine(SIZE // 2, int(arc_rect.bottom()), SIZE // 2, int(arc_rect.bottom()) + 18)
p.drawLine(
    SIZE // 2 - 22, int(arc_rect.bottom()) + 18,
    SIZE // 2 + 22, int(arc_rect.bottom()) + 18,
)

p.end()

out = Path(__file__).parent.parent / "assets" / "icon.png"
out.parent.mkdir(exist_ok=True)
px.save(str(out))
print(f"Ícone gerado: {out}")

app.quit()
