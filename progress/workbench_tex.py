"""新版工作台共用 TeX 解析与统计；不读取旧面板配置或状态。"""
import re


THEOREM_ENVS = {
    "definition", "axiom", "hypothesis", "theorem", "lemma", "proposition",
    "corollary", "metatheorem", "criteria", "problem", "example", "remark",
    "exercise", "algorithm", "convention", "alarm", "sketch",
}


PROOF_ENVS = {"proof", "sketch"}


MIN_CHARS = 50


EMPTY_ENV_CHARS = 20


TITLE_RE = re.compile(r"^\s*\\(part|chapter|section|subsection|subsubsection"
                      r"|appendixchapter|appendixsubsection)\b")


COMMENT_RE = re.compile(r"^\s*%")


BEGIN_RE = re.compile(r"\\begin\{([^}]*)\}")


END_RE = re.compile(r"\\end\{([^}]*)\}")


INPUT_PREFIX = "\\input{"


TITLE_KEYS = ("part", "chapter", "section", "subsection", "subsubsection",
              "appendixchapter", "appendixsubsection")


_TITLE_RES = {k: re.compile(r"\\" + k + r"\*?\{(.*)\}\s*$") for k in TITLE_KEYS}


def parse_inputs(line):
    r"""提取一行中所有 \input{...} 的目标路径。

    必须做花括号配对：路径可能含 LaTeX 花括号，
    例如 ./Content/7_The_additive_groups_R^{n}/index
    """
    out = []
    idx = 0
    while True:
        pos = line.find(INPUT_PREFIX, idx)
        if pos < 0:
            break
        i = pos + len(INPUT_PREFIX)
        start = i
        depth = 1
        while i < len(line) and depth > 0:
            if line[i] == "{":
                depth += 1
            elif line[i] == "}":
                depth -= 1
            i += 1
        if depth == 0:
            out.append(line[start:i - 1].strip())
        idx = i
    return out


def take_group(s, start):
    """s[start] 应为 '{'。返回配对组内的内容与结束位置。"""
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return s[start + 1:i], i + 1
    return s[start + 1:], len(s)


def unwrap_cmd(s, cmd):
    r"""反复把 \cmd{...} 替换为其参数内容，保留内部文本。"""
    token = cmd + "{"
    for _ in range(200):
        p = s.find(token)
        if p < 0:
            return s
        inner, end = take_group(s, p + len(cmd))
        s = s[:p] + inner + s[end:]
    return s


ACCENT_MAP = {
    '"': {"a": "ä", "e": "ë", "i": "ï", "o": "ö", "u": "ü", "y": "ÿ",
          "A": "Ä", "E": "Ë", "I": "Ï", "O": "Ö", "U": "Ü"},
    "'": {"a": "á", "e": "é", "i": "í", "o": "ó", "u": "ú", "y": "ý",
          "c": "ć", "n": "ń", "s": "ś", "z": "ź",
          "A": "Á", "E": "É", "I": "Í", "O": "Ó", "U": "Ú", "C": "Ć", "N": "Ń"},
    "`": {"a": "à", "e": "è", "i": "ì", "o": "ò", "u": "ù",
          "A": "À", "E": "È", "I": "Ì", "O": "Ò", "U": "Ù"},
    "^": {"a": "â", "e": "ê", "i": "î", "o": "ô", "u": "û",
          "A": "Â", "E": "Ê", "I": "Î", "O": "Ô", "U": "Û"},
    "~": {"a": "ã", "n": "ñ", "o": "õ", "A": "Ã", "N": "Ñ", "O": "Õ"},
}


MATH_CMDS = {
    "leq": "≤", "le": "≤", "leqslant": "≤", "geq": "≥", "ge": "≥",
    "geqslant": "≥", "neq": "≠", "ne": "≠", "equiv": "≡", "approx": "≈",
    "sim": "∼", "simeq": "≃", "cong": "≅", "propto": "∝",
    "ll": "≪", "gg": "≫", "prec": "≺", "succ": "≻",
    "subset": "⊂", "supset": "⊃", "subseteq": "⊆", "supseteq": "⊇",
    "in": "∈", "notin": "∉", "ni": "∋",
    "cup": "∪", "cap": "∩", "setminus": "∖", "emptyset": "∅",
    "varnothing": "∅", "times": "×", "cdot": "·", "div": "÷",
    "boxplus": "⊞", "boxminus": "⊟", "boxtimes": "⊠", "boxdot": "⊡",
    "bigboxplus": "⊞", "bigoplus": "⨁", "bigotimes": "⨂", "bigodot": "⨀",
    "bigcup": "⋃", "bigcap": "⋂", "bigvee": "⋁", "bigwedge": "⋀",
    "biguplus": "⨄", "coprod": "∐", "iint": "∬", "iiint": "∭",
    "pm": "±", "mp": "∓", "otimes": "⊗", "oplus": "⊕", "ominus": "⊖",
    "ast": "∗", "star": "⋆", "circ": "∘", "bullet": "•",
    "wedge": "∧", "vee": "∨", "land": "∧", "lor": "∨", "neg": "¬",
    "to": "→", "mapsto": "↦", "gets": "←",
    "rightarrow": "→", "longrightarrow": "⟶", "leftarrow": "←",
    "longleftarrow": "⟵", "Rightarrow": "⇒", "Leftarrow": "⇐",
    "leftrightarrow": "↔", "Leftrightarrow": "⇔",
    "uparrow": "↑", "downarrow": "↓", "hookrightarrow": "↪",
    "infty": "∞", "partial": "∂", "nabla": "∇", "forall": "∀",
    "exists": "∃", "nexists": "∄", "sum": "∑", "prod": "∏", "int": "∫",
    "oint": "∮", "angle": "∠", "perp": "⊥", "parallel": "∥",
    "langle": "⟨", "rangle": "⟩", "lceil": "⌈", "rceil": "⌉",
    "lfloor": "⌊", "rfloor": "⌋", "sqrt": "√", "cdots": "⋯", "ldots": "…",
    "dots": "…", "vdots": "⋮", "ddots": "⋱", "prime": "′", "deg": "°",
    # 希腊字母
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ", "Theta": "Θ",
    "iota": "ι", "kappa": "κ", "lambda": "λ", "Lambda": "Λ", "mu": "μ",
    "nu": "ν", "xi": "ξ", "Xi": "Ξ", "pi": "π", "Pi": "Π", "rho": "ρ",
    "sigma": "σ", "Sigma": "Σ", "tau": "τ", "upsilon": "υ", "phi": "φ",
    "varphi": "φ", "Phi": "Φ", "chi": "χ", "psi": "ψ", "Psi": "Ψ",
    "omega": "ω", "Omega": "Ω", "Gamma": "Γ", "Delta": "Δ",
}


DROP_CMDS = {
    "left", "right", "middle", "limits", "nolimits", "displaystyle",
    "textstyle", "scriptstyle", "scriptscriptstyle",
    "big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl", "Bigr",
}


SPACE_CMDS = {"quad", "qquad", "thickspace", "medspace", "thinspace",
              "enspace", "hspace", "vspace"}


def _deaccent(m):
    mark, ch = m.group(1), m.group(2)
    return ACCENT_MAP.get(mark, {}).get(ch, ch)


def _cmd_text(m):
    name = m.group(1)
    if name in MATH_CMDS:
        return MATH_CMDS[name]
    if name in DROP_CMDS:
        return ""
    if name in SPACE_CMDS:
        return " "
    return name          # 未知命令：去掉反斜杠、保留名字（如 \R -> R、\Pol -> Pol）


def clean_label(text):
    r"""清理 LaTeX 标题中的装饰命令，得到可显示的纯文本。

    处理 \texorpdfstring{A}{B} -> A、\textbf{} 等装饰命令、数集宏与残留括号。
    """
    if not text:
        return ""
    s = text.strip()

    # \texorpdfstring{A}{B} -> A。两个参数是各自独立的括号组，第二个须整体跳过。
    for _ in range(200):
        p = s.find("\\texorpdfstring{")
        if p < 0:
            break
        first, pos = take_group(s, p + len("\\texorpdfstring"))
        if pos < len(s) and s[pos] == "{":
            _, pos = take_group(s, pos)
        s = s[:p] + first + s[pos:]

    for cmd in ("\\textbf", "\\textit", "\\emph", "\\mathrm", "\\mathbf",
                "\\mathsf", "\\text", "\\ensuremath", "\\mbox"):
        s = unwrap_cmd(s, cmd)

    # 数学字体宏一类 \cmd{X} -> X（如 \mathcal{L} -> L、\mathfrak{S} -> S）
    for _ in range(60):
        before = s
        s = re.sub(r"\\[a-zA-Z]+\{([^{}]*)\}", r"\1", s)
        if s == before:
            break

    for cmd in ("\\Huge", "\\huge", "\\Large", "\\large", "\\normalsize",
                "\\footnotesize", "\\small", "\\!"):
        s = s.replace(cmd, "")

    s = s.replace("$", "")
    for _ in range(200):
        before = s
        s = re.sub(r"\{([^{}]*)\}", r"\1", s)
        if s == before:
            break
    s = s.replace("{", "").replace("}", "")
    # 重音转义：\"o -> ö、\'e -> é、\`a -> à、\^o -> ô、\~n -> ñ
    s = re.sub(r"\\([\"'`^~])\s*([A-Za-z])", _deaccent, s)
    # 命令：常用数学命令换成符号、纯排版命令删掉、其余去掉反斜杠保留名字
    s = re.sub(r"\\([A-Za-z]+)", _cmd_text, s)
    # 行内间距命令 \  \,  \;  \:  \! -> 空格（随后统一折叠）
    s = re.sub(r"\\([ ,;:!])", " ", s)
    # 其余转义符号：\# \_ \% \& \{ \} -> 字面符号
    s = re.sub(r"\\([#$%&_{}])", r"\1", s)
    return " ".join(s.replace("\\", "").split())


def resolve_target(note_dir, target):
    r"""把 \input 的目标路径解析为实际文件路径。

    不能拿 `Path.suffix` 判断是否要补 `.tex`：`\input` 允许省略扩展名，而文件名
    本身可能含点（如 `1_The_complexes_Ku,_K.u,_C,_Ku,_C`），后缀会算成
    `.u,_C,_Ku,_C` 这种伪后缀，于是漏补 `.tex`，真实存在的文件被误判成「未建」。
    """
    rel = target.strip()
    while rel.startswith("./"):
        rel = rel[2:]
    p = note_dir / rel
    if p.name.lower().endswith(".tex"):
        return p
    return note_dir / (rel + ".tex")


def strip_comment(line):
    r"""去掉行内注释：从第一个**未转义**的 `%` 起截断。

    LaTeX 里 `\%` 是转义的百分号、不算注释起点。环境统计必须先过这一步 ——
    否则被 `%` 注释掉的旧环境会被算进 envs，还可能让 `\begin` / `\end` 配对失衡
    （只注释掉一半时，会报出并不存在的「未配对」硬提示）。
    """
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if c == "\\":
            i += 2
            continue
        if c == "%":
            return line[:i]
        i += 1
    return line


def file_metrics(path, min_chars=MIN_CHARS, text=None):
    """统计单个 tex 文件的指标。

    返回 dict，含状态、字符构成、定理环境统计、配对情况等。
    text 可传入已读入的内容，避免重复读取磁盘。
    """
    m = {
        "status": "empty",
        "chars": 0,            # 剔除标题/注释/空行后的实质字符数
        "body_chars": 0,       # 环境之外的陈述性文字
        "inner_chars": 0,      # 定理环境内部的字符
        "total_chars": 0,
        "lines": 0,
        "envs": 0,
        "empty_envs": 0,
        "env_names": {},
        "has_proof": False,
        "has_sketch": False,
        "unpaired": False,
        #: 本文件里各标题命令的第一次出现（命令名 → 标题文本），
        #: 供上层按「这本笔记的层级模式」取用：`\section` 写在某个目录的第一个叶子里
        #: 时，那个叶子自己的标题是 `\subsection`，两者不能混为一谈。
        "titles": {},
    }
    if text is None:
        try:
            # utf-8-sig：无 BOM 时与 utf-8 行为完全一致；有 BOM 时自动剥离。
            # 必需 —— BOM 会让行首锚定判定（`cstrip[:1] == "\\"`、COMMENT_RE.match）
            # 在首行失效，导致标题文本被计入字数、首行注释/`\input` 的纳入标记判断出错。
            text = path.read_text(encoding="utf-8-sig", errors="ignore")
        except OSError:
            m["status"] = "missing"
            return m

    m["total_chars"] = len(text)
    lines = text.splitlines()
    m["lines"] = len(lines)

    depth = 0              # 当前定理环境嵌套深度
    buf = 0                # 当前环境累积字符
    env_stack = []

    def add_text(seg):
        """把一段纯正文按「当前的嵌套深度」归入内层 / 外层，并计入总字数。

        只在代码部分（注释已剥掉）上调用，所以行内注释不会污染字数。
        """
        nonlocal buf
        cnt = len(seg)
        if not cnt:
            return
        if depth > 0:
            buf += cnt
            m["inner_chars"] += cnt
        else:
            m["body_chars"] += cnt
        m["chars"] += cnt

    for ln in lines:
        raw = ln.rstrip("\n")
        # 一律只用代码部分：`%` 之后（含整行注释）既不算字数、也不参与标题与环境识别
        code = strip_comment(raw)
        cstrip = code.strip()
        if not cstrip:
            continue

        # 标题行：先收集各命令的标题（每本笔记按自己的层级模式取用），文本不计入字数。
        # 「命令出现过」本身就是有用信息（`\appendixchapter{}` 留空标题也是附录），
        # 所以只要匹配到就记下来，哪怕标题文本是空串。
        is_title = False
        if cstrip[:1] == "\\":
            for _k, _rx in _TITLE_RES.items():
                if _k in m["titles"]:
                    continue
                _mt = _rx.search(code)
                if _mt:
                    m["titles"][_k] = clean_label(_mt.group(1))
            is_title = bool(TITLE_RE.match(cstrip))

        # 环境开关按**列顺序**处理：同一行里的 `\begin{X}…\end{X}` 也要算对 ——
        # 逐个 finditer 分开跑会把同行环境判成空环境、内容也归错桶。
        # 段间文本按「当时的嵌套深度」进内层（inner）或外层（body）。
        events = []
        if "\\begin{" in code or "\\end{" in code:
            for mm in BEGIN_RE.finditer(code):
                events.append((mm.start(), mm.end(), "b", mm.group(1)))
            for mm in END_RE.finditer(code):
                events.append((mm.start(), mm.end(), "e", mm.group(1)))
            events.sort()

        seg_start = 0
        for pos, endpos, kind, name in events:
            if not is_title:
                add_text(code[seg_start:pos].strip())
            seg_start = endpos
            if kind == "b":
                if name in THEOREM_ENVS:
                    if depth == 0:
                        buf = 0
                    depth += 1
                    env_stack.append(name)
                    m["envs"] += 1
                    m["env_names"][name] = m["env_names"].get(name, 0) + 1
                # 「证明」维度：proof 不在 THEOREM_ENVS 里（不计入那 17 个），
                # 但它与 sketch 都要能被认出来，所以按 PROOF_ENVS 单独判。
                if name in PROOF_ENVS:
                    if name == "proof":
                        m["has_proof"] = True
                    else:
                        m["has_sketch"] = True
            else:
                if name in THEOREM_ENVS:
                    if depth > 0:
                        # 用栈比对名字：`\begin{theorem}…\end{lemma}` 在 LaTeX 里是错误
                        if env_stack and env_stack[-1] != name:
                            m["unpaired"] = True
                        if env_stack:
                            env_stack.pop()
                        depth -= 1
                        if depth == 0:
                            if buf < EMPTY_ENV_CHARS:
                                m["empty_envs"] += 1
                            buf = 0
                    else:
                        # 栈已空还遇到 `\end`：这一行本身就多了一个 end
                        m["unpaired"] = True
        if not is_title:
            add_text(code[seg_start:].strip())

    if depth != 0:
        m["unpaired"] = True

    m["status"] = "written" if m["chars"] > min_chars else "empty"
    return m


def scan_main(note_dir, cfg):
    r"""解析 main.tex 的顶层 \input，附带其上方最近的 \part / \chapter / \section 标题。

    顶层（部分 / 章）的标题写在 main.tex 里而不是目录中的文件，所以必须在这里取 ——
    否则树上那一行只能显示英文目录名。三个命令都记下来，由层级模式决定用哪个
    （`\part` 下挂多个 `\input` 的写法里，那些 `\input` 用的是 `\chapter` 名）。
    """
    mt = note_dir / "main.tex"
    entries = []
    if not mt.exists():
        return entries
    cur = {k: "" for k in ("part", "chapter", "section")}
    for ln in mt.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
        stripped = ln.strip()
        for k in cur:
            mh = _TITLE_RES[k].search(ln)
            if mh:
                cur[k] = clean_label(mh.group(1))
        for t in parse_inputs(ln):
            entries.append({
                "target": t,
                "part": cur["part"],
                "chapter": cur["chapter"],
                "section": cur["section"],
                "included": not COMMENT_RE.match(stripped),
            })
    return entries


def main_headings(note_dir, entries):
    r"""main.tex 里「\input 目标 → 该处各标题命令的值」。

    键与节点的 id 同形（笔记目录内的相对路径），供 apply_levels 按层级模式取用。
    """
    out = {}
    for e in entries:
        vals = {k: e[k] for k in ("part", "chapter", "section") if e.get(k)}
        if not vals:
            continue
        p = resolve_target(note_dir, e["target"])
        try:
            rid = str(p.relative_to(note_dir)).replace("\\", "/")
        except ValueError:
            rid = str(p).replace("\\", "/")
        out[rid] = vals
    return out
