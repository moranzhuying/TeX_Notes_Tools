# 更新日志 (ChangeLog)

**版本日期**: 2026-11-12
**当前状态**: 日常使用中。工作台的 PDF 预览为部分实现 —— 独立标签页路线可用，嵌入 Blob 与直接 HTTP iframe 仍受限，见 2026-10-14 条目。

---

## 2026-11-12 更新概览

对 Tools 下全部工具做一轮缺陷排查（数据安全 / 功能失效 / 编码容错）；随后连续三步收口：查干净**打包后才出现**的问题、把源码收进 `src/`、按桌面应用的惯例拆成「程序 / 数据 / 工作区」三分并改用 onedir 打包。之后补了图文帮助，并给界面字号做了高 DPI 适配。依次见「缺陷修复」「第四轮」「结构调整」「应用化改造」「图文帮助」「高 DPI 适配」。

### 缺陷修复

* **`clean_aux`：删除范围收窄**
    * 原来只按扩展名在整工作区匹配，实测会把 `outputs/` 的转录日志、`Tools/watch_notes/_logs/` 的运行日志一并删除。改为只认「LaTeX 上下文」：产物所在目录必须有 `.tex` 源文件。
    * `--with-pdf` 原来删全部 PDF（本工作区 2189 个，含扫描书籍与参考资料）。改为只删与同目录某个 `.tex` 同名的 PDF。
    * 默认跳过 `outputs/`、`SkillProjects/`、`_logs/`、`_state/`。
* **`symbols`：模板备份与跨行定义**
    * `backup()` 对任何 `structure.sty` 一律跳过，而模板自身没有可重建来源。改为模板调用时 `force=True`，保留可回滚副本。
    * 插入新定义时按「上一条定义的结束行」定位，跨行定义（`\newcommand{\x}[2]{%` 换行续写）不再被拆开。
    * 选项 6 录入定义时拦未转义的 `%`，避免把后续整行吞成注释、进而在 8 本笔记里编译失败。
* **`new_note`：测试目录与标题转义**
    * 清理测试目录改用「Test 作为独立段」匹配，`Testing_Notes`、`Contest_Problems` 不再被整棵删除；`rmtree` 失败给出提示而非崩栈。
    * 笔记名与大纲中译名写入 `\title` / `\part` / 章节命令前做 LaTeX 转义，`_`、`&`、`%` 等不再导致编译失败。
    * `notes_root()` 找不到根目录时明确报错，不再因 `target=None` 崩栈；`root` 支持 `~` 展开。
* **`commit`：钩子与 CHANGELOG 路径**
    * `--check` 移到 `chdir` 之前执行。原先会切到 `Tools/commit/`，钩子触发时扫的是本工具集仓库的暂存区，防泄露机制实际失效。
    * `--log` 改为写 `Tools/CHANGELOG.md`（原先找 `Tools/commit/CHANGELOG.md`，该文件不存在）；找不到目标节时提示当前格式。
* **`manager`：只推送与配置容错**
    * 「只推送」不再按工作区是否干净过滤，工作区干净但本地有未推送提交的仓库也能重推。
    * `manager.conf` 读取支持 UTF-8 BOM 与 GBK 回退，键名剥 BOM。
* **`check_sensitive`：全量扫描盲区**
    * `ls-files` 与 `diff` 关闭 `core.quotepath`。中文/希腊字母文件名原先被转义成八进制，拼出的路径不存在而被静默跳过（实测 Algebra 仓库漏 10 个正文文件）。
    * `/home/` 模式加左边界，`https://example.com/home/...` 这类 URL 不再误报。
* **`repo_check`：同一处 `quotepath` 修复**
    * `ls-files` 关闭 `core.quotepath`，中文路径的编译产物入库检查不再失配。
* **`watch_notes`：`--no-push` 不再清历史**
    * `--no-push` 仍会执行 `reflog expire` 与 `gc --prune=now`，导致本地改写后的历史不可回退、且与远程彻底分叉。改为仅在推送成功后清理。
* **`progress`：端口串台**
    * `Server` 关闭 `allow_reuse_address`。Windows 上 `SO_REUSEADDR` 允许在已监听地址上再次 bind，两个实例可能同时监听同一端口，与「端口占用不接管」的承诺冲突。
* **`tex2docx`：定理环境配平**
    * 无参 `\begin{theorem}` 也补编号并转成静态文本。原先只删 `\end{theorem}`、不转换无参 `\begin`，输出里会留下孤立的 `\begin`。
* **`video2text` / `symbols`：配置编码**
    * 配置文件读取改用 `utf-8-sig`，Windows 编辑器写入 BOM 时不再静默回落默认值；`symbols` 的文本读取失败回退 GBK。

### 第二轮：残留缺陷清理

* **`commit`**
    * CHANGELOG 末尾无换行时 `body.index("\n")` 抛 `ValueError`，改用 `find` 兜底。
    * 内容以 `++` 开头的新增行会被当成 diff 头跳过（不做敏感词扫描），改为只排除 `+++ b/`、`--- `、`@@`、`diff --git` 结构行。
    * `git diff` 执行失败时不再静默按「无命中」放行，改为打印警告。
    * 补 stdout/stderr 的 UTF-8 兜底。
* **`manager`**
    * `cwd` 不存在与「命令不存在」原本都报「未找到命令」，改为区分具体路径。
    * 无法比较 ahead/behind 时用 `?` 而不是 `-`，「同步正常」判定不再把未知当 0。
    * 「nothing to commit」不再被当作首次提交成功，也不再继续 `gh repo create --push`。
* **`symbols`**
    * `DEF_RE` 认 `\newcommand*`，与 `DEF_HEAD_RE` 对齐。
    * 替换定义时按整块（`definition_end`），跨行定义不再留下孤立函数体。
    * 覆盖符号时沿用原定义前缀（`\newcommand` / `\renewcommand`），不再一律写成 `\newcommand`。
    * 删除只在 `[模块 VI]` 内匹配，不再连带删模块 II–V 的同名宏；删除后同步清理提取档案。
    * `distribute` 读取失败的笔记逐条提示，不再静默跳过。
    * `refresh_cwl` 保留自动段之后用户追加的注释。
* **`outline_tool`**
    * `\input{...}%` 这类带尾随注释的写法能识别。
    * `lstrip("./")` 改为只剥前缀 `./`，`../` 不再被吃掉。
    * 写 md 前若目标已存在且内容不同，先留 `.bak`。
    * 8 处读取加 `errors="replace"`，非 UTF-8 文件不再让面板抛栈。
* **`new_note`**
    * 大纲 md 带 BOM 时头部元信息不再全部失效。
    * `\input` 判重改为忽略缩进与尾随注释，避免重复插入。
    * 笔记名字符集由 `\w` 收紧为 `[A-Za-z0-9_-]`，不再放行中文导致 `gh repo create` 失败。
    * 选项出现但缺值时给出提示，不再静默按默认值执行。
    * `.synctex.gz` 的复制跳过规则生效（`Path.suffix` 是 `.gz`）。
    * 首次提交前检查 `user.name` / `user.email`，缺失时提前中止并保留目录。
    * `--push` 时 `manager.conf` 缺 `account` 直接报错，不再拼出残缺 URL。
* **`video2text`**
    * `--drop-audio` 的清理异常不再穿出 `convert`，不会把已完成的转写记成失败。
    * 遗留锁下面板「生成标题目录」与 `--sync-titles` 不再崩溃（异常元组补 `RuntimeError`）。
    * `finally` 里的 `lock.unlink()` 加兜底，锁文件被外部删除/占用时不冲掉结果。
* **`progress`**
    * `目编号` 非法时记为冲突并跳过，不再让 `/data` 整体 500。
    * 读取 `.tex` / `review.md` 失败回退 GBK，非 UTF-8 文件不再让请求 500。
    * 备份改为先写 `.tmp-` 目录再整体改名；`list_backups` 跳过半成品/损坏目录；`restore` 用 `get("existed")`。
* **`pdf_upright`**
    * 备份文件名压平完整路径，`-r` 递归时不同目录的同名 PDF 不再互相覆盖。
* **`tex2docx`**
    * `\input` 展开改用递归栈语义，兄弟章节重复引用同一文件不再被当成循环引用丢弃。
* **`watch_notes`**
    * 面板输入 `-1` 之类负数/越界编号不再选中另一个仓库。
* **`note_tools`**
    * `new_note` 改为容错导入，缺文件时只有「补导引与小结」不可用，其余功能照常。

### 第三轮：剩余项收口

把前两轮标注为「需重构 / 设计取舍 / 边缘场景」的项一并处理完。

* **`symbols`：跨行定义整段解析**
    * `parse_symbols` 原先只认定义首行，跨行定义（`\newcommand{\x}[2]{%` 换行续写）的后半段成为无主残骸：比对时误报差异，回填/替换只换掉首行、留下残体。改为按 `definition_end` 整段收集，`code` 取各行去注释后的拼接。
    * `insert_into_symbol_lib` 的插入与替换按行拆分多行定义，行号不再因「一个元素含多行」而偏移，换行风格统一为文件自身的 EOL。
* **`new_note`：预演、换行与命名**
    * `--dry-run` 的「清理测试内容」原先扫的是尚未创建的目标目录，永远显示「（无）」。改为预演时扫模板。
    * `strip_test_sections` / `rewrite_main_tex` 保留原换行风格，CRLF 文件不再被整体改成 LF；一行并列多个 `\input` 时逐个判断，不再漏删。
    * `\title` / `\part{测试部分}` 匹配失败时明确告警（原先静默返回成功）。
    * 笔记名拦 Windows 保留设备名（`CON`/`NUL`/`COM1`…）与尾部空格、句点。
    * `levels` 连跳两层（如 `part` 直接接 `subsection`）给出提示。
* **`video2text`：登录态、补做与改名**
    * 默认不再直接读日常浏览器的 cookie —— 文档一直承诺「不借用」，实现却在无 cookie 文件时静默借用。改为配置 `[download] use_browser_cookies`（默认 false）或 `--use-browser-cookies` 显式开启。
    * `--only-failed` 现在也补「标记成功但产物被删/被清空/路径损坏」的集，原先只看状态，产物丢了永远补不回来。
    * `title_layout` 支持标题改回旧名：该目录确属本合集历史目录时复用，不再报「未登记或大小写冲突」。
* **`progress`：缓存与并发**
    * 只读展示的写许可核验加 2 秒缓存（原先每次请求都重扫整个 root、逐本校验永久 ID）；写操作仍实时核验。
    * 目录快照加 2 秒缓存，POST 成功后立刻失效，保存后读回不拿旧数据。
    * `ThreadingHTTPServer` 加并发上限（16），超限返回 503，一次刷新不再无限制开线程。
* **`outline_tool` / `tex2docx`**
    * 选项后缺值（`--check`、`--export`、`--from-text`、`--levels`）直接报错退出，不再掉进交互提问或抛 `TypeError`。
    * 导出提示「按占位空节点处理」与实际行为不符，改为「按现有深度结束，不补空标题」。
    * 定理编号的计数边界从只看 `\section` 扩展到 `\chapter` / `\section` / `\subsection`，带星号的标题不再推进编号。
    * 中间文件默认写到主 tex 同目录（原先写到当前工作目录）。
* **`git_setup`**
    * 已有 `Host github.com` 段但没配 443 时，就地补 `HostName` / `Port`；原先再追加一段，而 ssh 只认第一个匹配段，第二段永不生效。已有 `Port 22` 也会改成 443。
* **`repo_check`**
    * 编译产物清单与 `clean_aux` 对齐，补 `.synctex`、`.idx`、`.ind`、`.ilg`、`.run.xml`，并识别 `main.synctex(busy)` 这类占用态文件。
* **`pdf_upright`**
    * `-o` 指向源目录时直接拒绝：该参数的语义是「原件不动」，指到源目录会静默覆盖原件。
* **`launcher`**
    * 附加参数改用 Windows 习惯拆分，`--out D:\a\b` 的反斜杠不再被 shlex 当转义符吃掉。
* **`watch_notes`**
    * `--interval` / 删历史间隔下限 10 秒，并给出提示，避免 `0` 造成忙循环。

### 缺陷修复：`watch_notes` 历史不收敛

报告的现象是「设了每 15 分钟删一次，仓库仍有 35 条」。原因是裁剪语义写成了「删掉最早一条」，而提交还在按 5 分钟一条增加：每 15 分钟新增 3 条、删 1 条，净增 2 条/15 分钟，历史从来不会收敛。

* `prune_oldest` 改为 `prune_to(repo, keep)`：按条数上限裁剪，超出就一次裁到上限。
* 重建方式改用 `commit-tree` 逐条重放保留段，沿用原来的树、提交信息、作者与**提交时间**，只断掉更早的父链；不再走 `rebase --onto`，避免空提交判定与中断残留。
* `update-ref` 带旧 head 做 CAS，随后 `reset --hard` 对齐工作区（调用前已确认工作区干净）。
* 新增 `--keep`（默认 20，交互面板也会询问）；`--prune-interval` 语义改为「检查间隔」。
* `git()` 增加 `extra_env`，用于在 `commit-tree` 时传回原作者/提交时间。

### 第四轮：打包后的 exe

这一轮查**打包成 exe 之后才出现**的问题：用 `--exec` / `--selftest` 在打包环境里逐个工具冒烟，源码直跑全部正常，所以此前几轮都没碰到。顺带把全库的静态检查旧账清掉。

* **工具启动改用 venv 解释器（核心）**
    * 原机制是 exe 拿自己当解释器（`--exec`）。打包解释器的 `sys.path` 里只有 `_MEIPASS` 三项，实测 `pymupdf` / `numpy` / `faster_whisper` / `playwright` **全部缺失** —— PDF 转正、视频转写一启动就 ImportError。
    * 更隐蔽的一层：PyInstaller 把 `_MEIPASS` 塞进子进程 `PATH` 并设 `QT_PLUGIN_PATH` / `_PYI_*`。工具自身还有「缺依赖就换解释器重跑」的逻辑（`pdf_upright`、`video2text` 都有），换到 venv 的 python 后会加载**版本不符的 `python313.dll`**，进程链实测为 exe → exe → venv → venv 四层，40 秒零输出、纯挂死。
    * 改为 `panel_core.tool_python()` 定位工具 venv 的解释器，`_spawn_prefix` / `spawn_command` 在 frozen 下优先用它，找不到才回退 `--exec`。上文 `build_exe` 条目里的 `--exec` 描述以本节为准。
    * 新增 `panel_core.child_env()`：剥掉 `_MEIPASS` 的 `PATH` 项与 `QT_PLUGIN_PATH` / `_PYI_*`。`_MEIPASS` 常是 8.3 短名、`PATH` 里是长名，比较前要 `realpath` + `normcase` 归一再按前缀过滤，否则一条都匹配不上。
    * `launch()` 与 `panel_actions` 的 `QProcess` 都换成这份环境（`setProcessEnvironment`）。
    * 副作用是启动变快：onefile 每次运行解包 **93 MB**，原先**每点一次工具就解一次**，现在点工具不再解包。
* **`panel_config` / `launcher`：配置写进解包临时目录**
    * 两者都用 `__file__` 定位 `Tools/`。打包后 `__file__` 指向 `_MEIPASS`，配置被写进临时目录、进程退出即删 —— 表现为「设置每次重启都归零」，而 `panel_config` 的注释早就写着「打包后也在 exe 旁边」，实现没做。
    * 改为 frozen 时用 `sys.executable` 的目录。
* **`panel_qt`：崩溃日志同样落进 `_MEIPASS`**
    * `_panel_error.log` 与 `_panel_config.json` 同因，崩溃痕迹随进程消失，等于没记。抽出 `error_log_path()`，frozen 下落 exe 旁边。
    * `exec_tool` 在子工具崩溃后 `input("按回车关闭…")`，被面板捕获输出时没有终端，会一直挂着不返回。加 `isatty()` 守卫。
    * `exec_tool` 开头清洗自身环境，使目标脚本再派生的解释器不再继承污染。
* **`--selftest` 扩到九项**
    * 原来只验证「工具根正确 + 能拉起工具 11」。新增：工具解释器来源、子进程环境是否仍含 `_MEIPASS`、`pymupdf` / `numpy` / `yt_dlp` / `faster_whisper` / `playwright` 缺哪几个。缺依赖只报告、不阻断，因为纯标准库的工具不受影响。
* **静态检查旧账**
    * 全量 `pyflakes` 清到零：`make_icon` 未用的 `io`、`panel_pages` 未用的 `QtGui`、`manager` 未用的 `re`、`outline_tool` 一处无占位符的 f-string。
    * `build_exe` 的 `import PyInstaller  # noqa: F401` 骗不过 pyflakes（`noqa` 是 flake8 的写法），改 `importlib.util.find_spec`。
    * `make_icon` 的 `app` 不能删也不能改成下划线（pyflakes 一样报），末尾 `_app.quit()` 收尾 —— QApplication 的 C++ 对象被回收会崩。

### 结构调整：源码收进 `src/`

`Tools/` 根只留 `LaTeX-Toolbox.exe`、`README.md`、`CHANGELOG.md`、`_panel_config.json` 与 `src/`；全部源码（面板 + 16 个工具 + 两个非面板工具）下沉一层。exe 仍从磁盘读脚本，所以这只是收纳，不是把脚本打进包。

* **`panel_core`：拆开「工具根」与「脚本根」**
    * `TOOLS_ROOT` = `Tools/`（exe 所在，也是工作区的直接子目录）；新增 `SRC_ROOT` = 脚本所在（`Tools/src/`）。打包时取 exe 旁的 `src/`，**目录不存在则回退 `TOOLS_ROOT`**，旧的「脚本与 exe 同目录」布局照样能跑。
    * `describe_tools()` 的 `exists` 检查与 `launch()` 的脚本定位都改用 `SRC_ROOT`；`panel_actions` 的表单执行同样改。
    * `launcher.py` 一并拆出 `SCRIPT_ROOT`，`WORKSPACE` 仍由 `TOOLS_ROOT` 推导。
* **12 个工具：工作区上溯多一层**
    * `clean_aux` / `spec_sync` 从 `parent×3` 改成 `parent×4`；`new_note` / `note_tools` / `outline_tool` / `repo_check` / `sync_paths` / `show_memory` / `watch_notes` / `manager` 的 `WORKSPACE` 各加一层。
    * `manager` 另需一个 `TOOLS_ROOT`：它遍历工作区时要把「工具区」认出来并排除，若沿用 `TOOLS_DIR`（现在指向 `src/`）就永远匹配不上，`Tools/` 会被当成一个笔记仓库。
    * `TOOLS_DIR`（各工具目录的父级）语义恰好吃到 `src/`，所以 `TOOLS_DIR / "manager" / "manager.conf"`、`sys.path.insert(TOOLS_DIR / "new_note")` 这类引用不用动。
    * `symbols` 找「父目录下有多个笔记」的兜底、`video2text` 打印的工作区各加一层。
* **`progress`：默认配置与测试**
    * 默认 `root` 由 `../../LaTeX_Notes` 改为 `../../../LaTeX_Notes`（相对配置文件目录）。
    * `tests/` 里 `parents[3]`（工作区）改 `parents[4]`、`'Tools/progress'` 改 `'Tools/src/progress'`；`test_workbench_launcher` 的 `TOOLS`（Tools 根）改 `parents[3]`，`test_clean_save_acceptance` 与 `texstudio_ipc_routes` 的 `WORKSPACE`/`WS` 各多上溯一级。
* **打包与启动脚本**
    * `build_exe.py` 的入口改为 `src/panel_qt.py`，加 `--paths src`（`panel_core` 是「先改 `sys.path` 再 import launcher」，静态分析看不到），`--icon` / `--add-data` 指向 `src/tools.ico`；`--distpath` 仍是 `Tools/`，产物不变。
    * `run_panel.bat` 随源码进 `src/`，`ROOT=%~dp0..` 指回 `Tools/` 找 exe；文件保持 CRLF。
    * `panel_config.py` 源码运行时用 `parents[1]` 定位 `Tools/`，配置仍落在 exe 旁而不是 `src/` 里。
* **忽略规则与钩子（不做就会出事的两处）**
    * `.gitignore` 里带目录前缀的规则全部加 `src/` —— `progress/workbench_local.json`、`video2text/_data/`、`watch_notes/_state/` 这类规则按仓库根匹配，不跟着目录走；漏改会让本机配置和 1.5 GB 模型进入版本控制。
    * `sync_paths` 的忽略规则由单文件 `sync_paths.py` 改成整目录 `src/sync_paths/`：只忽略 `.py` 会漏掉同目录的 `.md`，一次 `git add -A` 就把它带进索引（本次结构调整时确实带进去过一次，已撤出）。
    * `.gitattributes` 的 `check_sensitive/pre-commit text eol=lf` 同样要加前缀，否则钩子被 CRLF 化、`sh` 报 `\r` 语法错。
    * `pre-commit` 模板的查找列表补 `Tools/src/*/check_sensitive.py`（保留旧的 `Tools/*/…` 兼容旧布局）。**已装钩子的 12 个仓库必须同步更新**：旧模板只认 `../../Tools/*/check_sensitive.py`，脚本沉到 `src/` 后一个都匹配不到，钩子会静默放行、防泄露形同虚设。已按「与旧模板逐字节相同才覆盖」的判据全量更新，并在 `LaTeX_Notes/Algebra` 实跑确认能定位到脚本。
* **文档**
    * README 的目录树重写（补上选项 16 `watch_notes`），散落的 `Tools/xxx` 路径统一补 `src/`；「exe 必须与脚本同目录」改为「exe 在 `Tools/` 根、脚本在 `src/`，只拷 exe 跑不起来」。

### 应用化改造：程序 / 数据 / 工作区三分

照 Typora、Anki、TeXStudio 的结构，把「程序只读」「数据可写」「内容由用户指定」分成三处。此前所有东西都住在 `Tools/` 一个目录里，装到 `Program Files` 后配置、日志、模型、状态全部写失败。

* **目录：`tools/` 组件、`src/` 面板源码、`resources/` 资源**
    * 18 个工具目录移到 `tools/`（对应 `plugins/` 的语义）；面板与打包脚本留在 `src/`，安装包不带这一层；`tools.ico` 与 `panel_gui.html` 进 `resources/`。
    * `panel_core` 的 `SCRIPTS_DIR` 指向 `tools/`，`TOOLS_ROOT` 仍是程序目录；`panel_actions` 的表单执行与 `describe_tools()` 的存在性检查同步。
    * 工具目录的层级没变（仍在程序目录下两级），上溯推导的 `WORKSPACE` 因而不受影响 —— 但下一条把它们整体换掉了。
* **`tools/app_paths.py`：数据落点与工作区只在这里定义一次**
    * `portable()` 判定形态：环境变量 `LATEX_TOOLBOX_PORTABLE` → 程序目录下的 `portable.flag` → 程序目录的父级像不像工作区（有 `LaTeX_Notes` 或 `Template`）。
    * `workspace()`：`config.json` 的 `workspace` 优先（相对路径按配置文件目录解析），缺失回退「程序目录的父级」——于是便携形态仍然零配置。
    * `data_dir(tool)` / `conf_file(tool, name)`：便携时落在 `tools/<工具>/`，安装时落在 `%LOCALAPPDATA%\LaTeX-Toolbox\<工具>\`。
    * `settings_file()` / `log_dir()`：应用级配置与日志，便携在程序目录，安装进 `%APPDATA%` / `%LOCALAPPDATA%`。
    * 配置里可给 `data_dir`，把 whisper 模型这类大件指到别的盘。
* **12 个工具改成读配置，不再上溯推工作区**
    * `clean_aux` / `spec_sync` 的 `parent×4`、其余 8 个的 `WORKSPACE = ...parent` 全部换成 `app_paths.workspace()`。
    * `manager` 识别「工具区」改用 `app_paths.APP_DIR`：安装形态下 `Tools/` 根本不在工作区里，原先按层级判断会把它当成一个笔记仓库。
    * `symbols` 找「父目录下有多个笔记」的兜底、`video2text` 打印的工作区一并改用 `workspace()`。
* **数据落点全部迁出程序目录**
    * `manager.conf`、`symbols.conf`、`symbols_extract.json`、`notes_tree.json`、`progress/workbench_local.json`、`video2text.conf`、`video2text/_data`、`watch_notes/_state`、`watch_notes/_logs`、面板设置、崩溃日志。
    * 读方不止一个的配置（`manager.conf` 被 `new_note` / `note_tools` / `repo_check` / `sync_paths` 读）统一走 `app_paths.conf_file()`，避免各自拼路径拼出不一致的位置。
    * `sync_paths` 的 `ITEMS` 从 `"manager/manager.conf"` 这种相对串改成 `(工具, 文件名, 键, 类型)` 四元组。
    * `progress` 的默认 `root` 不再是 `../../../LaTeX_Notes` 这种靠层数猜的相对路径，直接是 `workspace()/LaTeX_Notes`。
* **打包改 onedir，产物摊到程序目录根**
    * 默认 `--onedir`：`LaTeX-Toolbox.exe`（1.8 MB）+ `_internal/`（约 92 MB），不再每次启动解包 90 MB。
    * 新增 `flatten()`：把 `dist/<名>/` 里的 exe 与 `_internal/` 移到程序目录根，覆盖前先清旧的 `_internal`，免得残留 dll 混进来。
    * `--onefile` 保留为可选项，仅在需要单文件分发时用。
* **忽略规则与钩子（第三次跟着目录走）**
    * `.gitignore` 的目录前缀由 `src/` 改为 `tools/`，并新增 `_internal/`（92 MB 的运行时目录）、`config.json`、`logs/`。
    * `.gitattributes` 的 `pre-commit text eol=lf` 同步改到 `tools/check_sensitive/`。
    * 钩子模板的查找列表改成「一段 / 两段」都试：`Tools/*/check_sensitive.py` 与 `Tools/*/*/check_sensitive.py`。脚本沉到 `Tools/tools/` 后是两级，只写一段会一个都匹配不到 —— 钩子找不到脚本就放行，防泄露静默失效。12 个仓库已再同步一次，并在 `Algebra` / `General_Topology` 实跑确认。
    * README 目录树再次重写，并新增「数据放在哪」一节说明两态的数据位置。

### 第五轮：应用化改造后的回归

改造完按两态（便携 / 安装）各跑一遍全工具，收敛出四处漏改，都属「数据落点跟着目录走时少算一层」。

* **`video2text`：数据目录少一层 `_data`（影响最大）**
    * `DATA` 直接取 `app_paths.data_dir("video2text")` 得到 `tools/video2text`，而模型、cookie、profile、转写产物都在它下面的 `_data/` 里。表现是「登录态未登录、本地模型无、已转写 0 份」—— 5.4 GB 数据全都在，只是找不到。补回 `_data` 这一层后恢复正常（转写 490 份、cookie 有效至 2027-04）。
* **`symbols`：三处仍指向工具目录**
    * `default_cwl()` 在无 `%APPDATA%` 时回退 `SCRIPT_DIR / custom.cwl`，装到只读目录会写失败，改 `DATA_DIR`。
    * `.cwl_source`（cwl 来源记录）从 `SCRIPT_DIR` 改 `DATA_DIR` —— 它和 `symbols.conf` 一样是本机数据。
    * `resolve_root()` 的兜底从 `SCRIPT_DIR` 改 `workspace()`：工具已不在笔记根下，返回工具目录毫无意义。
* **一条纪律：工具里不许用 `sys.executable` 起 python**
    * 打包后它就是 `LaTeX-Toolbox.exe`，`exe -c "..."` 会被当成「无参数启动」，直接弹 GUI。测试脚本踩了一次（一次性起了两个窗口），工具里早先已规避（`pdf_upright` / `video2text` 都显式找 venv 解释器）。写新工具要走 `panel_core.tool_python()` 或 `app_paths`。

### 新增：图文帮助文档

每个工具一份说明，随 exe 分发，断网可查。入口两处：左下角「使用帮助」进总览，每个工具页右上角「? 查看帮助」直接跳到自己那篇。

* **结构**：`resources/help/` 下 17 个 HTML（总览 + 16 个工具）+ 19 张截图。扁平布局，图片走 `img/`，文档之间用文件名互链。打包时 `--add-data` 进 `_internal/help`，运行时从 `_MEIPASS` 读。
* **每篇五块**：什么时候用 / 怎么做（编号步骤）/ 界面上每项的意思（对照表单字段）/ 文件都在哪（配置与数据落点）/ 常见问题 Q&A。Q&A 写的是实际踩过的坑，不是占位。
* **生成而不是手写**：`src/make_help.py` 里一份数据 + 一套模板，样式、导航、页脚只有一处。改文案不碰标签，也不会 17 个文件改漏一个。
* **截图另一条线**：`_dbg/shoot_help.py` 用 `MainWindow.grab()` 抓「主界面 + 16 个工具页 + 设置页 + 帮助页」，固定浅色主题。分组页窗口高度压到 520，否则截图下方会有一大块空区。
* **`panel_pages.HelpPage` 重写**：不再把文档塞进 Python 字符串，改为读磁盘 HTML；`setOpenLinks(False)` + `anchorClicked` 自己处理站内跳转（否则 Qt 会当成文件打开）。`panel_core` 增加 `HELP_SLUGS`，`describe_tools()` 带出 `help` 字段，工具页据此生成「查看帮助」按钮。
* **`HelpDoc` 固定白底**：文档是浅色（配浅色截图）。原先 QSS 让它跟 `card` 取色，深色主题里会变成深底深字，看不清。
* **两处 Qt 渲染坑**：① `<p>` 里 `<br>` 换行、后面紧跟 `<img>`，QTextBrowser 会把图片插进段落中间 —— 改成表格排两行信息；② 只给 `<img>` 宽度不给高度时，它按图片的 DPI 元数据另算高度，图下留出一大块空白 —— 改为从 PNG 头读原始尺寸、按 560 宽等比写死 `height`。
* `tools/*/*.md` 保留为源码级说明（实现细节与设计取舍），面向改代码的人；面板里的帮助面向使用者，两套不互替。

### 调整：卡片标题、主题入口、帮助入口

* **卡片标题去掉括号注释**
    * `launcher.MENU` 里「设置 git 基本信息（环境检测 / 账户 / SSH）」这类补充是给命令行菜单用的；卡片上再带一遍太挤，下面本来就有一句说明。`panel_core.plain_title()` 剥掉中文/英文括号段，`describe_tools()` 同时给出 `title`（干净）与 `full_title`（原样）。
* **主题切换收回设置页**
    * 侧栏底部原先有「深色主题 / 浅色主题」一项，与「设置」页里的主题下拉重复；去掉侧栏那一个，只保留设置页。`Sidebar.theme_toggled` 信号与 `set_theme_label` 一并删除。
* **帮助入口改成上下文按钮**
    * 标题行右侧常驻一个圆形「?」：分组页 → 本板块帮助页，工具页 → 该工具那篇，在帮助/设置页 → 回总览。工具页里另有「? 查看帮助」，离表单更近。
    * 新增 6 个板块页（`group-core` / `group-maintain` / `group-commit` / `group-media` / `group-pdf` / `group-watch`），列出该组每个工具的一句话与入口。`panel_core.GROUP_SLUGS` 是映射表。
    * 帮助页标题跟着内容走：「帮助：PDF 处理」「帮助：PDF 转正」，不再一律写「使用帮助」。
* **帮助文档跟随主题**
    * 文档是浅色写死的，`QTextBrowser` 又不认 CSS 变量；深色主题下按 `HelpPage.DARK_SWAP` 把 19 个色值换掉（纸底、正文、标题、链接、三种提示框、表格边框、行内代码）。`apply_theme` 调 `help_page.set_dark()`，切换主题即时生效。
    * **配图也换**：`resources/help/img/` 拆成 `light/` 与 `dark/` 两套（各 19 张，`_dbg/shoot_help.py` 跑两遍产出），文档默认引用 `light/`，深色主题下把前缀换成 `dark/`。只改文字颜色不改图，暗色下会白得刺眼。
    * `HelpDoc` 的 QSS 背景改回 `{card}`，与文档换色后的底色一致。
    * 界面改了就得重跑 `_dbg/shoot_help.py` —— 文档里的截图是真实界面，标题与侧栏都变了，不重截会图文不符。

### 调整：帮助文档的配图与排版

* **图片放大并居中**
    * 原来固定 560 宽，在 900 宽的内容区里偏小、看不清。改为 HTML 里写设计宽度 1000，`HelpPage._fit_images()` 加载时按视口实测宽等比缩放（宽高一起改，只给宽度会让 Qt 按 DPI 另算高度、图下留白）。
    * `<p align="center">` 居中，图注也居中；左右留白收窄（文档 30px、HelpDoc 12px），把宽度让给图。
    * 图片外套一层链接：点一下用系统看图器打开原图（1680×1140），细节看得清。图注末尾写明这一点。
* **截图尺寸反直觉：不是越宽越清楚**
    * 图在帮助页里只能显示到内容区那么宽（约 800），源图越宽缩放比越小、字越糊。1440 宽的截图缩到 0.34 倍，字全糊；改 1120 宽后缩放比接近 1，表单标签能读。
* **排版收口**
    * 正文 14.5px / 行距 1.85；`h1` 23px，`h2` 15.5px 且下划线加粗到 2px；单元格 padding 加到 8×12；代码块加左侧竖条。
    * **表格列宽按比例分配**：Qt 默认把两列摊成一半一半，「项」列宽得离谱。`table()` 支持 `widths`，两列默认 28/72，`<th width="28%">` 生效后才左窄右宽。

### 新增：界面字号的高 DPI 适配

面板原先只有 0.85 ~ 1.3 的手动档，与屏幕无关；其余尺寸（间距、圆角、固定宽高）也完全不跟着字号走。这一轮把字号做成「一路管到底」的倍率。

* **默认档改为「跟随画面」**，按屏幕物理 DPI 自动定档：< 130 → ×1.00，130 ~ 180 → ×1.10，≥ 180 → ×1.18。`font_scale` 存 0 即表示自动（旧配置里的 1.0 仍然有效，等于手选「标准」）。
* **倍率不只缩放字号**：`build_qss` 用 `scale_px()` 把 QSS 里所有 `Npx` 统一乘一遍，`padding` / `margin` / `border-radius` / `min-height` 一起走；**1px、2px 不动** —— 那是边框与分隔线，放大后线条变粗显得笨重。
* **写死尺寸的控件也一起缩**：侧栏宽 214、卡片图标 40、搜索框 260、圆形「?」30、表单标签列宽 168/120、卡片内边距 14/13/14/12、网格间距 12 全部改走 `panel_qt.px()`。`ToolCard.resize_parts()` / `Sidebar.resize_parts()` / `CardGrid.refresh_spacing()` 负责切换档位时重设。
* **补上 Qt 不管的那一环**：Windows 辅助功能里的「文本大小」（注册表 `TextScaleFactor`）是独立于显示缩放的设置，Qt 一律不理会。`panel_qt.text_scale()` 直接读它并乘进倍率，用户调了才有反应。
* **换屏重算**：`showEvent` 里挂 `windowHandle().screenChanged`，窗口拖到另一块 DPI 不同的屏时重算自动档并重新定窗口大小。手选档位不动。
* **窗口尺寸按屏幕算**：原先写死 `resize(1200, 780)`，在 150% 缩放的 1366×768 屏上（逻辑只有 911×512）会直接超屏，标题栏跑到屏幕外拖不动。改为取可用区域的 82% × 86% 并夹在 880×560 ~ 设计尺寸之间，居中且 `setMaximumSize` 保证不出屏。
* **设置页**字号档位扩到七档（跟随画面 / 很小 / 较小 / 标准 / 较大 / 很大 / 特大 = ×0.85 ~ ×1.5），下方实时写出「实际倍率 ×1.10（正文约 20 物理像素）· 显示缩放 150% · 屏幕 161 DPI」，不必靠猜。
* **帮助文档也跟着缩**：`HelpPage.set_ui_scale()` 把文档 HTML 里的 `font-size` 乘同一倍率，只改字号不动 padding，图片仍按视口算。

一个必须记下的坑：`apply_theme` 里原先传的是 `self._font_scale`，而「跟随画面」存的是 0 —— 乘进 `scale_px` 后所有尺寸变成 1px，**整个面板的文字消失、只剩横杠**。截图时才发现。现在 `build_qss` 自己夹在 0.8 ~ 2.0，`apply_theme` 传 `_UI_SCALE`。

界面字号一变，`resources/help/img/` 的两套截图全部过期，已重截 38 张并重生成 23 篇文档。

### 新增功能

* **`watch_notes`（面板选项 16）**
    * 笔记目录监测：定时检测改动并提交推送；按设定条数上限裁剪 git 历史（内容、提交信息与时间都保留），让历史长度收敛。
    * `--dir` 可指定任意仓库目录；状态持久化，中断后默认恢复，`--fresh` 重新开始。
* **`panel_qt`：图形总面板（Qt 桌面窗口）**
    * 卡片式列出全部 16 个工具，按组分区，搜索过滤（`/` 聚焦、`Esc` 清空或关输出面板）。
    * 交互面板类工具弹独立控制台窗口（`CREATE_NEW_CONSOLE`），`input()` 行为与命令行一致；一次性命令类（`check_sensitive` / `sync_paths`）捕获输出，显示在窗口下方输出面板，跑完不会一闪而过。
    * 卡片显示状态点、耗时、退出码；运行中可停止（`taskkill /T /F` 连子进程）。
    * 列数随窗口宽度重排；结果很少时卡片宽度有上限，不会被拉成横幅。
    * 依赖 PySide6-Essentials，装在工具专用 venv，不碰系统 Python；`run_panel.bat` 双击启动。
* **`panel_core`：面板共用逻辑**
    * 工具清单、启动、停止、运行状态集中在这里，Qt 版与网页备用版都调用，避免两套启动规则漂移。清单仍来自 `launcher.MENU`，只有一处定义。
* **`panel_actions`：工具真正 GUI 化**
    * 不重写工具，而是给它们的**既有命令行接口**配表单：界面填参数 → 拼命令行 → `QProcess` 跑 → 输出留在面板里。工具代码一行未改，命令行接口就是稳定 API。
    * 已配表单：`new_note`、`outline_tool`、`clean_aux`、`repo_check`、`check_sensitive`、`sync_paths`、`commit`、`spec_sync`、`pdf_upright`、`watch_notes`。
    * 表单引擎：字段类型 text/int/path/file/choice/check；`show_if` 支持字段联动（切换操作只显示相关字段，隐藏字段不进参数）；路径字段带「浏览…」；破坏性操作默认不勾选。
    * 纯交互工具（`git_setup`/`manager`/`symbols`/`progress`/`note_tools`/`video2text`）走**内嵌终端**：`QProcess` 交互式运行，输出显示在面板，输入行回车写进子进程 stdin。**至此全部 16 个工具都能在面板内使用，不再需要弹外部控制台。**
    * 子进程统一注入 `PYTHONIOENCODING=utf-8`，否则 Windows 下 stdin 按 GBK 读，中文输入会乱码。
* **三个纯交互工具补上非交互子命令**（原有交互行为不变）
    * `manager`：`--status`、`--commit-all [--push-only] [--msg]`、`--create-repo [--selection] [--account]`、`--set-root <路径> [--account]`。做法是给 `set_root` / `commit_push_all` / `create_repo` 加可选参数，**默认 None 时仍走原提问流程**，图形面板传值时才走非交互。
    * `note_tools`：`--note <名字>` 跳过选本菜单，`--action commit|exercise|intro-summary`，`--scope both|intro|summary`，`--yes` 免确认。
    * `git_setup`：`--check`、`--account [--name] [--email]`、`--ssh [--gen-key] [--write-443] [--test]`。
    * `note_tools` 跑笔记目录下的脚本时，打包成 exe 后 `sys.executable` 是 exe 本身，改成 `exe --exec <脚本>`，否则子脚本跑不起来。
    * 至此 **16 个工具全部有可视化表单**。
* **`tools.ico` 与 `make_icon.py`：exe 图标**
    * 用 Qt 现画一个工具箱图标（深蓝圆角底 + 宽扁提手 + 箱体分割线与搭扣），导出 16/24/32/48/64/128/256 七档 PNG，按 ICO 格式拼成 `tools.ico`（19 KB）。
    * ICO 允许直接内嵌 PNG；`QPixmap.save` 只认 `QIODevice`，Python 的 `BytesIO` 不行，用 `QBuffer`。
    * 打包时 `--icon` 嵌进 exe，PE 资源里能看到 `RT_ICON` 7 条 + `RT_GROUP_ICON` 1 条。
    * 画图标时 Qt6 的 `QRectF` 在 `QtCore` 里，不在 `QtGui`。
* **`symbols` 补两个能力**
    * `--extract`：把各笔记相对模板的新符号提取进提取档案（只写工具自己的档案，不动模板，因此不受 `--write` 门控）。
    * `--add-name <名> --add-def <定义> [--add-comment] [--add-overwrite]`：非交互引入新记号，校验规则与交互版一致（只允许字母、括号配对、无裸 `%`、覆盖要显式声明）。
    * 写入部分抽成 `_write_symbol()`，交互版与命令行版共用同一条写入路径，避免两套逻辑漂移。
* **面板改成纯 GUI：去命令行**
    * 卡片上只留一个「打开」按钮，删掉「控制台」入口、底部输出区与内嵌终端；结果全部收进表单页。
    * 结果区改成「结果卡片」：标题 + 摘要 + 复制按钮 + 表格或整理过的文本。输出经 `_clean_output()` 清洗，去掉命令行回显、压缩空行。
    * 表格化的工具：`manager`（仓库/分支/改动/领先落后/远程）、`repo_check`（区域/仓库/结果）、`clean_aux`（目录/文件数/大小/类型）；spec 里用 `result` 声明列、解析函数与摘要函数，其余工具走文本模式。
    * 表单执行状态通过信号同步到卡片（执行中 / 已完成 / 已中止）。
    * 表格列宽：首列 Stretch（仓库名长短不一），其余 ResizeToContents；交替行底色要在 QSS 里显式给 `alternate-background-color`，否则会落到系统高亮蓝。
* **窗口与任务栏图标真正生效**
    * `--icon` 只改 exe 自身的 PE 资源，**标题栏图标另说**：Qt 会吞掉外部发的 `WM_SETICON`，改不动；标题栏实际用窗口类图标（`GetClassLongPtr(GCLP_HICON)`），Qt 建类时放的是它自己的默认图标 ⇒ 运行时用 Win32 `SetClassLongPtrW(hwnd, GWL_HICON, h)` 改类图标，并补 `ICON_BIG2`（Vista+ 标题栏优先取它）。
    * **不设 AppUserModelID**：设了之后 Windows 11 任务栏改为取窗口级图标，而那个取不到，会显示系统默认图标（白纸）。不设就用 exe 资源里的图标，那份是对的。
    * 运行时图标从包里读：`--add-data tools.ico;.` + `app_icon()` 按 `sys._MEIPASS` 定位。
    * **图标缓存**：Windows 按路径缓存 exe 图标，换图标后任务栏/资源管理器仍是旧的，重启资源管理器不够，要删 `%LOCALAPPDATA%\IconCache.db` 与 `Microsoft\Windows\Explorer\iconcache_*.db` 再重启 Explorer。
    * 图标造型由工具箱改成**齿轮**：拱形提手加中间搭扣在 16px 下会被读成挂锁，齿轮没有这个歧义。
* **14 个工具的结果表格化**
    * 给每个工具的输出写解析函数：键值型（`git_setup`/`symbols`）、分节型（`new_note`）、问题型（`outline_tool`）、文件清单型（`note_tools`/`commit`）、检查项型（`sync_paths`/`spec_sync`）、PDF 清单型（`pdf_upright`）、合集型（`video2text`）、日志型（`watch_notes`）。
    * spec 里用 `result` 声明列名、解析函数、摘要函数，以及要拉伸的列（`stretch`）。解析不出结构时自动退回文本，摘要改为显示工具的结论句。
    * **执行后立即关闭子进程 stdin**：GUI 里没有终端可输入，任何 `input()` 会拿到 EOF 走各自的「取消」分支。少了这一步，需要确认的工具（如 `note_tools` 补导引小结）会一直挂着不返回。
    * `video2text` 默认操作改成只读的「列出合集」，避免一点就下载转写。
    * 没有字段的工具不再留一张空表单卡。
* **全局异常兜底**
    * GUI 程序没有 stderr，未捕获的 Python 异常会被静默吞掉 —— 表现是「点了没反应、应用挂住」，极难查。`sys.excepthook` 落盘 `_panel_error.log` 并弹窗。
    * ⚠️ Qt 的信号槽回调里抛异常不会退出应用，事件循环照转，整个界面看着像卡死。写 Qt 代码时务必装这个钩子。
* **修浅色主题下的显示问题**
    * **表头黑底白字** —— QSS 里表头底色用了半透明 `rgba(...)`，而 windows11 样式对 `QHeaderView::section` 的半透明背景会回落到系统色（深）。改用不透明的专用色 `head_bg`（深 `#383838` / 浅 `#EFEFEF`），并给 `QHeaderView` 本身也设背景。
    * **侧栏选中态不唯一** —— 组按钮与特殊按钮（帮助/设置）分属两个互斥组，`autoExclusive` 不跨组取消，会出现「核心工具」和「运行监测」同时高亮。改成显式清掉另一边。
    * **工具页侧栏不跟随** —— 打开工具时侧栏停在「设置」上。现在指向工具所属分组，返回时回到来时的分组。
    * **设置页复选框不对齐** —— `QCheckBox` 被拉伸、位置随文字长度漂移。改成固定宽度，说明文字缩进到控件起点。
    * **卡片图标发白** —— 图标块底色是半透明淡蓝，emoji 的浅色笔画融进去了。改成实色底 + 显式指定 `Segoe UI Emoji` 字体（QSS 里的 `font-family` 会被 QLabel 字体覆盖，不显式设会落到西文字体，彩色 emoji 变 monochrome）。工具 1 的 ⚙ 换成 🔀 —— ⚙ 在 Segoe UI Emoji 里是淡紫灰色，浅色主题下看不见。
    * **侧栏底部去 emoji** —— ⚙️/🔧/❓/🌙 在浅色主题下分别是紫灰齿轮、浅色扳手、深红问号、橙太阳，颜色不统一且部分看不清。改成纯文字「使用帮助 / 设置 / 深色主题」，上方加「其他」小标题分组。
* **彻底不弹命令行窗口**
    * 工具内部调外部命令时全部加 `creationflags=CREATE_NO_WINDOW`（10 个脚本：git_setup / manager / new_note / note_tools / repo_check / check_sensitive / commit / video2text / pdf_upright / workbench_pdf）。**GUI 程序启动控制台子程序时，Windows 会新分配控制台并弹黑窗** —— 少这一层，exe 里跑工具就会闪黑框。
    * `note_tools.run_in_note` 改为捕获子脚本输出再转回自己的 stdout，否则子脚本的打印在面板里看不到。
    * 窗口级用 `QProcess`（Qt 默认已带 `CREATE_NO_WINDOW`）。⚠️ **PySide6 没暴露 `setCreateProcessArgumentsModifier`**，这条 API 走不通；实测管道模式下 Qt 自己处理好了，不必干预。
* **表格列宽可拖动**
    * `QHeaderView` 从 `ResizeToContents`/`Stretch` 改成 `Interactive` —— 前两者会锁死列宽，拖不动。
    * 列宽初值按内容算（取该列最宽的一格 + 余量），并记进 `Tools/_panel_config.json`，下次打开恢复。
* **新增设置页与帮助页**（`panel_config.py` + `panel_pages.py`）
    * 设置页：主题（跟随系统/深色/浅色）、界面字号（四档，缩放 QSS 里的 px 字号）、破坏性操作二次确认、列宽记忆、恢复默认。
    * 帮助页：完整用法说明 + 16 个工具的用途清单表。帮助正文用 **HTML 而非 Markdown** —— Qt 的 Markdown 解析器只支持标题/粗体/代码块，列表与表格的样式几乎不可调。
    * 配置持久化在 `Tools/_panel_config.json`，删掉即回默认。
* **界面细节**
    * 返回按钮从一行小字改成正式按钮「← 返回工具列表」（Secondary 样式，最小 132×32）。
    * 工具页去掉标题下方的副标题小字。
    * 快捷键：`Ctrl+1`~`Ctrl+6` 跳组、`Ctrl+,` 打开设置。
    * `pdf_upright` 的输入目录给默认值 `Exam`，不用每次手填。
* **`build_exe`：打包成 exe**
    * `build_exe.py` 调 PyInstaller 产出 `Tools/LaTeX-Toolbox.exe`（单文件约 37 MB，`--onedir` 为目录模式），自带 Python 运行时与 PySide6，目标机器无需装环境。
    * exe 需要跑工具时把自己当解释器：`--exec <脚本> -- [参数]`，工具脚本仍从真实 `Tools/` 读取（它们要操作真实工作区，不能进解包临时目录）。**此机制同日已改为优先用工具 venv 的解释器**，见「第四轮：打包后的 exe」。
    * **GUI 子系统程序忽略 `CREATE_NEW_CONSOLE`**，故在 `--exec` 里主动 `AllocConsole()` 再绑 `CONOUT$` / `CONIN$`；不这么做交互工具的 `input()` 直接 EOF、窗口一闪而过。
    * `--selftest` 自检：打印 frozen 标记、工具根、工作区、缺失项，并用一次性命令走通「exe 起子进程 → 捕获输出」。
    * 打包前自动关闭同名旧进程（否则文件被占用，PyInstaller 报 PermissionError）。产物与 `_build/` 已加入 `.gitignore`。
* **`panel_gui`：网页备用版**
    * Qt 不可用时的兜底：纯标准库、浏览器界面、零依赖。
    * 只绑 `127.0.0.1`；POST 校验内嵌随机令牌与 `Host` / `Origin`。

---

## 2026-11-07 更新概览

为 `video2text` 补一节面向调用方的快速路径。程序本身无改动。

### 优化与改进

* **`video2text` 文档补「快速路径」**
    * 在〈用法〉之前加四条，供 agent 与脚本直接调用时参照：默认命令、产物位置、失败补做入口，以及三种必须先征询再使用的扩权参数。
    * 目的在约束调用方的常见偏差 —— 自行编排「先探测再转写」、按标题而非集 ID 取产物、未经确认就加扩权参数。
    * 只写调用约定，参数表仍以〈用法〉为唯一出处，避免两处描述不一致。

---

## 2026-10-28 更新概览

修复符号库管理（面板选项 5）的引用统计与删除安全问题，把命令行 `--drop` 与面板的行为拉齐；同日补全工具文档、纳入 `tex2docx`，并修掉 `video2text` 与 `repo_check` 的两处缺陷。

### 新增功能

* **纳入 `tex2docx/preprocess.py`**
    * 把 LaTeX 论文转成 `.docx` 时，Pandoc 直接转会坏在定理环境、交叉引用、自定义宏与无编号标题上。本脚本先把这些改写成 Pandoc 能处理的形式，再交给 Pandoc。
    * 按约定**不占面板选项**：目录随仓库分发，需要时进目录单独运行。
* **`video2text` 支持反相片源**
    * 解码时取双声道、抽样统计相关系数，低于 −0.5 视为反相，改用 `(L−R)/2` 降混 —— 直接 `(L+R)/2` 会让反相的两个声道互相抵消，转出来是空的。
    * 单边静音或纯直流时相关系数无意义，退回常规降混。降混策略标识写进检查点绑定，策略一变旧检查点自动失配、从 0 块重转。

### 缺陷修复

* **`video2text` 的锁把复用的 PID 当成活进程**
    * 断电重启后 PID 会被新进程复用，只看「PID 是否存在」会误判锁仍被占用，于是一直无法开工。
    * 修法：核对属主进程的创建时刻是否晚于锁写入时刻（留 120 秒时钟漂移余量），判为失效锁并给出说明。
* **`repo_check` 的区域前缀在同一份报告里不一致**
    * `--area all` 时笔记区不带区域前缀、模板区与工具区却带；判断条件里有一个分支永远走不到。
    * 修法：只在 all 模式下给区域前缀，单区查询一律不带。
* **引用统计漏掉符号源笔记**
    * 统计引用时使用的笔记列表来自分发用的扫描结果，而该扫描按设计会跳过与模板同源的目录，导致符号源笔记自身的正文不在统计范围内。
    * 后果：源笔记正文里在用的符号被判为「未引用」，删除时不给出任何警告。
    * 修法：分开两个范围 —— 分发仍用原来的列表，统计另加源笔记自己。
* **注释前的零间距被改写**
    * 定义体与 `%` 之间本无空白的行，就地修改后会被补上四个空格，使整列注释错位。
    * 修法：把「没有注释」与「有注释但零间距」区分记录。
* **定义体里的裸 `%` 未被拒绝**
    * 输入含未转义 `%` 的定义体，会让该行后续内容被当作注释，定义残缺；此后该行无法再被解析，只能手工修改文件。
    * 修法：写入前检测并拒绝，提示改写为 `\%`。
* **符号库内部依赖未计入**
    * 正文未使用、但符号库里另有定义在调用的宏（辅助宏）同样被判为零引用，删除后会让调用它的定义一并失效。
    * 修法：把符号库内部定义之间的调用也纳入统计，清单中用 `†` 标出；删除前列出全部调用方。
* **参数说明不做校验**
    * 参数说明只接受 1–9 的数字，旧版照抄输入会写出非法定义。现在非法输入直接拒绝。
* **只有源笔记时无法进入选项 5**
    * 前置判断沿用了分发列表，只有符号源笔记、尚未分发出副本时会直接退出。改为按统计范围判断。
* **命令行 `--drop` 静默删除**
    * 面板已加引用警告，命令行仍无提示。现在删除前打印正文引用次数与库内调用方，但不拦截、退出码不变，供脚本调用。

### 优化与改进

* 注释起点的判定改为按连续反斜杠个数的奇偶判断，`\\%`（换行命令后紧跟 `%`）不再被误当作转义。
* 符号清单的命令名列宽随最长名字自适应，长名字不再把次数列挤歪。
* 选中符号时一并回显「库内 N 处」，避免只看正文的 0 次。
* **补齐工具文档**：`git_setup`、`check_sensitive`、`clean_aux`、`note_tools`、`outline_tool`、`pdf_upright`、`repo_check`、`show_memory` 各补一份同名 `.md`；`new_note.md` 补 `--template` / `--levels`，`commit.md` 补 `--check`。
* **文档按「只讲功能」清理**：删去本机状况、实测数字、验收证据与发布边界；`README.md` 的 `launcher.py` 一节原先整段是工作台内容，拆出独立的 `progress/` 一节；目录结构补上 `pdf_upright` 与 `tex2docx`。
* 订正 `pdf_upright` 的实现说明：现在是旋转烘进几何、`/Rotate` 归 `0`，旧文写的是 `/Rotate` 置 90。

## 2026-10-22 更新概览

新增 PDF 转正工具，随后把它的输出方式改为就地覆盖。

### 新增功能

* **PDF 转正（面板选项 15，分组「PDF 处理」）**
    * 针对一类导出的坏 PDF：横版幻灯片被打印成 A4 纵向、内容整体转了 90°，而页面 `/Rotate` 恒为 0，阅读器不会自动纠正。
    * 修法取页面几何、不重编码像素：把 90° 旋转烘进内容流，`/MediaBox` 与 `/CropBox` 都换成幻灯片本体的 16:9 尺寸，`/Rotate` 归 0 —— 方向只由几何决定，不再依赖阅读器对 `/Rotate` 的解释。画质与原件等同，体积基本不变。
    * 逐页判定，四条同时满足才动手：纵向页、无文字层、最大图像竖立、占页面面积 40% 以上。已转正的页面跳过，重复跑不会二次旋转。
    * 面板分四步：问目录（可粘贴或拖入；回车取当前目录；直接给一份 `.pdf` 则只处理这一份）→ 编号列表（含页数、页面尺寸、`需转正（N/M 页）`）→ 按编号选（`a` / `1,3` / `2-4`，与 `clean_aux` 同一套语法；`r` 切子目录、`o` 换输出目录）→ 执行后回到同一目录的列表。选到标「跳过」的项只提示、不报错。命令行对应 `-r/--recursive`。
    * 递归扫描自动排除输出目录，不把自己的产出当输入。
    * 依赖 `pymupdf`。启动时若当前解释器缺它，按 `PDF_UPRIGHT_PYTHON` → PATH 上的 `python` → 本地 Python 环境目录依次探测，找到装了的换过去重跑。

### 优化与改进

* **输出改为就地覆盖**：不再另存 `横向版/` 副本。覆盖前把原件备份到系统临时目录 `<TEMP>/pdf_upright_backup-<时间戳>/`，路径打在输出里可随时取回；用 `-o`（或面板 `o`）则原件完全不动。
* 文档同步：`README.md`（工具表新增一行、新增完整章节、依赖说明改为两个第三方依赖、总面板编号 1–14 改为 1–15）、`launcher.py`（`MENU` 加 15 与顶部说明表）。选项 1–14 编号不变，提交项仍为 12。

## 2026-10-15 更新概览

新建笔记时可选生成导引与小结，并新增对既有笔记的批量补齐；同批删除旧版写作追踪表。

### 新增功能

* **`new_note.py` 的 `--intro` / `--summary`**
    * 按大纲生成骨架时一并建导引与小结，默认都不带；交互式引导会问一句：`y` 都建 / `i` 只建导引 / `s` 只建小结。
    * 规则照模板的既有约定：最外层建 `intro.tex`（无编号标题 ＋ `\phantomsection` ＋ `\addcontentsline`，手工进目录），所有会产生目录的层建 `Summary/`（`index.tex` ＋ `intro.tex` ＋ `01_summary.tex`）；小结自己占下一级的编号标题，内部导引与条目再降一级，所以节的小结用到 `\subsubsection`。导引只加在最外层，末层是 `.tex` 文件、不加小结。
    * 对应的 `\input` 插进该层 `index.tex`：导引在第一条 `\input` 之前（开头的注释行留在最上面），小结在附录之前（没有附录就接在最后一条 `\input` 之后）；已存在的那一行不重复插。新文件里只留一行 `%` 注释写「这一节该写什么」，不写正文占位句。
* **`note_tools.py` 的「补导引与小结」**
    * 对既有笔记做同样的事：扫描 `Content/` 现有结构、按 `main.tex` 与正文里出现过的命令推断层级，先给「将新建几个文件、改动几个 index.tex」的清单、确认后才写入，只补缺、不覆盖，可反复跑。
    * 实现直接复用 `new_note.py`，不另写一份规则。

### 优化与改进

* 文档同步：`README.md`（new_note 用法与新增「导引与小结」一节、note_tools 一节）、`new_note/new_note.md`、`launcher.py` 面板文字。

### 缺陷修复

* **删除旧版写作追踪表**
    * 移除 `progress.py`、`progress_ui.html`、`progress.conf(.example)`、`progress_marks.json(+.bak)`、`progress_settings.json(+.bak)`、`progress_report.md`，以及退役拒绝入口 `workbench_legacy.py`；`progress/` 下只保留工作台（面板选项 4）。
    * 同步清理文档中的旧版章节：`README.md`、`progress.md`、`progress_design.md`、`launcher.py` 注释与 `.gitignore` 规则；旧版使用说明与设计正文不再保留。
    * 测试相应调整：删除 `test_legacy_retired.py`，从 `test_multi_permission_legacy.py`、`test_retirement_independent.py` 移除依赖旧模块的用例；其余「旧名不得出现」的守卫测试保留。

## 2026-10-14 更新概览

工作台的 PDF 预览新增一条备用打开路线：用户显式点击的独立标签页。

### 新增功能

* **独立标签页打开 PDF**
    * 只有完整已验证的 Blob 加载后才启用，目标重置时禁用；以 `noopener` 打开并携带目标页码，不自动打开、下载或修改 PDF 与后端。

### 已知限制

* 嵌入 Blob 与直接 HTTP iframe 仍受限、状态为未验证，根因未确认，不宣称全部 PDF 路由可用。产品与有界诊断测试已冻结，不继续猜测性修改阅读器。

## 2026-10-13 更新概览

工作台的保存许可模型成型，并划清发布边界。

### 优化与改进

* **保存许可按书独立**
    * 需同时满足写入开关、逐书独立 ID、绝对写入根完整匹配三项；外部同名书、复制 ID 的别名或不同根均不继承许可。
    * 启动及每次写请求重新核验根与身份；root 变化清空许可根与全部 ID。
    * 默认只读；`allow-open` 与保存许可相互独立，不因授予保存而自动开启。
    * 保存许可属本机配置，不随代码分发，也不写入公开库。
* **旧工作台入口与旧标记迁移保持退役**，历史源数据留存，不重新迁移、认领或改变审核结论。
