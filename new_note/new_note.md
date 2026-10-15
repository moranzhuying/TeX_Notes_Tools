# new_note.py — 从模板新建笔记

不带参数进入交互引导；也可指定笔记名、模板和 Markdown 大纲。程序复制模板骨架、生成 TeX 目录，初始化 Git 并安装提交前钩子，默认首次提交；只有显式 `--push` 才创建远程并推送。`--dry-run` 只预览，不写入文件。

```bash
python new_note.py MyNote --outline outline.md --abbreviation ABC
python new_note.py MyNote --outline outline.md --abbreviation ABC --dry-run
python new_note.py MyNote --outline outline.md --intro --summary
```

## 导引与小结（可选）

`--intro` / `--summary` 让骨架按 Math-Note 模板的既有约定带上这两样，默认都不带。交互式引导会问一句（`y` 都建 / `i` 只建导引 / `s` 只建小结）。

- `Content/<层1>/intro.tex`：本章导引，无编号标题 ＋ `\phantomsection` ＋ `\addcontentsline`。
- `Content/<层1>/Summary/`：本章小结，`index.tex` ＋ `intro.tex`（导引）＋ `01_summary.tex`（条目）。
- `Content/<层1>/<层2>/Summary/`：本节小结，标题降一级（`\subsection{本节小结}`，条目用 `\subsubsection`）。

**导引只加在最外层**（章 / 节）；**小结加在所有会产生目录的层**——末层是 `.tex` 文件，不加。小结自己占下一级的编号标题，内部导引与条目再降一级（带 `*` 与不带 `*` 区分）。每份新文件里留一行 `%` 注释写「这一节该写什么」，不占版面、不进目录。

对应的 `\input` 插进该层 `index.tex`：导引在第一条 `\input` 之前（开头的注释行留在最上面），小结在附录之前（没有附录就接在最后一条 `\input` 之后）。

已有的笔记要在事后补，走工具面板的「笔记工具」（`note_tools.py`）→「补导引与小结」：扫描 `Content/` 现有结构、按内容推断层级命令，只补缺、不覆盖，可以反复跑。

## 资料模式

模板含 `Source.md` 时启用资料骨架。缩写从 `--abbreviation`、大纲头部 `abbreviation:` 或交互输入获取，须由用户按所选版本核定；使用 ASCII 字母开头，可含数字、下划线与连字符。不从笔记名猜造书籍缩写，缺缩写在写入前停止。

资料模式目前仅支持 `levels: chapter, section, subsection`。三层分别对应原书章、§、目。目录或叶子名前的显式数字用于编号，无前缀按同级顺序自动编号；正整数且目编号必须唯一，人工核对后固定。TeX 仍采用原大纲的标题路径，不因资料编号重排。

- `Source.md`：书名、语言、版次/年份、出版社、PDF 标识与缩写。未知信息待填写。
- `缩写_Content.md`：输入目录正文与 TeX/资料绑定；输入头部元信息剥离，不复制本地模板路径。无大纲时仅生成待核对目录。
- `Materials/Cxx/Sxx/Nxx/images/`：来源截图，先保存后发送。
- `body.md`、`proof.md`：分别保存正文和证明的首次完整输出与最终采用稿。
- `record.md`：PDF 页序号、印刷页码、证明位置、待核对问题。
- `Materials/Cxx/Sxx/review.md`：每行一目，各审核阶段默认未检查。

程序只补缺失资料文件，不覆盖已有稿件和核对表；扩展目录时须人工同步核对表与绑定。习题不计入正文资料。`Materials/` 中的 body、proof、record、review、images/.gitkeep 与截图均允许 Git 版本跟踪，随私有仓库备份，克隆恢复已提交资料。新书不复制模板 Materials 或 BOOK_Content.md，而是按自身大纲可靠重建资料，避免模板样例污染。含来源材料的项目须保持私有。

不含 `Source.md` 的模板保持原层级流程。本功能不迁移已有笔记，不删除既有正文；历史材料后补。
