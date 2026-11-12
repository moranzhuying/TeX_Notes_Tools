# LaTeX 转 Word 预处理

把用 LaTeX 写的论文转成学校要求的 `.docx` 交付。Pandoc 直接转会坏在四处，本脚本先把这些地方改写成 Pandoc 能处理的形式。

## 为什么需要它

Pandoc 原样转换这类文档时，常见的坏法有这几处：

| 元素 | 直接转 Pandoc | 本脚本处理后 |
|---|---|---|
| 行内公式 `\mathbb{R}` | ✓ 转 OMML | ✓ |
| 定理环境 `\begin{theorem}{标题}{label}` | ✗ 整个散架 | ✓ `**定理 1.1（标题）**` |
| 交叉引用 `\cref{x}` | ✗ 裸标签 `[x]` | ✓ 静态编号 `1.2` |
| 自定义宏 `\N`、`\pr` | ✗ 原样留成文本 | ✓ 展开成 `\mathbb{N}` |
| `\unnumberedsection` | ✗ 整条标题丢失 | ✓ `\section*{}` |
| 并排图 caption | △ 丢第一个 | 同（Pandoc 固有限制） |

## 用法

```bash
# 只产出中间 tex，人工看一遍
python preprocess.py main.tex -o main_flat.tex

# 直接出 docx
python preprocess.py main.tex --pandoc out.docx

# 套学校 Word 模板的样式（推荐）
python preprocess.py main.tex --pandoc out.docx --reference-doc 学校模板.docx

# sty 不在同目录时显式指定
python preprocess.py main.tex --sty ../structure.sty -o main_flat.tex
```

转 docx 时如果图片报找不到，加 `--resource-path`：

```bash
pandoc main_flat.tex -o out.docx --resource-path="论文目录"
```

## 它做了什么

1. **递归展开 `\input` / `\include`**：路径以主文件目录为基准，和 LaTeX 编译一致。
2. **解析 `structure.sty`**：读 `\newcommand` 拿无参宏，反复替换直到收敛（`\N` → `\mathbb{N}` 这类链式定义也能展开）。
3. **定理环境按节编号**：读 `\newtcbtheorem` 拿环境名与中文名，输出 `**定理 1.1（谱定理）**`，同时记下 label → 编号。
4. **交叉引用静态化**：`\cref`/`\Cref`/`\autoref` → `\ref`，再把能查到的 `\ref` 直接换成编号。查不到的（图、表）原样留给 Pandoc。
5. **清理 Pandoc 不认的命令**：`\medskip`、`\hfill`、`\vspace`、`\addcontentsline`、`multicols` 等。

## 已知限制

- **编号是静态文本**。Word 里增删定理后编号不会自动更新，改完要重跑一遍。换来的是绝不会出现乱码标签。
- **带参数的宏不展开**（`\newcommand{\pr}[1]{...}` 这类），脚本只在报告里列出来，需要人工处理。
- **图、表的交叉引用交给 Pandoc**，它只能给 `\label` 挂在 figure/table 上的情况编号。
- **并排 minipage 图** 会变成表格，第一个 caption 可能丢，需要手工补。
- **模板特定残留**：部分模板开头会多出 `Contents`、`starttoctoc` 等字样，Word 里手工删掉即可。这类模板结构问题无法穷尽，转换后建议通读一遍。

## 依赖

Python 标准库 + Pandoc 3.x。不需要 LaTeX 环境（不编译，只做文本改写）。
