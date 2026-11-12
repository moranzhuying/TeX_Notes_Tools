# LaTeX 笔记工具集

一套维护本地 LaTeX 笔记的工具，配合「笔记写作」等模板使用。

| 脚本 | 用途 | 详细说明 |
|---|---|---|
| `launcher.py` | **命令行总面板**：列出并调起下面各工具 | 见下 |
| `panel_qt.py` | **图形总面板**（Qt 桌面窗口）：卡片式列出全部工具，一键启动控制台，一次性命令的结果显示在下方面板 | 见下 |
| `panel_core.py` | 面板共用逻辑（工具清单 / 启动 / 停止 / 状态），Qt 版与网页备用版都调用它 | 见下 |
| `panel_gui.py` | 图形面板的**网页备用版**：没有 Qt 环境时用，纯标准库、浏览器界面 | 见下 |
| `git_setup/git_setup.py` | Git 基本信息：环境检测 / 配置账户 / 配置 SSH | `git_setup.md` |
| `manager/manager.py` | 笔记工作区管理：仓库状态 / 批量提交 / 建仓库 | `manager.md` |
| `symbols/symbols.py` | 符号库管理：提取 / 回填 / 刷新补全 / 分发 / 删除 / 修改 | `symbols.md` |
| `progress/workbench_launcher.py` | 总面板选项 4：工作台启动面板，root / 端口 / 独立打开权限配置，默认只读、逐书保存独立根 / 永久 ID 许可 | 见下 |
| `progress/workbench_server.py` | 工作台 HTTP 服务：默认只读、禁止调起编辑器；实时轻量导航、按需全文 / 问题 / 阶段统计 / 报告 / PDF；受控写入与 TeXstudio 打开须另行显式授权 | `progress.md` |
| `progress/workbench_readonly.py` | 工作台只读原型：校验资料绑定与审核记录，导出快照；不迁移或修改笔记 | `progress.md` |
| `progress/workbench_store.py` | 受控保存底层：书籍身份、按书计划、审核补丁、版本检查与备份恢复 | `progress.md` |
| `new_note/new_note.py` | 从模板创建一本新笔记（复制骨架 → 清测试内容 → `git init`） | `new_note.md` |
| `outline_tool/outline_tool.py` | 大纲的创建 / 导出 / 校验 | `outline_tool.md` |
| `note_tools/note_tools.py` | 单本笔记的入口：提交 / 习题模式 / 补导引与小结 | `note_tools.md` |
| `clean_aux/clean_aux.py` | 清理编译产物（aux / log / xdv / fls / synctex …），无参数即交互面板 | `clean_aux.md` |
| `repo_check/repo_check.py` | 仓库体检：规范文件 / 误跟踪 / 未提交 | `repo_check.md` |
| `check_sensitive/check_sensitive.py` | 提交前扫描本机信息（用户名 / 本机路径 / 专有词） | `check_sensitive.md` |
| `sync_paths/sync_paths.py` | 配置路径检查与修复（**工作区专用，不随仓库分发**） | `sync_paths.md` |
| `commit/commit.py` | 一键提交：`add → commit → push`，含 `--check` 模式供 git 钩子调用 | `commit.md` |
| `video2text/video2text.py` | 视频 / 合集增量转文字：默认仅字幕，可选本地转写与分块恢复 | `video2text.md` |
| `spec_sync/spec_sync.py` | 项目规范副本一致性：比对原件与副本，不一致时可用原件覆盖（**工作区专用，不随仓库分发**） | `spec_sync.md` |
| `pdf_upright/pdf_upright.py` | PDF 转正：把「横躺」的课件 PDF 就地转正为 16:9，不重编码 | `pdf_upright.md` |
| `watch_notes/watch_notes.py` | 笔记目录监测：定时提交推送 + 滚动删除最早一条 git 记录，状态可恢复 | `watch_notes.md` |
| `show_memory/show_memory.py` | 查看工作记录（已从面板移除，需要时单独运行） | `show_memory.md` |
| `tex2docx/preprocess.py` | LaTeX 转 Word 预处理：把定理环境 / 交叉引用 / 自定义宏改写成 Pandoc 能转换的形式（**非面板项**） | `preprocess.md` |

## launcher.py — 命令行总面板

运行 `python Tools/launcher.py` 进入总面板。菜单由 `launcher.py` 里的 `MENU` 表驱动，**一个面板选项对应一个同名目录**，新增工具就是新建目录并在表里加一行。

- 选项分五组：核心工具、创建与维护、信息安全与提交、素材与转写、PDF 处理。
- 除「提交前本机信息扫描」「配置路径检查」两项是带参数直接跑完再回面板，其余各项都是**进入自己的交互面板**，在里面完成操作，不必再敲命令行参数。
- 带 `*` 的是提交本工具集到 GitHub（提交项编号 12）。
- 子进程以参数列表启动，不经过 shell；「后台」模式用于服务类工具，启动后立即返回面板。

每个工具也可以进自己的目录单独运行，配置与运行档案都放在它自己目录里。

## panel_qt.py — 图形总面板

```bash
python Tools/panel_qt.py              # 直接开窗口
```

也双击 `Tools/run_panel.bat`（会优先用工具 venv 里的解释器，回退到 PATH 的 python）。

**依赖**：PySide6-Essentials，装在 `.workbuddy/binaries/python/envs/default`，不碰系统 Python：

```bash
<venv>/Scripts/python.exe -m pip install PySide6-Essentials     --index-url https://mirrors.aliyun.com/pypi/simple/
```

界面按 Fluent / WinUI 风格做：左侧竖向导航把工具分成六组，右侧是当前组的卡片流，顶部一条工具栏放标题、搜索与主题开关。深浅主题跟随系统（读 `AppsUseLightTheme`），左下角可手动切换。

做的是**启动器**，不是把 16 个工具各重写一遍。清单来自 `launcher.MENU`（经 `panel_core` 转成界面用的结构），命令行面板、Qt 面板、网页备用版共用同一份，不会漂移。

**面板是纯 GUI，没有任何命令行入口** —— 卡片上只有一个「打开」按钮，点进去就是表单页：选操作、填参数、点「执行」，结果以界面元素呈现在下方（表格 / 摘要 / 文本），不弹控制台，也没有内嵌终端。

结果区是一张「结果卡片」：标题、一句摘要（如「13 个仓库，1 个有未提交改动」）、复制按钮，主体是表格或整理过的文本。**14 个工具的结果是表格**，两个是文本（输出本就是文字或服务日志）：

| 工具 | 表格 |
|---|---|
| `git_setup` | 项目 / 值（环境检测项） |
| `symbols` | 检查项 / 结果 |
| `new_note` | 类别 / 条目（按「复制骨架」等小节分组） |
| `outline_tool` | 位置 / 问题 |
| `note_tools` | 动作 / 文件（新建、修改） |
| `manager` | 文件夹 / 分支 / 改动 / 领先落后 / 远程 |
| `repo_check` | 区域 / 仓库 / 结果 |
| `clean_aux` | 目录 / 文件数 / 大小 / 类型 |
| `sync_paths` | 状态 / 位置 / 键 / 值 |
| `commit` | 状态 / 文件 |
| `spec_sync` | 状态 / 原件 / 副本与哈希 |
| `pdf_upright` | 文件 / 页数 / 尺寸 / 结论 |
| `video2text` | ID / 标题 / 进度 |
| `watch_notes` | 时间 / 级别 / 消息 |
| `progress`、`check_sensitive` | 文本（前者是服务日志，后者本来就是一句话结论） |

表格化在 spec 里声明：列名、解析函数、摘要函数；解析不出结构时自动退回文本，并把工具的结论句显示成摘要。

做法不是把工具重写一遍，而是**给每个工具的既有命令行接口配一张表单** —— 界面填参数 → 拼成命令行 → `QProcess` 跑真脚本 → 输出留在面板。工具本身的命令行接口就是稳定 API。

为此给三个原本只有交互菜单的工具补了非交互子命令（默认行为不变，不带参数时仍走原交互面板）：

| 工具 | 新增子命令 |
|---|---|
| `manager` | `--status` / `--commit-all [--push-only] [--msg]` / `--create-repo [--selection] [--account]` / `--set-root <路径> [--account]` |
| `note_tools` | `--note <名字>` / `--action commit\|exercise\|intro-summary` / `--scope both\|intro\|summary` / `--yes` |
| `git_setup` | `--check` / `--account [--name] [--email]` / `--ssh [--gen-key] [--write-443] [--test]` |
| `symbols` | `--extract`（提取到提取档案）/ `--add-name <名> --add-def <定义> [--add-comment <注释>] [--add-overwrite]` |

`symbols` 的写入部分抽成了 `_write_symbol()`，交互版与命令行版共用同一条写入路径。

表单引擎：字段类型 text / int / path / file / choice / check；`show_if` 支持字段联动（切换操作只显示相关字段，隐藏字段不进参数）；路径字段带「浏览…」；破坏性操作默认不勾选，先出预览再决定。

工具本身的命令行接口仍然保留可用（`python Tools/xxx/xxx.py`），但面板里不再暴露它们 —— 那是实现细节，不是给你用的入口。
- 卡片：图标 + 标题 + 说明 + 状态 + 操作，同排等高；主按钮进表单/终端，次按钮仍可弹外部控制台。
- 搜索：`/` 聚焦，跨组匹配后单独成页并显示命中数，`Esc` 清空回到当前组。
- 窗口变宽时卡片列数自动重排；只搜到一两个结果时卡片不会被拉成横幅。

### 打包成 exe

```bash
<venv>/Scripts/python.exe build_exe.py            # 单文件，约 37 MB
<venv>/Scripts/python.exe build_exe.py --onedir   # 目录模式，启动更快
```

产物 `Tools/LaTeX-Toolbox.exe`，自带 Python 运行时与 PySide6，**目标机器不需要装任何环境**，双击即开。`run_panel.bat` 会优先启动它。

图标是 `Tools/tools.ico`（多尺寸，7 档），由 `make_icon.py` 用 Qt 现画现生成：

```bash
<venv>/Scripts/python.exe make_icon.py     # 改样式后重跑即可
```

打包时 `--icon` 嵌进 exe（PE 资源里能看到 `RT_ICON` 与 `RT_GROUP_ICON`），同时 `--add-data` 把 ico 也打进包，运行时从解包目录读。

窗口图标分两处来源，各走各的：

- **标题栏**：`Qt` 的 `setWindowIcon` 只设窗口级图标（`WM_SETICON`），而 Qt 会吞掉外部发的 `WM_SETICON`，改不动。标题栏实际用的是**窗口类图标**（`GetClassLongPtr(GCLP_HICON)`），Qt 建类时放的是它自己的默认图标，所以运行时用 Win32 直接改类图标。
- **任务栏**：用的是 exe 资源里的图标。**不要设 AppUserModelID** —— 一设，Windows 11 就改为取窗口级图标，而那个取不到，会显示系统默认图标（一张白纸）。

**换了图标后任务栏/资源管理器仍显示旧的**：Windows 按路径缓存了 exe 图标，重启资源管理器不够，要清缓存：

```bat
del /f /q "%LOCALAPPDATA%\IconCache.db"
del /f /q "%LOCALAPPDATA%\Microsoft\Windows\Explorer\iconcache_*.db"
taskkill /f /im explorer.exe & start explorer.exe
```

（图标本身是齿轮而不是工具箱：拱形提手 + 中间搭扣在 16px 下会被读成挂锁，齿轮没有这个歧义。）

两个约束，来自「工具必须操作真实工作区」这一点：

- **exe 必须和工具脚本放在同一个目录**（默认就在 `Tools/`）。工具要读写 `LaTeX_Notes/`、`Template/`、`outputs/`，不能塞进 exe 的解包临时目录。
- 因此 exe 只带**运行环境和界面**，不带工具源码；换机器时整个 `Tools/` 一起拷。

实现上，exe 在需要跑工具时把自己当解释器：`LaTeX-Toolbox.exe --exec <脚本> -- [参数…]`。exe 是 GUI 子系统程序，`CREATE_NEW_CONSOLE` 对它无效，所以 `--exec` 里主动 `AllocConsole()` 再绑 `CONOUT$` / `CONIN$`，交互工具的 `input()` 才正常。

自检（打包后排查用）：

```bash
LaTeX-Toolbox.exe --selftest
```

会打印 exe 路径、frozen 标记、工具根、工作区、工具数量与缺失项，并用一次性命令走一遍「exe 起子进程 → 捕获输出」的完整链路。

**网页备用版** `panel_gui.py` 功能相同，纯标准库：`python Tools/panel_gui.py`，浏览器打开 `127.0.0.1:7658`。只在 Qt 装不上或坏掉时用；它同样只绑回环地址，POST 要内联随机令牌并校验 `Host` / `Origin`。

## progress/ — 写作工作台

选项 4 进入工作台的启动配置面板。进入面板不会自动启动服务；选择「启动服务」后由面板在后台线程管理服务并打开浏览器，选择「停止」或返回总面板时，若有运行服务，会先提醒保存网页未保存输入并要求确认；确认后关闭本面板创建的服务，端口立即释放。输入结束或中断也会清理本面板服务。端口占用时显示错误，不停止、不接管、不复用身份不明的现有服务。

面板可配置单个 `root`、端口（默认 `7656`）、独立 `allow-open` 开关和 TeXstudio 可执行文件路径。首次 `root` 从工具目录相对推导到工作区的 `LaTeX_Notes`；可改为其他书架目录或含 `LaTeX_Notes` 的工作区，含空格路径可直接输入、无需引号。空路径、文件、不存在目录、无 `*_Content.md` 书籍登记入口、登记冲突或绑定路径越界的目录均会拒绝；启动前逐本进行轻量导航校验。TeXstudio 留空时由服务自动查找，`allow-open` 默认关闭，开启不授予写入权限。

配置自动原子保存到 `progress/workbench_local.json`，已加入 `.gitignore`；相对 `root` 以配置文件所在目录为基准。配置损坏时显示可读错误并保留原文件，不回退后覆盖。改变 `root` 会清空旧写白名单、写入及打开权限。

默认只读。保存许可按书独立：需同时满足写入开关、逐书独立 ID、绝对写入根完整匹配三项；外部同名书、复制 ID 的别名或不同根均不继承许可；启动及每次写请求重新核验根与身份，`root` 变化清空许可根与全部 ID。`allow-open` 与保存许可相互独立，不因授予保存而自动开启。面板不初始化书、不迁移旧标记、不自动修改审核结论。

界面区分持久配置与当前服务的实际 root、端口、打开和写入权限；配置在下次显式启动时生效，运行期间禁止修改。

可独立运行 `python Tools/progress/workbench_launcher.py --no-browser`，进入同一面板但显式启动时不自动打开浏览器；`--config <JSON 路径>` 可指定隔离配置。独立服务 CLI 的默认端口同样为 `7656`，更多服务参数见 `progress/progress.md`。

**PDF 预览的已知限制**：独立标签页路线可用 —— 用户显式点击的「独立标签页打开 PDF」按钮，仅在完整已验证的 Blob 加载后启用，以 `noopener` 打开并携带目标页码，不自动打开、下载或修改 PDF 与后端。嵌入 Blob 与直接 HTTP iframe 仍受限、未验证，根因未确认，不宣称全部 PDF 路由可用。详见 `progress/progress.md`。


## manager.py — 笔记工作区管理面板

用于在**新环境**中准备 Git 与 SSH、配置远程账户，并统一管理笔记根目录下各子文件夹的仓库。

直接运行即进入数字面板（可多选，英文逗号分隔）：

```
==============================================================
  笔记工作区管理面板
==============================================================
  笔记根目录：<你的笔记根目录>
  已识别仓库：N 个 / 子文件夹 M 个
  远程账户　：<你的 GitHub 账户>
--------------------------------------------------------------
  1. 设置笔记根目录（扫描子文件夹，识别仓库）
  2. 显示各仓库状态（远程 / 分支 / 改动数 / 领先落后）
  3. 批量提交并推送（对所有有改动的仓库）
  4. 为未入版本控制的文件夹创建仓库并首次推送
  0. 退出
--------------------------------------------------------------
  可多选，用英文逗号分隔（如 1,3）
```

| 选项 | 功能 |
|---|---|
| 1 | 设置笔记根目录并扫描子文件夹，识别其中的 git 仓库 |
| 2 | 列出各仓库分支、改动文件数、相对远程的领先/落后提交数、远程仓库名；并列出尚未入版本控制的文件夹 |
| 3 | 勾选仓库后批量执行 `add → commit → push`；推送失败会自动重试并尝试备用端口 |
| 4 | 为未入版本控制的文件夹建仓库：补 `.gitignore` 与 `.gitattributes`、`git init`、首次提交并推送 |
| 0 | 退出 |

> 本面板只做**笔记区的仓库管理**；环境检测 / 账户 / SSH 在 `git_setup/`（总面板选项 1），
> 符号库、写作进度等子工具入口由 `launcher.py` 提供。

配置写在脚本同目录的 `manager.conf`：

```ini
root = D:/你的笔记根目录
account = <你的 GitHub 账户>
ignore =            # 额外忽略的目录名，逗号分隔
```

更详细的面板输出示例、推送失败处理流程与「与各脚本的分工」说明见 `manager.md`。

## symbols.py — 笔记符号管理面板

统一管理笔记根目录下各笔记的 `structure.sty` 符号库，并与 TeXStudio 补全文件 `custom.cwl` 保持同步。

直接运行即进入数字面板，可多选（英文逗号分隔，如 `1,3,5`）：

```
  1. 设置笔记文件夹并扫描目录结构（记录结构，只更新有差异的部分）
  2. 显示子文件夹结构（按英文名排序编号，可多选查看）
  3. 提取各子文件夹的符号
  4. 回填提取的符号（先 structure.sty，再 custom.cwl）
  5. 检验并管理符号（看引用情况，删除或修改任意符号）
  6. 引入新的记号（选归属子段，自动刷新补全）
  7. 退出
```

选项 5 先按笔记统计每个符号在正文（`main.tex` 与 `Content/**/*.tex`）中的引用次数（统计范围含符号源笔记本身），再列出整份符号库的清单（编号 / 命令名 / 次数 / 定义预览），`*` 标出正文与符号库内部都没人用的符号，`†` 标出正文没用、但库内还有定义在调用它的符号（行尾注明「库内 N 处」）。选中符号后可**删除任意符号**（仍被正文引用或仍被符号库内部定义调用的，会分两段警告并给出文件位置 / 调用方）或**就地修改**定义体 / 参数说明 / 注释；定义体不接受未转义的 `%`，参数说明只接受 1-9（可写 `2` 或 `[2][默认]`）。跨行定义整块删除，但不支持就地修改。

选项 6 在录入命令名 / 定义 / 注释后，会列出 `structure.sty` 中 `[模块 VI]` 内的编号子段（如 `6.1 代数`、`6.2 几何`、`6.3 分析`），输入数字即插入该子段末尾；也可选择新建子段（编号默认递增）或追加到模块末尾。写入模板后自动分发到各笔记并刷新 `custom.cwl`，无需再单独执行选项 4。命令名若已存在，会先确认再**原地覆盖**，不会产生重复定义。

命令名若是 LaTeX 内核已有的（`\H` `\i` `\d` `\Re` `\Im` `\S` 等），会自动生成 `\renewcommand` 而不是 `\newcommand` —— 后者对已定义命令会以 `Command \X already defined` 中止编译。另有 `CWL_SKIP` 名单：命中的符号保留在符号库中但不写进 `custom.cwl`（目前排除 `\H`，因为它由 TeXStudio 内置补全表覆盖）。

### 配置

把 `symbols.conf.example` 复制为 `symbols.conf`（与本脚本同目录），按实际路径填写：

```ini
root = D:\你的笔记根目录
template = D:\你的模板目录\笔记写作\structure.sty
cwl = %APPDATA%\texstudio\completion\user\custom.cwl
```

- `root` 下**每个含 `structure.sty` 的子目录**都被视为一本笔记
- `template` 是符号来源（共用模板的 `structure.sty`），必填
- `cwl` 可省略，默认取 `%APPDATA%\texstudio\completion\user\custom.cwl`

命令行参数（`--root` / `--template` / `--cwl-path`）优先于配置文件。

### 命令行模式（供批处理）

```bash
python symbols.py --all --write                        # 回填 + 刷新补全 + 分发
python symbols.py --cwl --write                        # 只刷新 TeXStudio 补全
python symbols.py --distribute --write                 # 只把模板分发到各笔记
python symbols.py --drop NAME --distribute --write     # 弃用某符号并同步全线
```

### 行为说明

- 默认只预览，**写入需显式加 `--write`**
- `structure.sty` 不生成备份（内容可随时由模板重新分发）；其他文件（如 `custom.cwl`）备份为 `.bak-<时间戳>`
- 目录结构统计会跳过隐藏目录、备份文件与 LaTeX 编译产物（`aux/log/out/toc/pdf` 等）
- 每个选项执行前清屏，画面只保留当前选项的内容


## check_sensitive.py — 提交前扫描本机信息

防止把本机路径、用户名或项目专有词推进公开仓库。三种模式：

```bash
python check_sensitive.py                # 扫暂存区新增行（供 git 钩子调用）
python check_sensitive.py --tracked      # 全量体检：扫所有已跟踪文件
python check_sensitive.py --dir <路径>   # 扫指定目录（非 git 目录也能用）
```

- 内置模式只匹配通用形态（Windows 与 Unix 的家目录路径）；其余词表放在工作区根的 `.sensitive-words.txt`，脚本**逐级向上**收集合并。
- **只扫新增行**：被删除的内容不构成泄露，所以「清理本机信息」这类提交不会被自己误拦。
- 命中时打印「文件 + 类别 + 内容片段」并以退出码 1 结束，可直接用作 `pre-commit` 钩子。

装钩子（每个仓库执行一次）：

```bash
cp Tools/check_sensitive/pre-commit "<仓库>/.git/hooks/pre-commit" && chmod +x "<仓库>/.git/hooks/pre-commit"
```

钩子装在 `.git/hooks/` 里（不进版本控制），重新 clone 后需重装；临时跳过单次检查用 `git commit --no-verify`。

> 用 `new_note/new_note.py` 新建的笔记仓库**会自动装好**这个钩子，不必再手工执行上面的命令。

## new_note.py — 从模板新建笔记

把「开始一本新笔记」的一串手工操作收敛成一步：复制骨架 → 按 **Markdown 大纲**生成
`Content/` → `git init` → 装提交前钩子 → 首次提交 →（可选）建远程并推送。

**不带参数运行会进入交互式引导**（从总面板进来就是这条路）：先问大纲 md 文件
（层级模式就从这份 md 里读，读不到会按结构推断并问你要不要代写进 md），再问笔记名、
模板、是否建远程，最后给出确认预览。笔记名与模板也能写在大纲 md 的元信息里，
写了就作为默认值。

```bash
python new_note/new_note.py                              # 交互式引导（推荐）
python new_note/new_note.py <笔记名>                      # 只建本地仓库（不生成骨架）
python new_note/new_note.py <笔记名> --push               # 同时建 GitHub 仓库并推送
python new_note/new_note.py <笔记名> --outline <大纲.md>   # 按 md 大纲生成骨架
python new_note/new_note.py <笔记名> --template <目录>
python new_note/new_note.py <笔记名> --dry-run            # 预演，不写任何文件
python new_note/new_note.py <笔记名> --outline <大纲.md> --levels textbook   # 覆盖 md 里的设置
python new_note/new_note.py <笔记名> --outline <大纲.md> --intro --summary  # 一并建导引与小结
```

### Math-Note 资料骨架试点

包含 `Source.md` 的模板启用资料模式，需 `--abbreviation <核定缩写>` 或大纲元信息 `abbreviation:`；交互引导也会获取缩写。`Source.md` 只保存书籍版本、语言等元信息；未知信息保留待填写。

三级 `chapter, section, subsection` 大纲生成 `缩写_Content.md` 和 `Materials/Cxx/Sxx/Nxx/{images,body.md,proof.md,record.md}`，每§一份 `review.md`，每行一目，审核阶段默认未检查。显式数字前缀用于固定编号，无前缀按同级顺序编号，目录须人工核对原书。复制到目录文件时剥离输入元信息，不带出模板等本地路径。

`Materials/` 的处理稿、记录、核对表和截图允许版本跟踪，随私有 Git 仓库备份。新书资料按大纲重建，不复制模板示例 Materials 或 BOOK_Content.md。资料补建不覆盖已有文件；无大纲只建元信息与待核对目录。试点不接受其它层级模式；不含 `Source.md` 的其它模板保持原层级流程。详见 [new_note.md](new_note/new_note.md)。

### 大纲 md 怎么写

文件头是可省的元信息块（`---` 包围、`键: 值`），随后用 **Markdown 标题的层级**表示
目录层级：最浅的一层就是最外层；行内用 `|` 分隔「目录名」与「中译名」（中译名可省，
省了就退用目录名）。可直接抄 `new_note/outline_example.md`。

```markdown
---
name: MyNote
template: Math-Note
levels: part, chapter, section
---

# Description_of_Formal_Mathematic | 数学的形式化描述
## Terms_and_relations | 项与关系
### Terms | 项
### Formative_constructions | 合式构造
```

| 规则 | 说明 |
|---|---|
| 元信息键 | `name`（笔记名）、`template`（模板目录名）、`levels`（层级命令），都可省 |
| 层级 | `#` 最外层、逐级往下；**不能跳级**（`#` 之后只能紧接 `##`） |
| 标题层级数 | 必须与 `levels` 的命令个数相同 |
| 目录名 | 英文/数字/下划线/连字符/点/逗号，不得含空白与 `\/:*?"<>\|`；中文写在 `\|` 右边 |
| 编号 | 不用手写 `1_` 前缀，脚本按出现顺序自动补；写了 `3_xxx` 就照用 |
| 空节点 | 某层节点下面没有更细的标题时，它的标题落进**该层自己的 `index.tex`**（占位） |
| 旧格式 | 不带 Markdown 标题的文件仍按旧「缩进 + `\|`」读；交互里输入 `paste` 可手动粘贴 |

### 层级模式（levels）

**写在 md 头部**（`levels: …`），工具不会另外问你 —— 一层一个 LaTeX 章节命令，
按**由外到内**排列、不可重复。管几个命令就是几层目录：末层是 `.tex` 文件，前面各层是目录。

```markdown
levels: chapter, section, subsection   # 1 级 \chapter、2 级 \section、3 级 \subsection
```

| 简写名 | 等价于 | 适用 |
|---|---|---|
| `textbook` | `chapter, section, subsection` | 常见教材：层1 目录＝章（默认写法） |
| `textbook-part` | `part, chapter, section, subsection` | 分「部」的大部头 |
| `two-level` | `chapter, section` | 两层：讲义 / 小册子 |
| `article` | `section, subsection` | 文章式：不分章 |
| `grouped` | `chapter, -, section` | 中间层只作分组、不产生标题 |

`-` 表示「这一层只作分组、不产生标题」。自定义就是直接列命令，例如
`levels: part, chapter, section`（部分-章-节）、`levels: chapter, -, section`。
以 `\part` 开头的序列不设简写名，直接写命令即可。

**不写也能跑**：脚本按标题层数推一个最接近的 —— 1 层→`section`；2 层→`chapter, section`；
3 层→`chapter, section, subsection`；4 层及以上→从 `part` 起按
`part → chapter → section → subsection` 顺延。此时：

- 交互式会问一句：**[Y] 用推断的 / [w] 把推断的 levels 写进 md 再用 / [n] 先去改 md**；
- 命令行只打印推断值与依据，并提示「想固定就在 md 头部加一行」，不弹提问。

**写了但与结构层数不符**同样处理：报出「按结构应该是 X」，交互式让你决定
（`[w]` 会把 md 里那行改成 X），命令行则给出改法并用 `--levels` 兜底。
只有层数实在凑不出合法序列（超过 LaTeX 的 7 级）时，才请你先改 md。

### 标题命令落在哪

以 `textbook`（`chapter, section, subsection`）为例：

| 位置 | 内容 |
|---|---|
| `main.tex` | `\chapter{层1中译}` ＋ 紧跟其后的 `\input{./Content/<层1>/index}` |
| `Content/<层1>/index.tex` | 只有 `\input`（指向各层2） |
| `Content/<层1>/<层2>/index.tex` | 只有 `\input`（指向各层3） |
| 该层2 的**第一个**叶子 | `\section{层2中译}` ＋ `\subsection{层3中译}` |
| 该层2 的其余叶子 | 只有 `\subsection{层3中译}` |

> 每一层的标题命令只在「它子树的第一个文件」里出现一次；换成
> `part, chapter, section` 时同理，只是命令依次变成 `\part` / `\chapter` / `\section`。

### 其他说明

- 只复制**源码与配置**（`.gitignore`/`.gitattributes`/`structure.sty`/脚本三件套/`Content`/`Figures` 等），
  跳过编译产物与 `__pycache__`。
- 模板里带 `Test` 字样的章节会被剔除，并同步移除 `main.tex` 中对应的 `\input`。
- `main.tex` 的 `\title` 改成笔记名；正文主体（`\mainmatter` … `\backmatter`）按大纲重写成
  「最外层标题命令 ＋ `\input`」的成对分组。
- **不提供大纲**时不会生成骨架：模板示例章已被剔除，`\mainmatter` 下只剩一个空的 `\part{笔记名}`，
  后续自己补 `Content/` 与 `\input`。
- `git init` 之后、首次提交之前，会自动把 `check_sensitive/pre-commit` 装进新仓库的 `.git/hooks/`，
  让「提交前本机信息扫描」一并生效，不必事后手工补装。

- 仓库分支用 `master`（与既有笔记仓库一致）。
- 若模板列表可用，交互式引导会列出 `Template/` 下所有含 `main.tex` 的目录供选择。

### 导引与小结（可选）

`--intro` / `--summary` 让骨架按 Math-Note 模板的既有约定带上这两样，**默认都不带**：

| 位置 | 内容 |
|---|---|
| `Content/<层1>/intro.tex` | **本章导引**——无编号标题 ＋ `\phantomsection` ＋ `\addcontentsline`，手工进目录 |
| `Content/<层1>/Summary/` | **本章小结**——`\section{本章小结}` ＋ `Summary/intro.tex`（导引）＋ `Summary/01_summary.tex`（条目） |
| `Content/<层1>/<层2>/Summary/` | **本节小结**——同上，标题降为 `\subsection`，条目为 `\subsubsection` |

规则：

- **导引只加在最外层**（章 / 节）；**小结加在所有会产生目录的层** —— 末层是 `.tex` 文件，不加。
- 小结自己占**下一级**的编号标题，内部的导引与条目再降一级（带 `*` 与不带 `*` 区分），
  所以节的小结用到 `\subsubsection`，与正文只到 `\subsection` 并不冲突。
- 每份新文件里留一行 `%` 注释写「这一节该写什么」，不占版面、不进目录。
- 对应的 `\input` 插进该层 `index.tex`：导引在**第一条 `\input` 之前**（开头的注释行留在最上面），
  小结在**附录之前**（没有附录就接在最后一条 `\input` 之后）。
- 交互式引导会问一句「骨架里一并建导引与小结？」（`y` 都建 / `i` 只建导引 / `s` 只建小结）。

**已有的笔记**也能补：走「笔记工具 → 补导引与小结」（`note_tools.py`）。它扫描 `Content/`
现有结构、按内容推断层级命令，先给清单、确认后写入；**已存在的文件与 `\input` 行都不动**，
可以反复跑。

## outline_tool.py — 大纲的创建 / 导出 / 校验

`new_note.py` 按大纲 md 建骨架，本工具负责**把大纲弄出来**。三个入口：

```bash
python outline_tool/outline_tool.py                       # 面板
python outline_tool/outline_tool.py --check <大纲.md>      # 只校验（不弹提问，并预览会生成哪些文件）
python outline_tool/outline_tool.py --check <大纲.md> --write-levels   # 顺手把推断的 levels 写进 md
python outline_tool/outline_tool.py --export <笔记目录> [输出.md]
python outline_tool/outline_tool.py --from-text <清单.txt> [输出.md]   # 层级按层数自动推断
```

**1. 新建大纲**：粘一份「缩进清单」（`目录名 | 中译名`，缩进表示层级，`END` 结束）
→ 写成规范的大纲 md，层级模式按清单层数自动推断并写进头部。适合先在草稿里把结构
列出来，再转成规范文件；事后想换层级，直接改 md 里那行 `levels:` 即可。

**2. 从现有笔记导出大纲**：读 `main.tex` 的正文主体与各级 `index.tex` 链，
把现有笔记的结构 + 中译名反推成大纲 md —— 既能给旧笔记留一份大纲，也能当新笔记的蓝本。
导出规则：

- 层级模式按**结构**推断：最外层命令取自 `main.tex`，其余按 `part → chapter → section
  → subsection` 的固定次序顺延到实际层数（不按「各层读到什么命令」投票，那会被
  笔记里的不规则写法带偏）。
- 中译名的两种写法都认：写在**自己的 `index.tex` 顶部**，或写在**该支第一个叶子文件**里。
  查不到就只写目录名，并在输出里列出「哪些位置没读到、文件里其实写的是什么命令」。
  顺带的诊断会指出笔记里的不一致，例如把层2 写成了 `\section`（本层应为 `\chapter`）、
  叶子只有 `\section{}` 空标题、某些分支只有两层。
- **被 `%` 注释掉的章照样收** —— 导出的是「计划」，用 `%` 关掉的多半是还没写的章。
  输出里会提示有几处是这样。
- 原本没有编号的目录名（如 `Appendix_…`）导出后会被补号 —— 这是 `new_note.py`
  的编号规则，不是导出丢信息。
- 写完会**回读校验**：重新解析这份 md，确认能还原出同一棵树。

**3. 校验大纲**：读一份 md，报格式错误（跳级、命令乱序、目录名非法……），
通过则打印它会生成的完整文件清单 —— 相当于 `new_note.py --dry-run` 的只读版。
md 没写 `levels:` 或写的与结构不符时，按结构推断并给出「改 md 里的哪一行」；
面板里还会问你要不要代写（命令行加 `--write-levels` 即代写）。

## note_tools.py — 单本笔记的入口

笔记目录里的 `commit.py` / `setup_mode.py` 必须**在笔记目录内**运行（前者依赖同目录的 `.git`，
后者读写同目录的 `Content/`）。本工具让你不必先 `cd` 过去。

列表会显示每本笔记的未提交改动数，选中后可选「提交并推送」「切换习题编排模式」
或「补导引与小结」。最后一项按 `new_note.py` 的同一套规则，给选中的那本补
`intro.tex`（本章导引）与各级 `Summary/`（小结），并把 `\input` 插进对应的 `index.tex`：
先扫现有结构、给出「将新建几个文件、改动几个 index.tex」的清单，确认后才写入；
已存在的文件与 `\input` 行都不动，可以反复跑。

## clean_aux.py — 清理编译产物

编译一次就会留下 `.aux/.log/.xdv/.fls/...` 一堆中间文件，它们被 `.gitignore` 忽略、
但会一直堆积。本工具按仓库分组列出占用，确认后再删。

**不带参数运行就是交互面板**：列出各仓库占用后，直接填序号选要清的 ——
`a` 全部、`1,3` 或 `2-4` 选几个、`p` 连 PDF 一起看、`notes`/`template`/`tools`/`all` 换区域，
回车则不删退出。删除前还会再确认一次。

```bash
python clean_aux/clean_aux.py                 # 交互面板
python clean_aux/clean_aux.py --write         # 删除全部（先确认）
python clean_aux/clean_aux.py --write --yes   # 删除全部且不确认（脚本用）
python clean_aux/clean_aux.py --with-pdf      # 连 PDF 一起
python clean_aux/clean_aux.py --area notes    # 只处理某区域：notes / template / tools / all
```

**默认不动 PDF**（那通常是你真正想留的东西），且只按扩展名匹配编译产物，不会碰到源码。

## repo_check.py — 仓库体检

把「仓库规范」变成可自动核查项，避免搬家 / 改名 / 复制模板后靠肉眼盯：

```bash
python repo_check/repo_check.py              # 巡检全部区域
python repo_check/repo_check.py --area notes # notes / template / tools / all
```

逐仓库检查：`.gitignore` / `.gitattributes` 是否存在；有没有**被跟踪**的编译产物；
有没有被跟踪的 `__pycache__`、`*.conf`、`.cwl_source`、`.sensitive-words.txt`、
运行档案；以及未提交改动数与远程配置。**只读，不改动任何文件。**

## video2text.py — 视频转文字

把没有字幕的讲座视频（B站 / YouTube）转成**带时间戳的纯文本**，供大模型整理成笔记。
全程本地、免费。**不带参数运行即交互面板**。

默认仅提取字幕；显式 `--mode auto` 才在无字幕时转本地 whisper，`--mode whisper` 强制转写。字幕下载/解析失败不会静默切换成长时间识别。支持有限重试、独立进度心跳、分块恢复、验证后复用音频与下载续传；正文与状态原子保存。面板第6项可管理合集、导出按集序 ZIP 及失败清单、只读诊断锁；`--only-failed` 仅补失败/未完成项。具体参数与恢复限制见工具说明。
两者耗时差三个数量级，所以「先探测」是默认行为。

```bash
python video2text/video2text.py                          # 交互面板
python video2text/video2text.py <URL>                    # 自动识别合集并增量处理
python video2text/video2text.py <URL> --single           # 只处理当前视频
python video2text/video2text.py <URL> --force            # 强制重做本次所选集
python video2text/video2text.py <URL> --force-whisper    # 忽略字幕，强制转写
python video2text/video2text.py --list                   # 列出已转写
python video2text/video2text.py --status                 # 环境与模型状态
python video2text/video2text.py --login                  # 扫码登录 B站
```

面板选项：转写视频 / 批量转写 / 已转写（预览；删除入口已停用，避免破坏索引）/ 重新登录 / 环境与模型状态 / 合集管理。

无 p 的 B站 BV 链接自动展开分P及公开不同 BV 合集；显式 `?p=N` 默认单集。B站空间合集和其它 yt-dlp 支持的 playlist 通过 flat 元信息展开，无固定集数限制。面板单条、批量与 CLI 共用入口。

重复运行只补新增、失败、未完成、产物缺失/空文件或 SHA-256 不匹配的集。稳定身份而非标题/序号驱动去重，同名、改名、重排不碰撞；逐集原子状态保留中断前成功项，移除成员不会自动删除。`--force`（同 `--refresh`）强制重做所选集，`--force-whisper` 仅改变转写路线；`--all-parts` 可主动展开显式 p 链接，不能与 `--single` 同用。旧标题目录及外部批处理结果不自动导入或搬迁，新入口写独立目录。

阅读用产物写在 `video2text/_data/transcripts/<合集标题>/`，每集一份以视频标题命名的 TXT，直接平铺，不再按 BV 建子目录；单集则在 `<视频标题>/` 放对应 TXT。原 `episodes/<稳定集ID>/transcript.txt` 仍保留作为权威增量索引与音频检查点，更新不会移动或删掉它；旧已完成成果可用 `--sync-titles <合集ID>` 离线补建标题目录。格式为

```
[00:00:02] 上次讲了什么度量空间或者维度量空间
```

**本工具集只有 `video2text/` 与 `pdf_upright/` 需要第三方依赖**；这里是前者（`yt-dlp`、
`faster-whisper`、`av<19`、`playwright`）。脚本启动时若发现当前解释器缺依赖，会自动改用
配置里指定的解释器重跑，所以从总面板进来不必操心解释器问题。数据目录（模型 / 登录态 /
转写产物）与本机 `.conf` 均不入版本库。

> 注意 `av` 必须 `<19`：PyAV 19 移除了 faster-whisper 仍在使用的参数，转写会直接报错。
> 用 `--status` 可检查是否合规。


增量边界：已成功且本地产物哈希一致的同 cid 不会再次探测远端字幕是否改版；要重新取字幕请用 `--force`。匿名公开元信息接口可能受风控或网络限制；发现失败时保留已有状态与产物，不把未完整发现的合集记为成功。

详见 `video2text.md`。

## pdf_upright.py — PDF 转正（横躺课件修复）

**症状**：从雨课堂下载的课件 PDF，每页都横躺着，得歪着头看；白边大，右侧还带一列
「雨课堂 / 第几页」水印。

**成因**：这类导出走的是「打印成 PDF」链路（`Producer: Microsoft: Print To PDF`）。
横版幻灯片先被栅格化（如 720×1280 的竖向位图），再被打印驱动旋转 90° 塞进纵向 A4 纸张 ——
旋转只落在像素里，页面属性 `/Rotate` 仍是 `0`，所以任何阅读器都不会自动纠正。

**修法（不重新编码，画质等同原件）**：把 90° 旋转直接**烘进页面几何** —— 每页内容流前置一个
转置矩阵，页面框换成幻灯片本身的大小（`/MediaBox` = `/CropBox` = 16:9 横向页），`/Rotate` 归 0。
方向只由几何决定，不再依赖阅读器对 `/Rotate` 与 `/CropBox` 的解释。

> 早先的做法是「`/CropBox` 收敛 + `/Rotate` 置 90」，在多数阅读器里看着对，但
> **SumatraPDF 会把用户手动转过的角度按文件记下来**（`%LOCALAPPDATA%\SumatraPDF\SumatraPDF-settings.txt`
> 的 `FileStates` 里的 `Rotation`），打开时叠在页面方向之上 —— 文件修好了它还是歪。
> 烘进几何之后不再有这种叠加空间。

```bash
python pdf_upright/pdf_upright.py                        # 交互面板
python pdf_upright/pdf_upright.py <文件或目录> ...        # 预检 + 就地修复（会确认）
python pdf_upright/pdf_upright.py <目录> --dry            # 只报告，不写文件
python pdf_upright/pdf_upright.py <目录> -o <输出目录>    # 不动原件，另存到别处
python pdf_upright/pdf_upright.py <目录> -r               # 连子目录一起找
python pdf_upright/pdf_upright.py <目录> --ccw            # 内容躺反了，按逆时针 90° 转
python pdf_upright/pdf_upright.py <目录> --yes            # 不确认
```

面板四步：

1. **问目录** —— 粘贴或拖入路径即可；直接回车用当前目录，直接给一份 `.pdf` 则只处理这一份；
   目录不存在会当场提示重输，`q` 退出。
2. **编号列表** —— 列出该目录下所有 PDF，一行一份：页数、页面尺寸 → 幻灯片尺寸、
   `需转正（29/29 页）` 或 `跳过`。**编号就是下面选的序号**。
3. **按编号选** —— `a` 全部、`1`、`1,3`、`2-4`（与 `clean_aux` 的选择语法一致）；
   `r` 切换是否含子目录、`o` 换输出位置、`d` 换转向、回车换目录、`q` 退出。
4. **执行并回报** —— 逐份打印转正页数与体积变化，随后回到同一目录的列表，可连续再来。

选到标了「跳过」的项不会报错，只提示「第 N 份不需要转正，跳过」。

**安全性**：

- **默认就地覆盖原文件**，不生成 `横向版/` 之类副本；覆盖前把原件备份到系统临时目录
  `<TEMP>/pdf_upright_backup-<时间戳>/`，路径打在输出里，随时可取回；
- 用 `-o`（或面板 `o`）则原件完全不动，结果写到指定目录；
- **逐页判定，已转正的页面会跳过**（横向页 / 有文字层 / 贴图不足页面 40%），重复跑不会二次旋转；
  预检里的 `需转正（N/M 页）` 就是逐页数出来的；
- 动手条件四条同时满足：纵向页 + 无文字层 + 最大图像竖立 + 占页面面积 40% 以上；
- 递归扫描时自动排除历史遗留的 `横向版/`，不会把旧副本当输入。

**已知局限**：判定只看形状，**分不出内容往哪边躺**。默认顺时针 90°（打印驱动产出的是这种）；
若转出来是倒立，说明躺反了，加 `--ccw`（面板按 `d`）改逆时针。原件有备份，可放心重试。

**依赖**：需要 PyMuPDF（`pip install pymupdf`）。启动时若当前解释器没有，会按
`PDF_UPRIGHT_PYTHON` 环境变量 → PATH 上的 `python` → `~/.workbuddy/binaries/python/` 下各环境
依次探测，找到装了它的就换过去重跑，所以从总面板进来不必操心解释器。

**边界**：只修「整页贴图、贴反了」这一类；含真正文字层或矢量排版的 PDF 一律跳过。
它治标 —— 想从源头不歪，导出时把纸张设为 A4 横向、边距「无」、勾上「背景图形」。

## show_memory.py — 查看工作记录

> 已从总面板移除（2026-09-24）。脚本仍在，需要时直接 `python show_memory/show_memory.py`。

`.workbuddy/memory/` 里按日期归档着工作日志与一份长期记忆。这些记录平时不看，
但「上次改到哪儿了」「为什么当初这么定」往往只能从这里找。

```bash
python show_memory/show_memory.py            # 列出所有记录
python show_memory/show_memory.py --last 3   # 看最近 3 天
python show_memory/show_memory.py 2026-09-24 # 看某一天
python show_memory/show_memory.py MEMORY     # 看长期记忆
```

## 目录结构

**一个面板选项 = 一个同名目录**（脚本、说明、配置都放在自己目录里，互不混）：

```
Tools/
├── launcher.py            总面板：表驱动，一个选项对应一个同名目录
├── README.md / CHANGELOG.md
├── git_setup/             Git 基本信息（环境检测 / 账户 / SSH）        → 选项 1
├── manager/               笔记工作区管理                                → 选项 2
│   └── manager.py / manager.md / manager.conf(.example)
├── symbols/               符号库管理                                    → 选项 3
│   └── symbols.py / symbols.md / symbols.conf(.example)
├── progress/              写作工作台                                    → 选项 4
│   └── workbench_launcher.py / workbench_server.py / workbench_store.py
│       workbench_editor.html / workbench_features.py / workbench_pdf.py
│       workbench_daily.py / workbench_tex.py / progress.md / progress_design.md
├── new_note/              从模板新建笔记                                → 选项 5
│   └── new_note.py / new_note.md / outline_example.md
├── outline_tool/          大纲的创建 / 导出 / 校验                      → 选项 6
├── note_tools/            单本笔记的入口（提交 / 习题模式）             → 选项 7
├── clean_aux/             清理编译产物                                  → 选项 8
├── repo_check/            仓库体检                                      → 选项 9
├── check_sensitive/       提交前本机信息扫描                            → 选项 10
│   └── check_sensitive.py / pre-commit   ← 钩子模板也在这里
├── sync_paths/            配置路径检查与修复                            → 选项 11
├── commit/                一键提交                                      → 选项 12
│   └── commit.py / commit.md
├── video2text/            视频转文字（默认仅字幕 / 可选本地恢复转写）   → 选项 13
│   └── video2text.py / video2text.md / video2text.conf(.example) / _data/
├── spec_sync/             项目规范副本一致性（检查 / 同步）             → 选项 14
├── pdf_upright/           PDF 转正（横躺课件就地转正 16:9）             → 选项 15
├── show_memory/           （已从面板移除；需要时单独运行）
│   └── show_memory.py
├── tex2docx/              LaTeX 转 Word 预处理（非面板项，单独运行）
│   └── preprocess.py / preprocess.md
└── _tools/                随附的第三方脚本（git-filter-repo），非面板项
```


直接运行 `python launcher.py` 即可进入总面板；也可以进入子目录单独运行某个脚本
（脚本的配置与运行档案都放在**它自己所在的目录**，所以单独运行同样正常）。


## 生成的档案

| 文件 | 说明 |
|---|---|
| `manager.conf` / `symbols.conf` | 工具配置，含绝对路径 |
| `progress/workbench_local.json` | 工作台启动配置（root / 端口 / 打开与保存许可） |
| `video2text/video2text.conf` | 视频转文字工具配置（另见其 `_data/` 目录） |
| `symbols_extract.json` | 符号提取记录，`{文件夹: {日期: {命令名: 定义行}}}` |
| `notes_tree.json` | 笔记目录结构快照 |

## 环境要求

- Python 3.8+，**除 `video2text/` 与 `pdf_upright/` 外仅用标准库，无第三方依赖**
- 用 `python xxx.py` 直接运行；终端与文件路径需支持 UTF-8
- `video2text/` 需第三方依赖（`yt-dlp`、`faster-whisper`、`av<19`、`playwright`），
  装在专用解释器里即可；脚本会自动探测并切换，见 `video2text.md`
- `pdf_upright/` 需 `pymupdf`；同样自动探测已装它的解释器，或用 `PDF_UPRIGHT_PYTHON` 指定
- 推送走 SSH；`manager.py` 选项 3 可自动写入 `~/.ssh/config`，其中 `github.com` 指向 `ssh.github.com:443` 以绕开 22 端口受限的网络
- `manager.py` 选项 7 在 `gh` 可用时一步创建远程仓库，否则退化为打印手动命令
- 工作台的 TeXStudio 探测针对 Windows（查注册表 `.tex` 关联与常见安装位置）
- 笔记项目须用 XeLaTeX 编译（`structure.sty` 的要求）
