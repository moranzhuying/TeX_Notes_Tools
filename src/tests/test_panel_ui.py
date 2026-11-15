# -*- coding: utf-8 -*-
"""面板回归测试一：单实例、切页保活、列宽、清空。

离屏运行，不弹窗口，也不碰真实配置（配置写到临时目录）：

    <venv>/Scripts/python.exe -X utf8 src/tests/test_panel_ui.py

覆盖的四条都是 2026-11-15 那轮改动：
1. 命名互斥体只放行一个实例；
2. 「返回工具列表」再回来，表单值 / 结果 / 进程都还在；
3. 默认列宽按内容算、末列补足，用户拖过之后刷新不重置；
4. 「清空」清掉结果但不打断任务。
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SRC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC))

import panel_config as cfg  # noqa: E402

# 配置写到临时文件，别动真的 _panel_config.json
cfg.CONFIG_PATH = Path(tempfile.mkdtemp(prefix="panel-test-")) / "_panel_config.json"

import panel_actions  # noqa: E402
import panel_qt  # noqa: E402
from PySide6 import QtWidgets  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  " + detail if detail else ""))
    if not cond:
        fails.append(name)


app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

# ---------- 1. 单实例 ----------
first = panel_qt._claim_single_instance()
second = panel_qt._claim_single_instance()
check("单实例：第一次拿到锁", first is True)
check("单实例：第二次被拒", second is False)

# ---------- 2~4. 主窗口 ----------
win = panel_qt.MainWindow()
win.show()

tool = next(t for t in win.tools if t["id"] == "16")
win.open_panel("16")
panel = win._panels.get("16")
check("打开工具页并建了面板", panel is not None)

panel.widgets["keep"].setText("37")
panel._show_result("[2026-11-15 18:30:00][123][INFO] 启动 第一次运行\n"
                   "[2026-11-15 18:30:05][123][INFO] 提交完成 3 个文件\n")
rows_before = panel.table.rowCount()
check("结果表有行", rows_before > 0, "行数={}".format(rows_before))

widths = [panel.table.horizontalHeader().sectionSize(c)
          for c in range(panel.table.columnCount())]
check("默认列宽不小于 110", min(widths) >= 110, "宽度={}".format(widths))
check("首列放得下时间", widths[0] >= 130, "首列={}".format(widths[0]))

win.close_panel()
check("返回列表后面板仍被持有", win._panels.get("16") is panel)
check("面板已从布局摘下且隐藏", panel.isHidden())
win.open_panel("16")
check("回到同一页时复用同一个面板", win._panels.get("16") is panel)
check("表单值还在", panel.widgets["keep"].text() == "37",
      "keep={!r}".format(panel.widgets["keep"].text()))
check("结果还在", panel.table.rowCount() == rows_before and rows_before > 0)

header = panel.table.horizontalHeader()
header.resizeSection(0, 260)          # 等价于用户拖到 260，会发 sectionResized
panel._save_column_widths()
check("拖动后内存里的宽度已更新", panel._saved_widths[0] == 260,
      "_saved_widths={}".format(panel._saved_widths))
panel._show_result("[2026-11-15 18:31:00][123][INFO] 第二次运行\n")
check("再次刷新不重置列宽", header.sectionSize(0) == 260,
      "首列={}".format(header.sectionSize(0)))

stored = (cfg.load().get("column_widths") or {}).get("16")
check("宽度落盘", stored is not None and stored[0] == 260, "stored={}".format(stored))

panel.reset_column_widths()
check("恢复默认后不再记忆", panel._saved_widths is None)
check("恢复默认后宽度回落", header.sectionSize(0) != 260,
      "首列={}".format(header.sectionSize(0)))

panel.clear_result()
check("清空后表格没有行", panel.table.rowCount() == 0)
check("清空后缓冲已丢", panel._buffer == "")

header.resizeSection(1, 300)
panel._save_column_widths()
rebuilt = panel_actions.build("16", tool)
w = rebuilt.table.horizontalHeader().sectionSize(1)
check("重建后按记忆恢复列宽", w == 300, "第 2 列={}".format(w))

win.close()

print()
if fails:
    print("失败 {} 项：{}".format(len(fails), "、".join(fails)))
    sys.exit(1)
print("全部通过")
