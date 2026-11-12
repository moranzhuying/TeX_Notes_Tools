#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_icon.py — 生成 exe 用的 tools.ico

用 Qt 画一个工具箱图标，导出多种尺寸的 PNG，再按 ICO 格式拼起来
（ICO 允许直接内嵌 PNG，Vista 以后都这么干）。

    <venv>/Scripts/python.exe make_icon.py

产物：Tools/tools.ico。改样式后重跑一次即可。
"""
import io
import struct
import sys
from pathlib import Path

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    sys.stderr.write("需要 PySide6。\n")
    raise SystemExit(2)

HERE = Path(__file__).resolve().parent
OUT = HERE / "tools.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def draw(size):
    """画一张 size×size 的图标。"""
    pm = QtGui.QPixmap(size, size)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    s = float(size)

    # 圆角底板 + 竖直渐变 + 一圈亮边
    path = QtGui.QPainterPath()
    path.addRoundedRect(QtCore.QRectF(s * 0.05, s * 0.05, s * 0.90, s * 0.90),
                        s * 0.22, s * 0.22)
    grad = QtGui.QLinearGradient(0, 0, 0, s)
    grad.setColorAt(0.0, QtGui.QColor("#31507F"))
    grad.setColorAt(1.0, QtGui.QColor("#141F33"))
    p.fillPath(path, grad)
    p.setPen(QtGui.QPen(QtGui.QColor("#5B9BFF"), max(1.0, s * 0.014)))
    p.drawPath(path)

    # 提手：宽而扁，才是工具箱的样子（窄高会读成挂锁）
    pen = QtGui.QPen(QtGui.QColor("#F2F6FC"), max(1.0, s * 0.055),
                     QtCore.Qt.SolidLine, QtCore.Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(QtCore.Qt.NoBrush)
    handle = QtGui.QPainterPath()
    handle.moveTo(s * 0.36, s * 0.42)
    handle.lineTo(s * 0.36, s * 0.36)
    handle.arcTo(QtCore.QRectF(s * 0.36, s * 0.29, s * 0.28, s * 0.16), 180, -180)
    handle.lineTo(s * 0.64, s * 0.42)
    p.drawPath(handle)

    # 箱体
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(QtGui.QColor("#F2F6FC"))
    p.drawRoundedRect(QtCore.QRectF(s * 0.22, s * 0.42, s * 0.56, s * 0.34),
                      s * 0.045, s * 0.045)

    # 箱盖与箱身的分界
    p.setPen(QtGui.QPen(QtGui.QColor("#31507F"), max(1.0, s * 0.022)))
    p.drawLine(QtCore.QPointF(s * 0.22, s * 0.555), QtCore.QPointF(s * 0.78, s * 0.555))

    # 搭扣
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(QtGui.QColor("#31507F"))
    p.drawRoundedRect(QtCore.QRectF(s * 0.445, s * 0.505, s * 0.11, s * 0.10),
                      s * 0.02, s * 0.02)
    p.end()
    return pm


def png_bytes(pm):
    """Pixmap.save 只认 QIODevice，Python 的 BytesIO 不行，用 QBuffer。"""
    buf = QtCore.QBuffer()
    buf.open(QtCore.QIODevice.WriteOnly)
    pm.save(buf, "PNG")
    data = bytes(buf.data())
    buf.close()
    return data


def build_ico(path):
    images = [(size, png_bytes(draw(size))) for size in SIZES]
    out = bytearray(struct.pack("<HHH", 0, 1, len(images)))
    offset = 6 + 16 * len(images)
    for size, data in images:
        out += struct.pack("<BBBBHHII",
                           size if size < 256 else 0,
                           size if size < 256 else 0,
                           0, 0, 1, 32, len(data), offset)
        offset += len(data)
    for _size, data in images:
        out += data
    Path(path).write_bytes(bytes(out))
    return sum(len(d) for _s, d in images)


def main():
    app = QtWidgets.QApplication(sys.argv)
    total = build_ico(OUT)
    # 回读确认能被 Qt 正常解析
    icon = QtGui.QIcon(str(OUT))
    sizes = icon.availableSizes()
    print("已生成 {}（{:.1f} KB）".format(OUT, total / 1024))
    print("Qt 回读到的尺寸：{}".format([s.width() for s in sizes]))
    if not sizes:
        print("✗ 生成的 ico 无法被 Qt 识别")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
