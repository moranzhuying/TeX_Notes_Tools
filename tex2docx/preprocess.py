#!/usr/bin/env python3
"""LaTeX -> Word 预处理：把 Pandoc 认不出的 LaTeX 构造改写成它能处理的形式。

Pandoc 在数学论文上的四个失手点：
  1. tcolorbox 定理环境（\\newtcbtheorem）—— 完全不认，内容会散架
  2. 定理的交叉引用 —— Pandoc 只给 section/figure/table 编号，
     定理上的 \\label 会被丢弃，\\ref 于是退化成裸标签
  3. cleveref 的 \\cref/\\Cref —— 同上
  4. structure.sty 的自定义宏 —— 原样留成文本

本脚本的策略：定理按节编号（1.1、1.2…）写成静态文本，并把 label 收集起来，
把 \\ref 直接替换成编号。这样 Word 里的引用是死文本，但内容对、不会再出乱码。

用法：
  python preprocess.py main.tex -o main_flat.tex
  python preprocess.py main.tex --sty structure.sty -o main_flat.tex
  python preprocess.py main.tex --pandoc out.docx --reference-doc 学校模板.docx

只依赖标准库。中间产物是纯文本 .tex，可人工复核后再手动跑 pandoc。
"""

import argparse
import os
import re
import subprocess
import sys

# ---------------------------------------------------------------- 宏解析

RE_NEWCMD = re.compile(
    r"\\(?:newcommand|providecommand|renewcommand)\*?"
    r"(?:\{\\([A-Za-z@]+)\}|\\([A-Za-z@]+))"
    r"(?:\[(\d)\])?"
    r"\{((?:[^{}]|\{[^{}]*\})*)\}"
)


def parse_macros(sty_text):
    """提取无参宏定义，返回 ({名字: 展开体}, [跳过的名字])。"""
    defs, skipped = {}, []
    for m in RE_NEWCMD.finditer(sty_text):
        name = m.group(1) or m.group(2)
        argc = m.group(3)
        body = m.group(4).strip()
        if (argc and argc != "0") or not body or "#" in body:
            skipped.append(name)
            continue
        defs[name] = body
    return defs, skipped


def expand_macros(text, defs, rounds=6):
    """反复替换直到收敛，处理 \\N -> \\mathbb{N} 这类链式定义。"""
    total = 0
    for _ in range(rounds):
        changed = 0
        for name, body in defs.items():
            pat = re.compile(r"\\" + re.escape(name) + r"(?![A-Za-z])")
            text, n = pat.subn(lambda _m, b=body: b, text)
            changed += n
        total += changed
        if not changed:
            break
    return text, total


# ---------------------------------------------------------------- 环境分类

RE_TCBTHM = re.compile(
    r"\\newtcbtheorem\s*(?:\[[^\]]*\])?\s*\{([A-Za-z]+)\}\s*\{([^}]*)\}")
RE_TCBBOX = re.compile(r"\\newtcolorbox\s*\{([A-Za-z]+)\}")

FALLBACK_CN = {
    "theorem": "定理", "definition": "定义", "lemma": "引理",
    "proposition": "命题", "corollary": "推论", "remark": "注记",
    "example": "例", "proof": "证明", "exercise": "习题",
    "answer": "解", "solution": "解", "hint": "提示", "note": "注",
}


def collect_envs(sty_text):
    """返回 (带编号的定理环境, 不带编号的盒子环境)，都是 {环境名: 中文名}。"""
    thm, box = {}, {}
    for m in RE_TCBTHM.finditer(sty_text):
        name = m.group(1)
        thm[name] = m.group(2).strip() or FALLBACK_CN.get(name, name)
    for m in RE_TCBBOX.finditer(sty_text):
        name = m.group(1)
        box[name] = FALLBACK_CN.get(name, name)
    return thm, box


def number_theorems(text, thm_envs):
    """按节给定理编号并写成静态文本，同时收集 {label: 编号}。

    \\begin{theorem}{谱定理}{thm:spec} -> **定理 1.1（谱定理）**\\label{thm:spec}
    """
    alt = "|".join(re.escape(e) for e in thm_envs)
    token = re.compile(
        r"(\\section\*?\{[^}]*\})"
        r"|\\begin\{(" + alt + r")\}\s*\{([^{}]*)\}\s*\{([^{}]*)\}"
        r"|\\begin\{(" + alt + r")\}")
    state = {"sec": 0, "cnt": 0}
    labels = {}

    def repl(m):
        if m.group(1):
            state["sec"] += 1
            state["cnt"] = 0
            return m.group(1)
        if m.group(5):
            # 无参 \begin{env}：也补上编号并转成静态文本，
            # 否则后面的 \end{env} 会被统一删掉，留下孤立的 \begin
            env = m.group(5)
            state["cnt"] += 1
            num = f'{state["sec"]}.{state["cnt"]}'
            cn = thm_envs.get(env, FALLBACK_CN.get(env, env))
            return "\n\n" + f"**{cn} {num}**" + "\\quad "
        env = m.group(2)
        title = m.group(3).strip()
        label = m.group(4).strip()
        state["cnt"] += 1
        num = f'{state["sec"]}.{state["cnt"]}'
        if label:
            labels[label] = num
        cn = thm_envs.get(env, FALLBACK_CN.get(env, env))
        head = f"**{cn} {num}**" + (f"（{title}）" if title else "")
        tail = f"\\label{{{label}}}" if label else ""
        return "\n\n" + head + "\\quad " + tail

    result = token.sub(repl, text)
    if thm_envs:
        # 定理的 \end 也要吃掉，否则 Pandoc 会撞到孤立的 \end{theorem}
        end_pat = re.compile(r"\\end\{(" + alt + r")\}")
        result = end_pat.sub("\n\n", result)
    return result, labels


def convert_plain_envs(text, box_envs):
    """无编号盒子环境（proof / answer / hint …）-> 粗体标题段落。"""
    count = 0
    for env, cn in box_envs.items():
        e = re.escape(env)

        def repl_opt(m, c=cn):
            return "\n\n" + f"**{c}（{m.group(1)}）**" + "\\quad "

        text, n1 = re.subn(r"\\begin\{" + e + r"\}\s*\[([^\]]*)\]", repl_opt, text)

        def repl_plain(_m, c=cn):
            return "\n\n" + f"**{c}**" + "\\quad "

        text, n2 = re.subn(r"\\begin\{" + e + r"\}", repl_plain, text)

        end_text = "\n\n" + ("$\\square$" if env in ("proof", "answer", "solution", "sketch") else "") + "\n\n"
        text, n3 = re.subn(r"\\end\{" + e + r"\}", lambda _m, x=end_text: x, text)
        count += n1 + n2 + n3
    return text, count


# ---------------------------------------------------------------- 其余改写

def fix_cleveref(text):
    """\\cref/\\Cref/\\autoref -> \\ref。"""
    n = 0
    for cmd in ("cref", "Cref", "autoref", "Autoref", "nameref"):
        text, k = re.subn(r"\\" + cmd + r"\{([^}]*)\}",
                          lambda m: "\\ref{" + m.group(1) + "}", text)
        n += k
    return text, n


def resolve_refs(text, labels):
    """把已编号定理的 \\ref 替换成编号；查不到的原样留给 Pandoc。"""
    n = 0

    def repl(m):
        nonlocal n
        key = m.group(1).strip()
        if key in labels:
            n += 1
            return labels[key]
        return m.group(0)

    return re.sub(r"\\ref\{([^}]*)\}", repl, text), n


def fix_unnumbered_section(text):
    """\\unnumberedsection{级别}{标题} -> \\级别*{标题}。"""
    return re.subn(r"\\unnumberedsection\s*\{([^{}]*)\}\s*\{([^{}]*)\}",
                   lambda m: "\\" + m.group(1).strip() + "*{" + m.group(2) + "}",
                   text)


DROP_CMDS = [
    "medskip", "bigskip", "smallskip", "noindent", "indent",
    "centering", "raggedright", "raggedleft", "hfill", "hfil", "vfill",
    "newpage", "clearpage", "tableofcontents", "maketitle",
    "pagestyle", "thispagestyle", "phantomsection",
    # ctex / 自定义目录守卫
    "starttoctoc", "stoptoc", "starttoc", "addcontentsline",
]


def drop_noise(text):
    n = 0
    # 带三个参数的目录登记命令，必须整体删（只删命令名会留下 {section}{标题} 残渣）
    text, k0 = re.subn(r"\\addcontentsline\{[^{}]*\}\{[^{}]*\}\{[^{}]*\}", "", text)
    # 多栏环境：Pandoc 不认，拆掉标记即可
    text, k1 = re.subn(r"\\begin\{multicols\}\{[^{}]*\}|\\end\{multicols\}", "", text)
    text, k2 = re.subn(r"\\begin\{multicols\*\}\{[^{}]*\}|\\end\{multicols\*\}", "", text)
    n += k0 + k1 + k2

    for cmd in DROP_CMDS:
        text, k = re.subn(r"\\" + cmd + r"\b(\[[^\]]*\])?(\{[^{}]*\})?", "", text)
        n += k
    text, k3 = re.subn(r"\\vspace\*?\{[^{}]*\}", "", text)
    text, k4 = re.subn(r"\\hspace\*?\{[^{}]*\}", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text, n + k3 + k4


def flatten_inputs(main_path, root=None, depth=0, seen=None):
    """递归展开 \\input / \\include，路径以主文件目录为基准（同 LaTeX）。"""
    seen = seen if seen is not None else set()
    root = root or os.path.dirname(os.path.abspath(main_path))
    text = open(main_path, encoding="utf-8").read()

    def repl(m):
        target = m.group(1).strip()
        if not target.lower().endswith(".tex"):
            target += ".tex"
        path = os.path.normpath(os.path.join(root, target))
        if not os.path.exists(path):
            print(f"  [跳过] 找不到 {target}", file=sys.stderr)
            return ""
        if path in seen or depth > 12:
            print(f"  [跳过] 循环引用 {target}", file=sys.stderr)
            return ""
        seen.add(path)
        return flatten_inputs(path, root, depth + 1, seen)

    return re.sub(r"\\(?:input|include)\{([^}]*)\}", repl, text)


def strip_preamble(text):
    m = re.search(r"\\begin\{document\}(.*?)\\end\{document\}", text, re.S)
    return m.group(1) if m else text


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="LaTeX -> Word 预处理")
    ap.add_argument("tex", help="主 tex 文件")
    ap.add_argument("-o", "--output", help="输出的中间 tex（默认 <名字>_flat.tex）")
    ap.add_argument("--sty", help="structure.sty 路径（默认找同目录）")
    ap.add_argument("--pandoc", metavar="DOCX", help="预处理后直接跑 pandoc 出 docx")
    ap.add_argument("--reference-doc", help="套用 Word 模板样式")
    args = ap.parse_args()

    base = os.path.dirname(os.path.abspath(args.tex))
    sty_path = args.sty or os.path.join(base, "structure.sty")

    macro_defs, skipped = {}, []
    thm_envs, box_envs = {}, {}
    if os.path.exists(sty_path):
        sty_text = open(sty_path, encoding="utf-8").read()
        macro_defs, skipped = parse_macros(sty_text)
        thm_envs, box_envs = collect_envs(sty_text)
        print(f"宏解析：{len(macro_defs)} 个可展开，{len(skipped)} 个跳过（带参/复杂）")
        print(f"定理环境：{len(thm_envs)} 个带编号，{len(box_envs)} 个盒子 -> "
              + " ".join(f"{k}={v}" for k, v in list(thm_envs.items())[:5]) + " …")
    else:
        print(f"[警告] 没找到 {sty_path}，跳过宏展开与定理转换", file=sys.stderr)

    text = strip_preamble(flatten_inputs(args.tex))

    text, labels = number_theorems(text, thm_envs)
    text, n_box = convert_plain_envs(text, box_envs)
    text, n_sec = fix_unnumbered_section(text)
    text, n_ref = fix_cleveref(text)
    text, n_macro = expand_macros(text, macro_defs)
    text, n_resolved = resolve_refs(text, labels)
    text, n_noise = drop_noise(text)

    out = args.output or re.sub(r"\.tex$", "", os.path.basename(args.tex)) + "_flat.tex"
    with open(out, "w", encoding="utf-8", newline="") as f:
        f.write(text)

    print(f"定理编号 {len(labels)} 个 | 盒子环境 {n_box} 处 | 无编号节 {n_sec} 处 | "
          f"交叉引用 {n_ref} 处 | 宏展开 {n_macro} 次 | 解析 ref {n_resolved} 处")
    print(f"中间文件：{out}")

    if skipped:
        preview = ", ".join("\\" + s for s in skipped[:8])
        print(f"未展开的宏（带参数，需人工处理）：{preview}"
              + (" …" if len(skipped) > 8 else ""))

    if args.pandoc:
        cmd = ["pandoc", out, "-o", args.pandoc,
               "--from", "latex", "--to", "docx"]
        if args.reference_doc:
            cmd += ["--reference-doc", args.reference_doc]
        print("执行：", " ".join(cmd))
        r = subprocess.run(cmd)
        if r.returncode == 0:
            print(f"已生成：{args.pandoc}")
        else:
            print(f"pandoc 失败，退出码 {r.returncode}", file=sys.stderr)
            return r.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
