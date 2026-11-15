# -*- coding: utf-8 -*-
"""面板回归测试二：真跑一个工具，并在它跑的过程中切走再切回。

    <venv>/Scripts/python.exe -X utf8 src/tests/test_panel_run.py

验证的是「切页保活」最关键的一条：面板从布局里摘下来之后，QProcess 还在跑，
输出落在被藏起来的面板里，卡片状态也会更新。用 11 号（配置路径检查，无参数、
几十秒内结束）当受试工具。
"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SRC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC))

import panel_config as cfg  # noqa: E402

cfg.CONFIG_PATH = Path(tempfile.mkdtemp(prefix="panel-run-")) / "_panel_config.json"

import panel_qt  # noqa: E402
from PySide6 import QtWidgets  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  " + detail if detail else ""))
    if not cond:
        fails.append(name)


app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
win = panel_qt.MainWindow()
win.show()

win.open_panel("11")
panel = win._panels["11"]
panel.run_btn.click()

# 刚起来就切走（相当于点「返回工具列表」）
win.close_panel()
check("切走后进程仍在跑", panel.proc is not None)
check("面板已被藏起", panel.isHidden())

deadline = time.time() + 90
while time.time() < deadline and panel.proc is not None:
    app.processEvents()
    time.sleep(0.05)
app.processEvents()

check("任务已结束", panel.proc is None)
text = panel._buffer
check("输出落在被藏起的面板里", len(text) > 0, "{} 字符".format(len(text)))
check("结果区有内容",
      (panel.table.rowCount() > 0) or
      (panel.out is not None and panel.out.toPlainText()),
      "行数={}".format(panel.table.rowCount() if panel.table else -1))
check("卡片状态已更新", "完成" in win.cards["11"].status.text(),
      "status={!r}".format(win.cards["11"].status.text()))

win.open_panel("11")
check("切回来还是同一个面板", win._panels["11"] is panel)
check("切回来输出还在", panel._buffer == text)
check("切回来按钮已恢复", panel.run_btn.isEnabled())

panel.clear_result()
check("清空后表格空", panel.table.rowCount() == 0)

win.close()
print()
if fails:
    print("失败 {} 项：{}".format(len(fails), "、".join(fails)))
    sys.exit(1)
print("全部通过")
