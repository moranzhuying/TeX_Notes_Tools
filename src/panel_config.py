#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
panel_config.py — 面板的持久化配置与内置帮助文本

配置存在 `Tools/_panel_config.json`（打包后也在 exe 旁边），随时可删，删了回到默认。
放这里而不是散在 UI 代码里，是为了让「设置页」和「帮助页」都只管展示。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import app_paths  # noqa: E402 —— 配置落点由它决定

#: 面板设置。便携形态在程序目录，安装形态进 %APPDATA%\LaTeX-Toolbox。
CONFIG_PATH = app_paths.settings_file("_panel_config.json")

#: 默认配置。新增项时在这里加默认值即可，旧配置文件会自动补齐。
DEFAULTS = {
    # 外观
    "theme": "auto",              # auto / dark / light
    "font_scale": 0.0,            # 界面字号：0 = 跟随画面（按屏幕密度自动），或 0.85 ~ 1.5
    # 行为
    "confirm_danger": True,       # 破坏性操作执行前弹确认
    "remember_columns": True,     # 记住表格列宽
    # 记住的状态
    "last_group": "",
    "columns": {},                # {"工具号": [列宽, ...]}
}


def load():
    """读配置；文件不存在或坏了都退回默认值，不让面板起不来。"""
    data = dict(DEFAULTS)
    try:
        if CONFIG_PATH.is_file():
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                stored = json.load(fh)
            if isinstance(stored, dict):
                for key, value in stored.items():
                    if key in DEFAULTS:
                        data[key] = value
    except (OSError, ValueError):
        pass
    return data


def save(data):
    """写配置。写不了（只读目录等）也不能让面板崩。"""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8", newline="") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def update(**kwargs):
    """改若干项并落盘。"""
    data = load()
    data.update(kwargs)
    save(data)
    return data


# ---------------------------------------------------------------- 内置帮助

#: 帮助正文（HTML 片段）。用 HTML 而非 Markdown：Qt 的 Markdown 解析器
#: 只支持标题/粗体/代码块，列表与表格的样式几乎不可调。
HELP_HTML = """
<p class="lead">本面板把工作区里的 16 个笔记维护工具收在一起。左边按用途分组，
右边是卡片，点卡片上的<b>打开</b>进工具页：选操作、填参数、点<b>执行</b>，
结果直接显示在下方。</p>

<p class="lead"><b>整个面板不弹命令行窗口</b> —— 工具在后台跑，输出收进结果区。</p>

<h2>左侧导航怎么用</h2>
<ul>
<li>上半部分是<b>工具分组</b>，按用途分的六组：核心工具、创建与维护、信息安全与提交、
素材与转写、PDF 处理、运行监测。</li>
<li>下半部分是<b>使用帮助</b>与<b>设置</b>。设置页能改主题、字号，也能恢复默认设置。</li>
<li>搜索框跨分组查找：输入关键词会单独列出全部命中结果，并显示命中个数。</li>
</ul>

<h2>工具页怎么用</h2>
<ul>
<li>每个工具页上半部分是<b>表单</b>，下半部分是<b>结果</b>。</li>
<li>表单里有些字段会随别的字段联动。比如「符号库管理」切成「删除符号」时，
才出现「要删除的符号名」这一行；没显示的字段不会传给工具。</li>
<li>结果区是<b>表格</b>：列宽可以<b>用鼠标拖动边界调整</b>，拖完会被记住，下次打开还在。</li>
<li>「复制」按钮把整张结果表复制成制表符分隔的文本，可以直接粘进 Excel。</li>
<li>「执行」旁边有「停止」，长任务卡住了可以中断。</li>
</ul>

<h2>结果怎么看</h2>
<ul>
<li>表格型结果：每个工具一行或几行，右边有摘要（比如「13 个仓库，1 个有未提交改动」）。</li>
<li>解析不出结构的工具退回文本模式，但也会清掉命令行回显、压缩空行。</li>
<li>破坏性操作默认<b>不勾选</b>。真正写入前会先出预览，确认了才动文件。</li>
</ul>

<h2>快捷键</h2>
<table class="keys">
<tr><td><b>/</b></td><td>定位到搜索框</td></tr>
<tr><td><b>Esc</b></td><td>清空搜索；正在工具页时返回分组</td></tr>
<tr><td><b>Ctrl+1</b> ~ <b>Ctrl+6</b></td><td>跳到第 1~6 组</td></tr>
<tr><td><b>Ctrl+,</b></td><td>打开设置</td></tr>
</table>

<h2>遇到问题</h2>
<ul>
<li>工具报错时，详情看面板底部的状态条；完整栈写在日志目录的 <code>_panel_error.log</code>
（便携版在 <code>Tools/logs/</code>，安装版在 <code>%LOCALAPPDATA%\\LaTeX-Toolbox\\logs\\</code>）。</li>
<li>界面显示不对（比如图标没变）：Windows 会缓存 exe 图标，删掉
<code>%LOCALAPPDATA%\\IconCache.db</code> 再重启资源管理器即可。</li>
<li>改了工具代码要重新打包：在 <code>Tools/</code> 下跑 <code>python src/build_exe.py</code>。</li>
</ul>
"""

HELP_TOOLS_LEAD = "下面按分组列出每个工具的用途。点工具名旁边的「打开」就是直接用。"


def tool_help_rows():
    """给帮助页用的工具清单表：[(分组, 名称, 说明)]。"""
    import panel_core as core

    rows = []
    for tool in core.describe_tools():
        rows.append((tool["group"], tool["title"], tool["desc"]))
    return rows
