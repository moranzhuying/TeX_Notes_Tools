#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_help.py — 生成 resources/help/ 下的帮助文档（每工具一页 + 总览）。

    <venv>/Scripts/python.exe src/make_help.py

为什么要生成而不是手写 19 个 HTML：样式、导航、页脚只有一份，改一次全站生效；
内容集中在下面 DOCS 里，改文案不用碰标签。

文档是**浅色白底**，与 `_dbg/shoot_help.py` 截的图一致；面板是深色主题时，
QTextBrowser 里呈现为一张「纸」，反而好读。
"""
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "resources" / "help"
IMG_W = 1000


def png_size(path):
    """读 PNG 头里的宽高（IHDR 固定在第 16–24 字节）。

    QTextBrowser 只给 width 时，会按图片自带的 DPI 元数据另算高度 ——
    结果在图片下方留出一大块空白。宽高都给死就没这问题。
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(26)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", head[16:24])
            return w, h
    except OSError:
        pass
    return 0, 0


def img_tag(name):
    """图片：引用浅色那一套，宽度写「设计宽度」，由 HelpPage 按窗口实测宽等比缩放。

    静态 HTML 里写死宽度的话，窗口一宽图就偏小、一窄就出横向滚动条。
    `img/light/` 这个前缀在深色主题下会被换成 `img/dark/`。
    """
    w, h = png_size(OUT / "img" / "light" / name)
    boxes = f'width="{IMG_W}"'
    if w:
        boxes += f' height="{max(1, round(IMG_W * h / w))}"'
    # 外面套一层链接：面板里点击会用系统看图器打开原图，细节能看清
    return (f'<p align="center"><a href="img/light/{name}">'
            f'<img src="img/light/{name}" {boxes} alt="界面"></a></p>')

CSS = """
:root { color-scheme: light; }
body {
  margin: 0; padding: 24px 30px 64px; background: #ffffff; color: #24292f;
  font-family: "Segoe UI", "Microsoft YaHei UI", "PingFang SC", sans-serif;
  font-size: 14.5px; line-height: 1.85;
}
h1 { font-size: 23px; margin: 2px 0 8px; color: #0f172a; }
h2 { font-size: 15.5px; margin: 30px 0 10px; padding-bottom: 6px;
     border-bottom: 2px solid #e6e8eb; color: #0f172a; }
h3 { font-size: 14.5px; margin: 20px 0 4px; color: #0f172a; }
p { margin: 8px 0; }
.lead { font-size: 14.5px; color: #3d4653; margin: 4px 0 12px; }
.crumb { font-size: 12px; color: #6b7280; margin: 0 0 14px; }
.crumb a { color: #0067c0; text-decoration: none; }
table.kv { margin: 12px 0 16px; }
table.kv th { background: #f6f8fa; font-weight: 600; color: #5c6470; }
.meta { font-size: 12.5px; color: #5c6470; background: #f6f8fa;
        border: 1px solid #e6e8eb; border-radius: 6px; padding: 9px 12px; margin: 12px 0 16px; }
code { font-family: Consolas, "Cascadia Mono", monospace; font-size: 12.5px;
       background: #f2f4f7; border-radius: 3px; padding: 1px 4px; color: #8a2b06; }
pre { font-family: Consolas, "Cascadia Mono", monospace; font-size: 12.5px;
      background: #f6f8fa; border: 1px solid #e6e8eb; border-radius: 6px;
      padding: 10px 14px; color: #24292f; border-left: 3px solid #d0d7de; }
ul, ol { margin: 8px 0 8px 0; padding-left: 24px; }
li { margin: 4px 0; }
table { border-collapse: collapse; width: 100%; margin: 10px 0 14px; font-size: 13px; }
th { background: #f2f4f7; text-align: left; font-weight: 600; color: #0f172a;
     border: 1px solid #e1e4e8; padding: 8px 12px; }
td { border: 1px solid #e1e4e8; padding: 8px 12px; vertical-align: top; }
.warn { background: #fff8e6; border: 1px solid #f0d29a; border-radius: 6px;
        padding: 10px 12px; margin: 12px 0; }
.danger { background: #fdecea; border: 1px solid #f3b6b0; border-radius: 6px;
          padding: 10px 12px; margin: 12px 0; }
.tip { background: #eef7f0; border: 1px solid #b7dcc1; border-radius: 6px;
       padding: 10px 12px; margin: 12px 0; }
.qa { margin: 10px 0 0; }
.qa .q { font-weight: 600; color: #0f172a; margin: 14px 0 2px; }
.qa .a { margin: 0 0 4px; color: #3d4653; }
img { border: 1px solid #e1e4e8; margin: 14px 0 6px; }
.cap { font-size: 12.5px; color: #6b7280; margin: 0 0 22px; }
.nav { margin-top: 34px; padding-top: 12px; border-top: 1px solid #e6e8eb;
       font-size: 13px; color: #6b7280; }
.nav a { color: #0067c0; text-decoration: none; }
"""


def e(text):
    """转义，但保留内容里已经写好的少量标签（本文件自己控制，不处理用户输入）。"""
    return text


def table(headers, rows, widths=None):
    """表格。`widths` 给每列的百分比，缺省时两列按 28/72 分。

    Qt 会把列宽摊平（一半一半），说明列被挤得没法读；给出百分比后
    QTextTable 会按比例分配。
    """
    if widths is None:
        widths = [28, 72] if len(headers) == 2 else [100 // len(headers)] * len(headers)
    head = "".join(f'<th width="{widths[i]}%">{e(h)}</th>' for i, h in enumerate(headers))
    body = "".join(
        "<tr>" + "".join(f"<td>{e(c)}</td>" for c in row) + "</tr>" for row in rows)
    return f'<table width="100%"><tr>{head}</tr>{body}</table>'


def ul(items):
    return "<ul>" + "".join(f"<li>{e(i)}</li>" for i in items) + "</ul>"


def ol(items):
    return "<ol>" + "".join(f"<li>{e(i)}</li>" for i in items) + "</ol>"


def qa_block(pairs):
    out = ['<div class="qa">']
    for q, a in pairs:
        out.append(f'<p class="q">Q：{e(q)}</p><p class="a">A：{e(a)}</p>')
    out.append("</div>")
    return "".join(out)


def page(doc, prev=None, nxt=None):
    nav = []
    if prev:
        nav.append(f'<a href="{prev[0]}.html">← {e(prev[1])}</a>')
    nav.append('<a href="index.html">帮助目录</a>')
    if nxt:
        nav.append(f'<a href="{nxt[0]}.html">{e(nxt[1])} →</a>')
    nav_html = " &nbsp;·&nbsp; ".join(nav)

    body = [
        '<p class="crumb"><a href="index.html">帮助目录</a> · ' + e(doc["group"]) + "</p>",
        f'<h1>{e(doc["title"])}</h1>',
        f'<p class="lead">{e(doc["lead"])}</p>',
        '<table class="kv"><tr><th width="90">面板入口</th><td>' + e(doc["entry"]) + "</td></tr>"
        + '<tr><th width="90">命令行</th><td><code>' + e(doc["cli"]) + "</code></td></tr></table>",
    ]
    if doc.get("image"):
        body.append(img_tag(doc["image"]))
        body.append(f'<p class="cap" align="center">{e(doc.get("caption", ""))}（点击图片用看图器放大）</p>')

    body.append("<h2>什么时候用</h2>" + ul(doc["when"]))
    body.append("<h2>怎么做</h2>" + ol(doc["steps"]))

    if doc.get("fields"):
        body.append("<h2>界面上每项的意思</h2>")
        body.append(table(["项", "说明"], doc["fields"]))

    if doc.get("cli_more"):
        body.append("<h2>命令行用法</h2><pre>" + e(doc["cli_more"]) + "</pre>")

    if doc.get("data"):
        body.append("<h2>文件都在哪</h2>")
        body.append(table(["内容", "位置"], doc["data"]))

    if doc.get("warn"):
        cls = doc.get("warn_class", "warn")
        body.append(f'<div class="{cls}">{e(doc["warn"])}</div>')

    if doc.get("qa"):
        body.append("<h2>常见问题</h2>" + qa_block(doc["qa"]))

    if doc.get("related"):
        body.append("<h2>相关</h2>" + ul(doc["related"]))

    body.append(f'<p class="nav">{nav_html}</p>')

    return (
        '<!DOCTYPE html>\n<html lang="zh-CN"><head><meta charset="utf-8">'
        f'<title>{e(doc["title"])} — LaTeX 工具箱</title><style>{CSS}</style></head>'
        "<body>" + "".join(body) + "</body></html>\n"
    )


def index_page(docs):
    groups = []
    for d in docs:
        if d["group"] not in groups:
            groups.append(d["group"])

    parts = [
        '<p class="crumb">LaTeX 工具箱 · 帮助</p>',
        "<h1>使用帮助</h1>",
        '<p class="lead">每个工具一页，讲清「什么时候用、界面怎么填、文件落在哪、出问题怎么办」。'
        "看完整篇仍解决不了，就到 <code>Tools/README.md</code> 里找对应的源码说明。</p>",
        img_tag("panel-main.png"),
        '<p class="cap">左侧按用途分组，右侧是当前组的工具卡片；右上角搜索框按 / 聚焦。</p>',
        "<h2>先看这几条</h2>",
        ul([
            "工具在面板里跑，<b>不弹命令行窗口</b>；输出显示在工具页下方，可一键复制成表格。",
            "带「真正写入 / 真正删除」的勾选项默认不勾，先看预演结果再动手。",
            "所有配置与数据都不在程序目录里（便携版除外），见每页「文件都在哪」。",
            "面板设置（主题、字号）在左下角「设置」；文档随 exe 一起分发，断网也能看。",
        ]),
    ]

    for g in groups:
        rows = [[f'<a href="{d["slug"]}.html">{e(d["title"])}</a>', e(d["lead"])]
                for d in docs if d["group"] == g]
        parts.append(f"<h2>{e(g)}</h2>")
        parts.append(table(["工具", "一句话"], rows))

    parts.append('<h2>出问题了</h2>')
    parts.append(ul([
        "先看工具页底部的状态条与结果区，多数错误会写明原因。",
        "面板本身崩了会写日志：便携版在 <code>Tools/logs/_panel_error.log</code>，"
        "安装版在 <code>%LOCALAPPDATA%\\LaTeX-Toolbox\\logs\\</code>。",
        "工具「点了没反应」多半是缺依赖：面板设置页下方会显示工具解释器与缺失的包。",
    ]))

    return (
        '<!DOCTYPE html>\n<html lang="zh-CN"><head><meta charset="utf-8">'
        f"<title>使用帮助 — LaTeX 工具箱</title><style>{CSS}</style></head>"
        "<body>" + "".join(parts) + "</body></html>\n"
    )


#: 板块页：与 `panel_core.GROUP_SLUGS` 一一对应
GROUPS = [
    ("核心工具", "group-core", "日常最常用的四件事：Git 环境、仓库管理、符号库、写作工作台"),
    ("创建与维护", "group-maintain", "建新笔记、导出大纲、单本笔记的提交与骨架、清理编译产物"),
    ("信息安全与提交", "group-commit", "仓库体检、本机信息扫描、路径检查、规范同步、提交"),
    ("素材与转写", "group-media", "视频转文字：字幕优先，无字幕走本地 whisper"),
    ("PDF 处理", "group-pdf", "横躺的课件 PDF 就地转正"),
    ("运行监测", "group-watch", "监测笔记目录，有改动自动提交推送并裁剪历史"),
]


def group_page(name, desc, docs):
    """板块页：这个分组下所有工具的一句话与入口。"""
    rows = [[f'<a href="{d["slug"]}.html">{e(d["title"])}</a>', e(d["lead"])] for d in docs]
    body = [
        '<p class="crumb"><a href="index.html">帮助目录</a> · 板块</p>',
        f"<h1>{e(name)}</h1>",
        f'<p class="lead">{e(desc)}</p>',
        "<h2>这个板块里的工具</h2>",
        table(["工具", "一句话"], rows),
        '<p class="nav"><a href="index.html">← 帮助目录</a></p>',
    ]
    return (
        '<!DOCTYPE html>\n<html lang="zh-CN"><head><meta charset="utf-8">'
        f"<title>{e(name)} — LaTeX 工具箱</title><style>{CSS}</style></head>"
        "<body>" + "".join(body) + "</body></html>\n"
    )


# ============================================================ 各工具正文
DOCS = []


def add(**kw):
    DOCS.append(kw)


add(
    slug="01-git-setup", no=1, group="核心工具",
    title="1. 设置 git 基本信息",
    lead="检测 git / ssh 环境、配置提交身份、配好 GitHub 的 SSH 通道。三件事都只在换机器或首次配置时做一次。",
    entry="核心工具 → 卡片「设置 git 基本信息」→ 选操作 → 执行",
    cli="python tools/git_setup/git_setup.py",
    image="tool-01.png",
    caption="操作下拉切换三件事；结果以「项目 / 值」两列表格出来。",
    when=[
        "刚装好 git，不确定 ssh 能不能连上 GitHub。",
        "换了电脑或重装系统，需要重新配置 <code>user.name</code> / <code>user.email</code>。",
        "仓库能 clone 但 push 报 <code>Permission denied (publickey)</code>。",
        "网络封了 22 端口，需要把 SSH 改走 <code>ssh.github.com:443</code>。",
    ],
    steps=[
        "选「检测环境」，执行。看输出里的 git 版本、用户名、邮箱、密钥是否存在、能否连通。",
        "缺账户就选「配置 Git 账户」，填用户名与邮箱，执行。留空表示不改动。",
        "缺密钥就选「配置 SSH」，勾上「没有密钥时生成 ed25519」，执行。",
        "把结果里显示的公钥整段复制，粘到 GitHub → Settings → SSH and GPG keys → New SSH key。",
        "仍然连不上时，勾「写 ssh config 的 443 端口」再执行一次，然后点「测试连通性」。",
    ],
    fields=[
        ("操作", "检测环境 / 配置 Git 账户 / 配置 SSH。切换后下面的字段跟着变。"),
        ("用户名 / 邮箱", "写进 <code>git config --global</code>；留空则保持原值不动。"),
        ("没有密钥时生成 ed25519", "只在 <code>~/.ssh</code> 里没有密钥时才生成，不会覆盖已有的。"),
        ("写 ssh config 的 443 端口", "把 <code>github.com</code> 指到 <code>ssh.github.com:443</code>，绕开 22 端口被封。"),
        ("测试连通性", "跑一次 <code>ssh -T git@github.com</code>，成功时会显示 <code>Hi 用户名!</code>。"),
    ],
    cli_more="""python tools/git_setup/git_setup.py --check
python tools/git_setup/git_setup.py --account --name 你的名字 --email you@example.com
python tools/git_setup/git_setup.py --ssh --gen-key --write-443 --test""",
    data=[
        ("账户名与邮箱", "<code>~/.gitconfig</code>（全局）"),
        ("密钥", "<code>~/.ssh/id_ed25519</code> 与 <code>.pub</code>"),
        ("SSH 配置", "<code>~/.ssh/config</code>（只动 <code>Host github.com</code> 那一段）"),
        ("远程账户名（供建仓库用）", "<code>tools/manager/manager.conf</code> 或应用数据目录"),
    ],
    qa=[
        ("检测显示「ssh 未安装」怎么办？",
         "Windows 10 以上自带 OpenSSH，先在「设置 → 系统 → 可选功能」里确认 OpenSSH 客户端已装；"
         "装了仍找不到，说明 PATH 里没有，重装一次该可选功能即可。"),
        ("push 报 Permission denied (publickey)",
         "三种可能：① 公钥没粘到 GitHub；② 粘错了账号；③ ssh-agent 没加载密钥。先点「检测环境」看密钥路径，"
         "再用「配置 SSH → 测试连通性」确认。"),
        ("为什么要把 SSH 改成 443 端口？",
         "国内不少网络屏蔽 22 端口，症状是 <code>ssh -T</code> 一直卡住然后超时。443 是 HTTPS 的端口，"
         "通常不被拦；GitHub 在 <code>ssh.github.com:443</code> 上提供同一套 SSH 服务。"),
        ("配置账户会不会覆盖我已经设好的值？",
         "留空就不动。填写才写 <code>git config --global</code>。"),
        ("公司电脑不让改 ~/.ssh，还能用吗？",
         "可以改用 HTTPS 远程，但本工具集的建仓库与提交都假设 SSH。这种情况建议单独配一个仓库级 remote。"),
    ],
    related=["2. 笔记工作区管理（看仓库状态、远程是否配对）", "12. 提交本工具集"],
)

add(
    slug="02-manager", no=2, group="核心工具",
    title="2. 笔记工作区管理",
    lead="一眼看完所有笔记仓库的状态，批量提交推送，或把还没入库的文件夹建成仓库。",
    entry="核心工具 → 卡片「笔记工作区管理」→ 选操作 → 执行",
    cli="python tools/manager/manager.py",
    image="tool-02.png",
    caption="「显示各仓库状态」出的是五行表格：文件夹 / 分支 / 改动 / 领先落后 / 远程。",
    when=[
        "想确认哪几本书有未提交改动、哪些还没推到远程。",
        "一轮写作结束，要把多本笔记一起提交推送。",
        "从模板新拷贝了一个目录，还没 <code>git init</code>，想一次性建好仓库与远程。",
        "笔记根目录换了位置，需要重新登记。",
    ],
    steps=[
        "选「显示各仓库状态」，执行。表格里「改动」是未提交文件数，「领先/落后」是本地与远程的差。",
        "要提交推送就选「批量提交并推送」，填一句提交说明（留空用默认），执行。",
        "只补推送（本地已提交、远程还没收到）选「只推送、不提交」。",
        "新建仓库选「为未入库的文件夹建仓库」，填编号（留空＝全选）与远程账户名，执行。",
    ],
    fields=[
        ("操作", "五种：看状态、批量提交并推送、只推送、建仓库、设根目录。"),
        ("提交说明", "写进 commit message；留空时用默认文案。"),
        ("要建仓库的编号", "表格里的序号，逗号分隔；留空表示全部。"),
        ("远程账户名", "GitHub 用户名，用来拼 <code>git@github.com:用户名/仓库名.git</code>。"),
        ("笔记根目录", "只在「设置笔记根目录」时出现；改完会写进 <code>manager.conf</code>。"),
    ],
    cli_more="""python tools/manager/manager.py --status
python tools/manager/manager.py --commit-all --msg "本轮修改"
python tools/manager/manager.py --commit-all --push-only
python tools/manager/manager.py --create-repo --selection 3,5 --account 你的GitHub名""",
    data=[
        ("笔记根目录、远程账户", "<code>manager.conf</code>（便携：<code>tools/manager/</code>）"),
        ("仓库状态", "实时从 git 读，不落盘"),
    ],
    qa=[
        ("表格里「领先 3 / 落后 0」是什么意思？",
         "本地比远程多 3 个提交，远程没有新东西。落后大于 0 时说明别处推过东西，先拉再推，否则会被拒。"),
        ("「同步正常」但工作区是干净的，为什么还要「只推送」？",
         "工作区干净不代表提交都推上去了。这条专门补推本地已有的提交。"),
        ("远程显示 <code>?</code> 是怎么回事？",
         "没配 remote，或者 <code>git fetch</code> 拿不到对比数据。先确认远程地址存在且能连通。"),
        ("建仓库时报「用户或仓库名不合法」",
         "GitHub 仓库名只允许字母数字与 <code>-_.</code>，且不能以点开头。中文目录名要先改名。"),
        ("commit 被钩子拦下了",
         "那是提交前的本机信息扫描（工具 10）。按提示改掉命中的路径或密钥；确属误报可单次用 "
         "<code>git commit --no-verify</code>。"),
    ],
    related=["1. 设置 git 基本信息", "9. 仓库体检", "16. 笔记目录监测"],
)

add(
    slug="03-symbols", no=3, group="核心工具",
    title="3. 符号库管理",
    lead="在模板与各笔记之间搬运符号定义、刷新 TeXStudio 补全、删除或新增记号。默认只预览，不写文件。",
    entry="核心工具 → 卡片「符号库管理」→ 选操作 → 执行",
    cli="python tools/symbols/symbols.py",
    image="tool-03.png",
    caption="操作下拉决定这一趟做什么；「真正写入」不勾就只出清单。",
    when=[
        "在某一本书里新加了 <code>\\newcommand</code>，想合并回模板，让以后新建的笔记都能用。",
        "模板新增了符号，要同步分发到已有各本笔记的 <code>structure.sty</code>。",
        "TeXStudio 里新符号显示为「未知命令」，需要刷新 <code>custom.cwl</code>。",
        "某个记号名想改或想删，又不想在 10 个文件里手工找。",
    ],
    steps=[
        "选操作（回填 / 分发 / 刷新补全 / 删除 / 提取 / 引入新记号 / 全套），执行。",
        "先看清单：它列出哪个文件、哪一行、会怎么改。这一步不写任何文件。",
        "确认无误后勾「真正写入」，再执行一次。",
        "刷新补全后重开 TeXStudio，或在 TeXStudio 里「重新载入补全」。",
    ],
    fields=[
        ("操作", "七选一。切换后才会出现对应的输入项。"),
        ("要删除的符号名", "多个用空格分隔，不带反斜杠。"),
        ("命令名 / 定义 / 注释", "「引入新记号」用。命令名只允许字母；定义里 <code>%</code> 必须转义成 <code>\\%</code>。"),
        ("覆盖同名已有定义", "默认关闭。开启后同名定义的旧内容会被替换。"),
        ("真正写入", "不勾只预览。这一项是所有写操作的统一开关。"),
    ],
    cli_more="""python tools/symbols/symbols.py --merge --write         # 回填
python tools/symbols/symbols.py --distribute --write    # 分发
python tools/symbols/symbols.py --cwl --write           # 刷新补全
python tools/symbols/symbols.py --drop Foo Bar --write
python tools/symbols/symbols.py --add-name orb --add-def "\\operatorname{Orb}" --write""",
    data=[
        ("笔记根目录、模板路径、cwl 路径", "<code>symbols.conf</code>（便携：<code>tools/symbols/</code>）"),
        ("提取档案", "<code>symbols_extract.json</code>（同一目录）"),
        ("目录结构快照", "<code>notes_tree.json</code>（同一目录）"),
        ("TeXStudio 补全", "<code>%APPDATA%\\texstudio\\completion\\user\\custom.cwl</code>"),
    ],
    warn="回填会修改模板的 <code>structure.sty</code>。模板是唯一真源，工具会在写之前留一份可回滚的备份；"
         "但备份不是版本控制，改坏了请用 <code>git diff</code> 检查再决定。",
    qa=[
        ("只预览时显示「将新增 3 个符号」，勾了写入却没生效？",
         "检查是否选对了操作。回填是「笔记 → 模板」，分发是「模板 → 笔记」，方向反了就看不到变化。"),
        ("提示「跨行定义无法解析」",
         "<code>\\newcommand{\\x}[2]{%</code> 这种换行续写的写法，旧版本只认首行。现在整段解析，"
         "若仍报错，多半是续行里有未转义的 <code>%</code> 或括号不配对。"),
        ("分发后编译报 undefined control sequence",
         "说明笔记的 <code>structure.sty</code> 里没有这个宏。常见原因是分发时该书的文件被 TeX 占用（编译中），"
         "写入失败但没报出来。关掉编辑器再分发一次。"),
        ("TeXStudio 里还是提示未知命令",
         "补全文件路径可能不是这个 TeXStudio 用的那份。看工具输出里显示的 cwl 路径，与 TeXStudio 的"
         "「配置 → 补全 → 用户补全文件」是否一致；另外 cwl 是启动时读的，必须重启。"),
        ("删除符号会不会把模块 II–V 的同名宏一起删掉？",
         "不会，只在 <code>[模块 VI]</code>（自定义符号段）里匹配。"),
    ],
    related=["6. 大纲工具", "7. 单本笔记工具"],
)

add(
    slug="04-progress", no=4, group="核心工具",
    title="4. 写作工作台",
    lead="在本机起一个浏览器界面来写作与预览：左边目录、右边正文，改动直接写回 .tex。默认只读，写入要按书单独授权。",
    entry="核心工具 → 卡片「写作工作台」→ 填参数 → 执行（会打开浏览器）",
    cli="python tools/progress/workbench_launcher.py",
    image="tool-04.png",
    caption="笔记根目录与端口；「允许写入」默认不勾，勾了还要在下面列出授权哪几本。",
    when=[
        "想在浏览器里连续改多篇笔记，比在 TeXStudio 里来回切文件快。",
        "只想读、不想误改：默认只读模式适合通读与校对。",
        "多个 TeXstudio 窗口冲突时，换个界面先看图、后回编辑器改。",
    ],
    steps=[
        "确认「笔记根目录」正确（默认是工作区下的 <code>LaTeX_Notes</code>），端口一般不用改。",
        "只读通读：直接执行，浏览器会打开工作台。",
        "要能保存：勾「允许写入」，在「授权写入的书」里填书名（逗号分隔），再执行。",
        "关闭面板或点工具里的「停止」会关掉本面板起的服务，端口立即释放。",
    ],
    fields=[
        ("笔记根目录", "工作台的根；必须是含各书目录的那一层。"),
        ("端口", "默认 7656。被占用时换一个，工具不会去接管别人的端口。"),
        ("允许写入", "总开关。不勾时全部请求只读，任何保存都会被拒。"),
        ("授权写入的书", "逐本授权，逗号分隔。授权状态按书的永久 ID 记录，书改名不会失效。"),
        ("允许调起 TeXstudio", "只负责打开文件，不等于授权 TeX 写入。"),
    ],
    cli_more="""python tools/progress/workbench_launcher.py --no-browser
python tools/progress/workbench_launcher.py --config 另一个配置.json""",
    data=[
        ("启动配置（root / 端口 / 授权）", "便携：<code>tools/progress/workbench_local.json</code>；"
                                        "安装：<code>%APPDATA%\\LaTeX-Toolbox\\progress\\</code>"),
        ("书 ID 与写入许可", "同上配置文件里的 <code>write_book_ids</code>"),
        ("备份", "写入前先备份到根目录下的备份区，可在工作台里回滚"),
    ],
    qa=[
        ("浏览器打开了但页面空白",
         "服务可能没起来。看工具页结果区的日志末尾，通常是端口被占用（换端口）或笔记根目录填错。"),
        ("保存按钮点了没反应 / 提示无权限",
         "没勾「允许写入」，或这本不在授权列表里。授权是按书 ID 记的，换书要重新授权。"),
        ("端口 7656 被占用",
         "换一个端口重开，例如 7657。工具不会杀掉占用端口的进程 —— 那可能是别的程序。"),
        ("改完发现写坏了，能回滚吗？",
         "可以。写入前会自动备份，工作台里有备份列表与恢复入口。"),
        ("关闭面板后服务还在跑吗？",
         "面板起的服务随面板关闭而关闭。用 <code>--no-browser</code> 独立启动的，要用「停止」或关掉那个窗口。"),
    ],
    related=["7. 单本笔记工具", "9. 仓库体检"],
)


add(
    slug="05-new-note", no=5, group="创建与维护",
    title="5. 新建笔记",
    lead="从一个模板目录复制骨架、清掉模板里的测试内容、按大纲生成章节、初始化 git。默认只预演。",
    entry="创建与维护 → 卡片「新建笔记」→ 填名字与缩写 → 执行",
    cli="python tools/new_note/new_note.py",
    image="tool-05.png",
    caption="笔记名与缩写是必填；「只预演」默认勾着，先看它准备做什么。",
    when=[
        "决定开始啃一本新书，要从模板建一本结构一致的笔记。",
        "手上已经有大纲（缩进清单或 md），想让工具一次性把章节骨架建出来。",
        "想确认「从模板到成书」到底会动哪些文件，先预演一遍。",
    ],
    steps=[
        "填笔记名（字母开头，可含数字下划线与连字符）与缩写（ASCII，例如 GT）。",
        "有大纲就选文件；没有就留空，之后用大纲工具补。",
        "保持「只预演」勾选，执行。看结果里的「将创建 / 将删除 / 将改写」清单。",
        "确认无误，去掉「只预演」再执行一次。",
        "需要远程仓库就勾「建好后推送」，但要先确保 <code>manager.conf</code> 里有远程账户名。",
    ],
    fields=[
        ("笔记名", "目录名与 <code>\\title</code> 的来源。会拦 Windows 保留名（CON/NUL/COM1…）与尾部空格。"),
        ("缩写", "用于封面与页眉的短标识，必须是 ASCII。"),
        ("大纲文件", "可空。给了才生成章节骨架；格式见「大纲工具」页。"),
        ("层级", "可空，例如 <code>part,section</code>。连跳两级会提示。"),
        ("模板目录", "可空，默认 <code>Template/Math-Note</code>。"),
        ("只预演，不写文件", "默认开启。这是安全阀，别在看清单之前关掉它。"),
        ("骨架里建最外层导引 / 各级小结", "默认不建。导引与小结按项目约定默认注释，不占版面。"),
        ("建好后推送到远程", "需要 <code>gh</code> 或已建好的空仓库。"),
    ],
    cli_more="""python tools/new_note/new_note.py --dry-run --name General_Topology --abbreviation GT
python tools/new_note/new_note.py --name General_Topology --abbreviation GT \\
    --outline 大纲.md --levels part,section""",
    data=[
        ("新建的笔记", "工作区下的 <code>LaTeX_Notes/&lt;笔记名&gt;/</code>"),
        ("读的模板", "<code>Template/Math-Note/</code>（可在表单里改）"),
        ("远程账户名", "<code>manager.conf</code>"),
        ("装进新仓库的 pre-commit 钩子", "<code>tools/check_sensitive/pre-commit</code>"),
    ],
    warn="「只预演」是本工具唯一的保护措施 —— 去掉勾选后它会真的建目录、改文件、执行 git init。"
         "第一次用某本新笔记时，先把预演清单从头看到尾。",
    qa=[
        ("提示「笔记名不合法」",
         "只允许字母开头，后面可跟字母、数字、下划线、连字符。中文名要先转成英文（GitHub 仓库名同样限制）。"),
        ("大纲里写了 <code>\\input{...}</code>，为什么生成时被跳过？",
         "工具会判重：同一文件已在别处 import 就不再插入。若确实要插两次，先在 md 里删掉重复项。"),
        ("建完编译报错，说 structure.sty 找不到",
         "模板目录选错了，或模板被移动。检查表单里的「模板目录」，或看 <code>Template/Math-Note/</code> 是否存在。"),
        ("能不能不建 git 仓库，只建目录？",
         "可以手工复制模板，但会丢掉钩子安装与标题转义。建议还是走工具。"),
        ("生成的中文标题为什么带了反斜杠？",
         "那是 LaTeX 转义：<code>_</code>、<code>&amp;</code>、<code>%</code> 在 <code>\\title</code> 里必须转义，否则编译失败。正常现象。"),
    ],
    related=["6. 大纲工具", "3. 符号库管理", "2. 笔记工作区管理"],
)

add(
    slug="06-outline", no=6, group="创建与维护",
    title="6. 大纲工具",
    lead="三种事：校验已有大纲 md 的层级是否自洽、从一本笔记反向导出大纲、把缩进清单转成规范 md。",
    entry="创建与维护 → 卡片「大纲工具」→ 选操作 → 执行",
    cli="python tools/outline_tool/outline_tool.py",
    image="tool-06.png",
    caption="三种模式对应三种输入框，切换后就只剩相关的几项。",
    when=[
        "大纲是从别处抄来的，层级缩进乱，想知道哪里不自洽。",
        "笔记写了一部分，想把现有章节结构导回大纲，继续往下规划。",
        "手上只有一份缩进清单（目录名 | 中译名），要转成能喂给「新建笔记」的 md。",
    ],
    steps=[
        "选模式：校验 / 导出 / 从清单新建。",
        "校验：选 md 文件；勾「把推断的层级写回 md」才会改文件，否则只报问题。",
        "导出：选笔记目录；输出路径留空时写在笔记目录里。",
        "从清单新建：选清单文件，生成规范 md。",
    ],
    fields=[
        ("操作", "校验大纲 / 导出大纲 / 从清单新建。"),
        ("大纲文件", "校验用。支持 <code>levels:</code> 头部元信息与缩进层级。"),
        ("把推断的层级写回 md", "默认关。开启后会把推断出的层级实际写进文件。"),
        ("笔记目录", "导出用。读 <code>main.tex</code> 的 <code>\\part</code> / <code>\\chapter</code> / <code>\\section</code> 结构。"),
        ("输出文件", "可空。留空写在笔记目录下；已存在且内容不同会先留 <code>.bak</code>。"),
        ("清单文件", "格式：每行 <code>目录名 | 中译名</code>，用缩进表示层级，单独一行 <code>END</code> 结束。"),
    ],
    cli_more="""python tools/outline_tool/outline_tool.py --check 大纲.md
python tools/outline_tool/outline_tool.py --check 大纲.md --fix
python tools/outline_tool/outline_tool.py --export LaTeX_Notes/General_Topology""",
    data=[
        ("读出的大纲", "笔记目录下的 <code>main.tex</code> 与各级 <code>index.tex</code>"),
        ("写出的 md", "由「输出文件」决定，默认写在笔记目录"),
        ("备份", "覆盖前生成 <code>*.bak</code>"),
    ],
    qa=[
        ("校验报「层级跳跃」",
         "例如 <code>part</code> 直接接 <code>subsection</code>。这会让 LaTeX 的编号与目录错乱，补一层 section 即可。"),
        ("勾了写回但文件没变",
         "推断的层级与现状本来就一致时，不做任何写入。看结果里的「无变化」条目。"),
        ("导出的章节顺序和我预期的不同",
         "导出按 <code>\\input</code> 的实际顺序走，不是按文件名排序。"),
        ("清单里的中文名可以省略吗？",
         "可以，写成 <code>Basic_definitions</code> 一行也行；省了就用目录名当标题。"),
        ("为什么大纲里的 <code>*</code>（星号节）没出现在导出结果里？",
         "带星号的标题不编号、不进目录，导出时会被跳过。导引与小结就属于这一类。"),
    ],
    related=["5. 新建笔记", "7. 单本笔记工具"],
)

add(
    slug="07-note-tools", no=7, group="创建与维护",
    title="7. 单本笔记工具",
    lead="对某一本书做三件事：提交推送、切换习题编排模式、补导引与小结的骨架。",
    entry="创建与维护 → 卡片「单本笔记工具」→ 选书与动作 → 执行",
    cli="python tools/note_tools/note_tools.py",
    image="tool-07.png",
    caption="先选书，再选动作；「补导引与小结」会多出范围与免确认两项。",
    when=[
        "只改了一本书，不想用批量提交（免得把别的仓库一起动）。",
        "想给某一章切到「习题模式」（题目与答案分开编排）。",
        "某一层的正文已经写完，要补上该层的导引与小结骨架。",
    ],
    steps=[
        "在「笔记」下拉里选一本书（列表来自当前笔记根下含 <code>main.tex</code> 的目录）。",
        "选动作：提交并推送 / 切换习题编排模式 / 补导引与小结。",
        "补导引与小结时选范围（both / intro / summary）。",
        "「免确认直接写入」默认不勾，勾了才跳过逐项确认。",
    ],
    fields=[
        ("笔记", "下拉选择，来自实时扫描，不会列出已删除的书。"),
        ("动作", "三选一。"),
        ("补哪些", "both = 导引与小结都补；intro 只补导引；summary 只补小结。"),
        ("免确认直接写入", "关掉后每处写入前都会列出来问一次。默认关。"),
    ],
    cli_more="""python tools/note_tools/note_tools.py --note General_Topology --action commit
python tools/note_tools/note_tools.py --note General_Topology --action intro-summary --scope both
python tools/note_tools/note_tools.py --note General_Topology --action exercise""",
    data=[
        ("改的文件", "该笔记目录下的 <code>index.tex</code> / <code>main.tex</code> / <code>structure.sty</code>"),
        ("读的配置", "<code>manager.conf</code>"),
    ],
    warn="补导引与小结会插入 <code>\\section*</code> 与 <code>\\unnumberedsection</code> 骨架。按项目约定，"
         "这些块应保持注释状态、只在正在写的那一层打开 —— 工具插入后不会自动注释，记得手工收紧。",
    qa=[
        ("下拉里没有我要的书",
         "扫描规则是「笔记根下含 <code>main.tex</code> 的目录」。新书还没建 <code>main.tex</code> 就不会出现，"
         "先用「新建笔记」。"),
        ("补小结时报「正文没有 \\label」",
         "小结里的 <code>\\ref</code> / <code>\\cref</code> 需要正文有对应 label。缺 label 时只生成标题不生成引用。"),
        ("提交后远程没更新",
         "看结果里是否写了 push 失败。常见原因是远程有别人的提交，需要先拉。"),
        ("习题模式会不会删掉我的正文？",
         "不会删，只是把题目与解答分到不同文件并调整入口。改动前有 git 兜底，建议先提交一次。"),
    ],
    related=["2. 笔记工作区管理", "6. 大纲工具", "9. 仓库体检"],
)

add(
    slug="08-clean-aux", no=8, group="创建与维护",
    title="8. 清理编译产物",
    lead="删掉 aux / log / synctex 这类可再生的中间文件。只在「有 .tex 源」的目录里动手。",
    entry="创建与维护 → 卡片「清理编译产物」→ 选区域 → 执行",
    cli="python tools/clean_aux/clean_aux.py",
    image="tool-08.png",
    caption="默认扫 LaTeX_Notes，列出目录 / 文件数 / 大小 / 类型；不勾「真正删除」就只是清单。",
    when=[
        "编译产物攒了几百兆，想清一清。",
        "仓库体检提示「误跟踪了编译产物」，想知道到底有哪些。",
        "换机器前想瘦身，但不想误删笔记正文。",
    ],
    steps=[
        "选扫描区域（整个工作区 / LaTeX_Notes / Template / Tools）。",
        "先不勾「真正删除」，执行，看清单。",
        "确认清单里没有想留的东西，再勾「真正删除」执行一次。",
    ],
    fields=[
        ("扫描区域", "默认 LaTeX_Notes；Tools 区域指工具集自身。"),
        ("连 PDF 一起删", "只删「与同目录某个 <code>.tex</code> 同名」的 PDF，不会碰下载的电子书。"),
        ("真正删除", "不勾只列清单。这是唯一的安全阀。"),
    ],
    cli_more="""python tools/clean_aux/clean_aux.py --dry-run
python tools/clean_aux/clean_aux.py --area LaTeX_Notes --write""",
    data=[
        ("删除范围", "只动扩展名在清单里的中间产物；<code>outputs/</code>、<code>SkillProjects/</code>、"
                  "<code>_logs/</code>、<code>_state/</code> 默认跳过"),
        ("不动的东西", ".tex 源、图片、PDF 电子书、转写日志"),
    ],
    warn="这个工具会真删文件，且不进回收站。第一次用某个区域时，务必先跑一遍不勾「真正删除」的清单。",
    qa=[
        ("清单里有我不认识的文件",
         "看「类型」列：<code>aux</code> / <code>log</code> / <code>synctex</code> 都可再生。<code>fdb_latexmk</code> 是"
         "latexmk 的依赖记录，删了只是下次全量编译。"),
        ("能恢复吗？",
         "不能，不进回收站。所以清单必须先看。真要保险，先提交一次 git。"),
        ("为什么 <code>outputs/</code> 里的 log 没被清？",
         "那里混着转写日志与运行日志，不是 LaTeX 产物。工具只在「同目录有 .tex」的地方动手。"),
        ("删完编译变慢了",
         "正常。latexmk 的增量信息（<code>fdb_latexmk</code> / <code>fls</code>）被清掉了，下一次是全量编译。"),
    ],
    related=["9. 仓库体检", "12. 提交本工具集"],
)

add(
    slug="09-repo-check", no=9, group="信息安全与提交",
    title="9. 仓库体检",
    lead="一次看完：规范副本是否一致、有没有误跟踪编译产物、哪些仓库还有未提交改动。",
    entry="信息安全与提交 → 卡片「仓库体检」→ 选区域 → 执行",
    cli="python tools/repo_check/repo_check.py",
    image="tool-09.png",
    caption="每个仓库一行，「结果」列写明通过还是具体问题。",
    when=[
        "提交前想确认没把 aux/log 之类的东西跟踪进去。",
        "怀疑某个仓库的 <code>项目规范.md</code> 与原件不一致。",
        "接手别人的工作区，想快速摸清哪些仓库是干净的。",
    ],
    steps=[
        "选检查区域（整个工作区最快也最全）。",
        "执行，逐行看「结果」列。",
        "有问题的那几行会写明是「规范副本不一致」「误跟踪编译产物」还是「有未提交改动」。",
        "要修就先按提示改；规范副本问题可以直接用工具 14 同步。",
    ],
    fields=[
        ("检查区域", "整个工作区 / LaTeX_Notes / Template / Tools。"),
    ],
    cli_more="python tools/repo_check/repo_check.py --area all",
    data=[
        ("读的东西", "各仓库的 <code>git status</code>、<code>git ls-files</code> 与规范副本"),
        ("不写任何文件", "纯只读检查"),
    ],
    qa=[
        ("提示「误跟踪编译产物」怎么办？",
         "用 <code>git rm --cached</code> 把它们移出版本控制，并确认 <code>.gitignore</code> 覆盖了这些扩展名。"
         "工具只报警，不会自己改索引。"),
        ("「规范副本不一致」是指哪份文件？",
         "<code>项目规范.md</code>。原件在工作区根，副本在若干仓库里。用工具 14 同步，方向恒为原件 → 副本。"),
        ("中文文件名的仓库被跳过了？",
         "旧版本有 <code>core.quotepath</code> 的坑，已修。若仍跳过，检查仓库是否是合法 git 仓库。"),
        ("为什么 Tools 自己也列出来了？",
         "它就是一个仓库。检查它没问题；但注意它的规范副本也可能不一致。"),
    ],
    related=["14. 项目规范副本一致性", "8. 清理编译产物", "10. 本机信息扫描"],
)

add(
    slug="10-sensitive", no=10, group="信息安全与提交",
    title="10. 本机信息扫描",
    lead="提交前最后一道关：扫一遍暂存内容里有没有本机路径、用户名、密钥、专有词。",
    entry="信息安全与提交 → 卡片「本机信息扫描」→ 执行（默认只扫已跟踪文件）",
    cli="python tools/check_sensitive/check_sensitive.py",
    image="tool-10.png",
    caption="只有一个勾选项；不勾就扫暂存区，勾了就扫全部已跟踪文件。",
    when=[
        "准备把笔记仓库推到公开 GitHub 之前。",
        "写脚本时手滑写了绝对路径，想全库查一遍。",
        "想知道 <code>.sensitive-words.txt</code> 里的词有没有漏进某个文件。",
    ],
    steps=[
        "勾「只扫已跟踪文件」适合全量体检；不勾则只扫暂存区（提交那一刻的检查就是它）。",
        "执行。有命中会列出文件、类别、内容片段。",
        "按提示改写：本机路径换成 <code>%USERPROFILE%</code> 之类，密钥删掉，配置文件进 <code>.gitignore</code>。",
    ],
    fields=[
        ("只扫已跟踪文件", "勾上扫全部已跟踪文件（慢一些但更全）；不勾只扫 <code>git diff --cached</code>。"),
    ],
    cli_more="""python tools/check_sensitive/check_sensitive.py --tracked
python tools/check_sensitive/check_sensitive.py --dir 某目录""",
    data=[
        ("词表", "<code>tools/check_sensitive/_sensitive-words.txt</code>（可用 <code>.sensitive-words.txt</code> 逐级追加）"),
        ("钩子模板", "<code>tools/check_sensitive/pre-commit</code>"),
        ("钩子安装位置", "各仓库的 <code>.git/hooks/pre-commit</code>"),
    ],
    warn="扫描输出里会带命中的原文片段。若要贴给别人看，先把路径与用户名打码。",
    qa=[
        ("钩子明明装了，提交却没被拦？",
         "钩子是靠相对路径找脚本的。工具集目录挪过位置（例如从 <code>Tools/&lt;工具&gt;/</code> 改成 "
         "<code>Tools/tools/&lt;工具&gt;/</code>），旧钩子就找不到脚本、直接放行。重新装一次钩子即可。"),
        ("中文文件名被跳过",
         "旧版本没关 <code>core.quotepath</code>，中文名被转义成八进制，拼出的路径不存在。已修；"
         "若仍出现，确认钩子与脚本是新版本。"),
        ("误报了某个 URL",
         "<code>https://example.com/home/...</code> 这类曾因子串匹配被误判。规则已加左边界；"
         "仍误报就把具体串加到白名单或改词表。"),
        ("我能自己加要拦的词吗？",
         "可以。在仓库根或任意上级目录放 <code>.sensitive-words.txt</code>，一行一个词，脚本会逐级合并。"),
        ("<code>git commit --no-verify</code> 会跳过吗？",
         "会。这是有意的逃生口，只在你确认是误报时用。"),
    ],
    related=["9. 仓库体检", "12. 提交本工具集"],
)


add(
    slug="11-sync-paths", no=11, group="信息安全与提交",
    title="11. 配置路径检查与修复",
    lead="逐个检查各工具配置里的路径是否还有效（换了电脑、挪了目录之后特别有用），并可一键改成正确值。",
    entry="信息安全与提交 → 卡片「配置路径检查与修复」→ 执行",
    cli="python tools/sync_paths/sync_paths.py",
    image="tool-11.png",
    caption="没有参数，直接执行；每条形如「[OK] symbols.conf:6 root = …」。",
    when=[
        "把整个工作区搬到另一个盘或另一台机器之后。",
        "工具提示「笔记根目录不存在」，但目录明明在。",
        "不确定 <code>manager.conf</code> / <code>symbols.conf</code> / <code>progress.conf</code> 里的路径哪个是坏的。",
    ],
    steps=[
        "直接执行。默认只检查，不改任何文件。",
        "看输出：<code>[OK]</code> 是有效，<code>[失效]</code> 会写出键名与当前值。",
        "要修就勾「真正修复」（或命令行加 <code>--write</code>），它会按工作区位置推算正确值并写回。",
    ],
    fields=[
        ("（无字段）", "这个工具不需要参数；勾选项在命令行里是 <code>--write</code>。"),
    ],
    cli_more="""python tools/sync_paths/sync_paths.py            # 只检查
python tools/sync_paths/sync_paths.py --write    # 检查并修复""",
    data=[
        ("检查的配置", "<code>symbols/symbols.conf</code>、<code>manager/manager.conf</code>、"
                  "<code>progress/progress.conf</code>"),
        ("配置文件位置", "便携：各工具目录；安装：<code>%LOCALAPPDATA%\\LaTeX-Toolbox\\&lt;工具&gt;\\</code>"),
    ],
    qa=[
        ("显示「[失效] manager.conf:1 root = D:\\旧盘\\...」",
         "工作区搬过家。勾「真正修复」跑一次，或手工改成新路径。"),
        ("修复会不会把别的键也改掉？",
         "只改它认识的那几个键（笔记根、模板路径、cwl 路径），其余行原样保留。"),
        ("配置里留空的值算不算失效？",
         "不算。留空表示「用默认值」，工具会跳过。"),
        ("为什么某个配置文件没被检查？",
         "文件不存在就跳过 —— 说明那个工具还没配置过，先用一次它就会生成。"),
    ],
    related=["9. 仓库体检", "2. 笔记工作区管理"],
)

add(
    slug="12-commit", no=12, group="信息安全与提交",
    title="12. 提交本工具集",
    lead="把 <code>Tools/</code> 这个仓库 add → commit → push。默认预演，看到文件清单再决定。",
    entry="信息安全与提交 → 卡片「提交本工具集」→ 填说明 → 执行",
    cli="python tools/commit/commit.py",
    image="tool-12.png",
    caption="提交说明可空；「预演」默认勾着，只列出将提交的文件。",
    when=[
        "改完工具代码或文档，要把工具集本身同步到 GitHub。",
        "想确认这次改动到底涉及多少文件。",
        "需要顺带把改动记进 CHANGELOG。",
    ],
    steps=[
        "填一句提交说明（留空用默认文案）。",
        "保持「预演」勾选，执行，看文件清单。",
        "确认无误，去掉「预演」再执行；需要跳过确认就勾「跳过确认」。",
        "要写 CHANGELOG 就用命令行加 <code>--log</code>。",
    ],
    fields=[
        ("提交说明", "写进 commit message。"),
        ("预演（不真的提交）", "默认开。只列出将提交的文件，不动 git。"),
        ("跳过确认直接提交", "默认关。开了会一路走到 push。"),
    ],
    cli_more="""python tools/commit/commit.py --dry-run
python tools/commit/commit.py 'fix: 修 xx'
python tools/commit/commit.py --log 'feat: 加了 xx'""",
    data=[
        ("被提交的仓库", "程序目录（<code>Tools/</code>）这个 git 仓库"),
        ("CHANGELOG", "程序目录下的 <code>CHANGELOG.md</code>"),
        ("防护", "提交前自动跑一次本机信息扫描（工具 10）"),
    ],
    warn="这是唯一会 push 的工具。预演清单里如果出现 <code>config.json</code>、<code>*.conf</code>、"
         "<code>_data/</code> 这类本机数据，说明 <code>.gitignore</code> 漏了规则，先补规则再提交。",
    qa=[
        ("提示「没有改动，无需提交」",
         "工作区是干净的。若你刚改过文件，检查是不是改在了 <code>_build/</code>、<code>_dbg/</code> 这类被忽略的目录里。"),
        ("push 被拒（non-fast-forward）",
         "远程有你本地没有的提交。先 <code>git pull --rebase</code>，再提交。"),
        ("提交被钩子拦下",
         "那是本机信息扫描。按提示改；确属误报再 <code>--no-verify</code>。"),
        ("预演和实际提交的文件数不一样？",
         "预演之后你又改了文件。重新预演一次。"),
    ],
    related=["10. 本机信息扫描", "9. 仓库体检"],
)

add(
    slug="13-video2text", no=13, group="素材与转写",
    title="13. 视频转文字",
    lead="给一个视频链接，优先取字幕；没有字幕就用本地 whisper 转写。产物按合集归档，可断点续做。",
    entry="素材与转写 → 卡片「视频转文字」→ 选操作 → 执行",
    cli="python tools/video2text/video2text.py",
    image="tool-13.png",
    caption="默认操作是「列出合集」（只读）；选「转写视频」才会露出二十来项参数。",
    when=[
        "看到一门课的录像，想要可检索的文字稿。",
        "想先把已转写的合集列出来，看看哪几集还缺。",
        "批量补做失败的集数，或把整个合集导出成一个 ZIP。",
    ],
    steps=[
        "先选「列出合集」执行，确认已有归档与进度。",
        "选「转写视频」，填 BV 号或链接，取源方式保持「默认」。",
        "默认会展开全部分 P；只想要当前这一集就勾「只处理当前视频」。",
        "登录态过期时，先在工作台里跑一次扫码登录（见下方 Q&A）。",
    ],
    fields=[
        ("操作", "列出合集 / 转写视频 / 补做失败项 / 导出合集 ZIP / 同步标题文件夹 / 锁状态诊断。"),
        ("视频地址", "BV 号或完整链接。"),
        ("取源方式", "默认（先字幕后 whisper）/ subtitles（只要字幕）/ auto / whisper（强制转写）。"),
        ("whisper 模型", "默认 medium。换 small 更快、更糊。"),
        ("设备 / 计算精度", "CPU 用 int8；有 N 卡可试 cuda + float16。"),
        ("忽略字幕强制转写", "字幕质量差时用。"),
        ("保留音频", "转完留着音频文件；默认删除。"),
        ("强制重做", "连已成功的一起重做，用于换模型重转。"),
    ],
    cli_more="""python tools/video2text/video2text.py --collections
python tools/video2text/video2text.py BV1xx411c7mD
python tools/video2text/video2text.py --only-failed
python tools/video2text/video2text.py --export-collection 合集ID --export-to out.zip""",
    data=[
        ("模型 / cookie / 浏览器档案 / 转写产物", "便携：<code>tools/video2text/_data/</code>；"
                                          "安装：<code>%LOCALAPPDATA%\\LaTeX-Toolbox\\video2text\\_data\\</code>"),
        ("工具配置", "同目录的 <code>video2text.conf</code>"),
        ("模型体积", "medium 约 1.5 GB；换成 large 会更大"),
    ],
    warn="whisper 模型与浏览器档案加起来可能有几个 GB。换机器时不要连 <code>_data</code> 一起拷进版本库 —— "
         "它已经在 <code>.gitignore</code> 里。",
    qa=[
        ("提示「未登录」或转写报 403",
         "cookie 过期了。要用扫码登录：工具菜单里有登录入口，会拉起 Edge。登录后 cookie 落在 "
         "<code>_data/cookies</code>。"),
        ("「本地模型：无」是怎么回事？",
         "模型文件不在 <code>_data/models</code> 下。要么先跑一次让它下载，要么在「本地模型目录」里指到已有模型。"),
        ("转写很慢",
         "CPU 上 medium 大约是音长的 1–2 倍。想快就把模型换成 small，或勾「关闭静音过滤」以外的东西别乱动。"),
        ("中途断了，要重来吗？",
         "不用。默认断点续做，重跑同一条命令会跳过已完成的集。"),
        ("导出的 ZIP 里文件名是乱的",
         "先用「同步标题文件夹」把集标题对齐，再导出。"),
        ("为什么有些集只有几行字？",
         "那集只拿到了字幕（可能不完整）。看结果里的「取源」列，需要完整稿就勾「忽略字幕强制转写」。"),
    ],
    related=["4. 写作工作台", "5. 新建笔记"],
)

add(
    slug="14-spec-sync", no=14, group="信息安全与提交",
    title="14. 项目规范副本一致性",
    lead="比对工作区根的 <code>项目规范.md</code> 与各仓库里的副本是否逐字节一致，并把原件同步过去。",
    entry="信息安全与提交 → 卡片「项目规范副本一致性」→ 选模式 → 执行",
    cli="python tools/spec_sync/spec_sync.py",
    image="tool-14.png",
    caption="三档模式：只检查 / 直接同步 / 防呆同步。",
    when=[
        "改完项目规范，要把它同步到 10 个仓库里。",
        "不确定哪个仓库的副本还是旧的。",
        "想确认副本没被别人单独改过（防呆同步会先比对再写）。",
    ],
    steps=[
        "先选「只检查」，执行，看哪些副本不一致。",
        "确认原件是最新的，再选「防呆同步」执行。",
        "方向恒为 原件 → 副本，不会反向覆盖。",
    ],
    fields=[
        ("模式", "只检查 / 直接同步 / 防呆同步（先比对再写，推荐）。"),
    ],
    cli_more="""python tools/spec_sync/spec_sync.py --check
python tools/spec_sync/spec_sync.py --sync --safe""",
    data=[
        ("原件", "工作区根的 <code>项目规范.md</code>"),
        ("副本", "各仓库里的同名文件（配对关系由工具内置）"),
    ],
    qa=[
        ("某个仓库的副本被改过，同步会覆盖吗？",
         "防呆同步会先报差异再写；直接同步则无条件覆盖。所以默认先用「只检查」。"),
        ("能不能反向同步（副本 → 原件）？",
         "不能，这是刻意的设计：原件是唯一真源，反向会引入多源。"),
        ("提示某个仓库找不到副本",
         "该仓库没装过规范文件。要装的话，工具会新建一份。"),
    ],
    related=["9. 仓库体检"],
)

add(
    slug="15-pdf-upright", no=15, group="PDF 处理",
    title="15. PDF 转正",
    lead="把「横版课件被打印成 A4 纵向、内容转了 90°」的 PDF 裁白边、转成 16:9，不重新编码。",
    entry="PDF 处理 → 卡片「PDF 转正」→ 选文件或目录 → 执行",
    cli="python tools/pdf_upright/pdf_upright.py",
    image="tool-15.png",
    caption="输入默认指向工作区的 Exam 目录；「预演」默认勾着。",
    when=[
        "课件在阅读器里要横着看，或者转正后留大片白边。",
        "打印出来是竖版、内容侧躺。",
        "批量处理一整门课的 PDF。",
    ],
    steps=[
        "选 PDF 文件或目录（目录会展开，默认含子目录）。",
        "保持「预演」勾选，执行，看每份的页数与判定结论。",
        "确认后取消「预演」再执行。默认就地覆盖，原件备份到系统临时目录。",
        "转出来是倒立的，勾「逆时针转正」再来一次。",
    ],
    fields=[
        ("PDF 文件或目录", "两者都接受。"),
        ("含子目录", "默认开。"),
        ("另存目录", "留空则就地覆盖原文件；`-o` 指向源目录会被拒绝（语义是「原件不动」）。"),
        ("逆时针转正", "默认顺时针 90°；转出来倒立就换这个。"),
        ("预演（不真的转）", "默认开。只报告每份的判断，不写文件。"),
    ],
    cli_more="""python tools/pdf_upright/pdf_upright.py 某课件.pdf
python tools/pdf_upright/pdf_upright.py Exam -r
python tools/pdf_upright/pdf_upright.py Exam -r -o D:/输出目录""",
    data=[
        ("原件备份", "系统临时目录（覆盖前自动备份）"),
        ("依赖", "<code>pymupdf</code>；缺了会自动找装了它的解释器重跑"),
    ],
    warn="默认是**就地覆盖**。虽然会先备份到临时目录，但临时目录会被系统清理 —— 重要的原件先自己留一份。",
    qa=[
        ("提示「当前 Python 里没有 PyMuPDF」",
         "本机工具 venv 里装了它，正常不会出现。若真出现，说明面板找错了解释器：在设置页确认「工具解释器」，"
         "或用环境变量 <code>PDF_UPRIGHT_PYTHON</code> 指一个装了 pymupdf 的 python。"),
        ("有些页没转，有些转了",
         "判定依据是「整页贴图占页面面积 40% 以上」，扫描件与纯文字页处理方式不同。看预演里的「结论」列。"),
        ("转完反而变成倒的",
         "源文件原本是逆时针躺的。勾「逆时针转正」重跑。注意这时原件已被覆盖过，建议从备份恢复再转。"),
        ("画质会下降吗？",
         "不会。只改页面框与旋转标记，不重新编码图像。"),
        ("能处理整本扫描书吗？",
         "能，但它只做「转正 + 裁白边」，不做 OCR 与纠偏。扫描书更需要 OCR，那是另一条线。"),
    ],
    related=["13. 视频转文字"],
)

add(
    slug="16-watch-notes", no=16, group="运行监测",
    title="16. 笔记目录监测",
    lead="盯着一个仓库，有改动就自动提交推送，并按条数上限裁剪历史，让提交记录不无限增长。",
    entry="运行监测 → 卡片「笔记目录监测」→ 选仓库与间隔 → 执行",
    cli="python tools/watch_notes/watch_notes.py",
    image="tool-16.png",
    caption="「只跑一轮」默认勾着，适合先试一次看行为；长期跑要去掉这个勾。",
    when=[
        "写作时不想频繁手动提交，希望几分钟自动存一次。",
        "自动提交攒了几百条历史，想把旧记录裁掉只留最近 N 条。",
        "想先试跑一轮，确认它会提交什么、不会误推。",
    ],
    steps=[
        "选监测仓库（下拉来自笔记根下各仓库）。",
        "设间隔：检测 300 秒、裁剪检查 900 秒、保留 20 条。",
        "先保持「只跑一轮」执行一次，看日志里它做了什么。",
        "确认无误后去掉该勾，让它常驻；关掉窗口即停止。",
    ],
    fields=[
        ("监测仓库", "一次盯一个仓库。"),
        ("检测间隔", "多久看一次改动，最小 10 秒。"),
        ("裁剪检查间隔", "多久检查一次历史条数，最小 10 秒。"),
        ("历史保留条数", "超出就按条数上限一次裁到该值。"),
        ("只跑一轮", "默认开。测行为时用，长期跑要关。"),
        ("只提交不推送", "想先在本地攒着时用。注意这只影响推送，裁剪仍然只在推送成功后做。"),
    ],
    cli_more="""python tools/watch_notes/watch_notes.py --dir LaTeX_Notes/Algebra --once
python tools/watch_notes/watch_notes.py --dir LaTeX_Notes/Algebra --keep 20""",
    data=[
        ("状态与日志", "便携：<code>tools/watch_notes/_state</code> 与 <code>_logs</code>；"
                  "安装：<code>%LOCALAPPDATA%\\LaTeX-Toolbox\\watch_notes\\</code>"),
        ("锁文件", "同一状态目录下的 <code>watch-*.lock</code>"),
    ],
    warn="裁剪历史会**改写本地 git 历史**（保留内容、提交信息与时间，只断掉更早的父链）。"
         "如果远程已有那些提交，裁剪后本地与远程会分叉，需要强推。别在没有备份的仓库上乱试。",
    qa=[
        ("设了「每 15 分钟删一次」，历史还是越来越长",
         "旧版语义是「删最早一条」，而提交速度比删除快，永远追不上。现在改成「按条数上限一次裁到该值」，"
         "配 <code>--keep</code> 用。"),
        ("裁剪后 push 被拒",
         "历史被改写了，远程还是旧链。确认本地内容无误后 <code>git push --force-with-lease</code>。"),
        ("日志里一直写「无改动」",
         "正常。它只在检测到改动时才提交。"),
        ("关掉窗口后还在跑吗？",
         "不会。「只跑一轮」之外的模式是前台常驻，窗口关掉进程就结束。"),
        ("为什么裁剪没发生？",
         "只在推送成功后裁剪。设了「只提交不推送」时不会裁。"),
    ],
    related=["2. 笔记工作区管理", "9. 仓库体检"],
)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "img").mkdir(exist_ok=True)

    docs = DOCS
    for i, d in enumerate(docs):
        prev = (docs[i - 1]["slug"], docs[i - 1]["title"]) if i > 0 else None
        nxt = (docs[i + 1]["slug"], docs[i + 1]["title"]) if i < len(docs) - 1 else None
        (OUT / f"{d['slug']}.html").write_text(page(d, prev, nxt), encoding="utf-8", newline="")

    (OUT / "index.html").write_text(index_page(docs), encoding="utf-8", newline="")

    made = 0
    for name, slug, desc in GROUPS:
        members = [d for d in docs if d["group"] == name]
        if not members:
            continue
        (OUT / f"{slug}.html").write_text(
            group_page(name, desc, members), encoding="utf-8", newline="")
        made += 1

    print(f"生成 {len(docs)} 篇工具文档 + {made} 篇板块 + 1 篇总览，输出到 {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
