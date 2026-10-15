# LaTeX 笔记工具集

一套维护本地 LaTeX 笔记的工具，配合「笔记写作」等模板使用。

| 脚本 | 用途 | 详细说明 |
|---|---|---|
| `launcher.py` | **总面板**：列出并调起下面各工具 | 见下 |
| `git_setup/git_setup.py` | Git 基本信息：环境检测 / 配置账户 / 配置 SSH | 见下 |
| `manager/manager.py` | 笔记工作区管理：仓库状态 / 批量提交 / 建仓库 | `manager.md` |
| `symbols/symbols.py` | 符号库管理：提取 / 回填 / 刷新补全 / 分发 | 见下 |
| `progress/workbench_launcher.py` | 总面板选项 4：工作台启动面板，本机root/端口/独立打开权限配置，默认只读、逐书保存独立根/永久ID许可 | 见下 |
| `progress/workbench_server.py` | 工作台HTTP服务：默认只读、禁止调起编辑器；实时轻量导航、按需全文/问题/阶段统计/报告/PDF；受控写入与TeXstudio打开须另行显式授权 | `progress.md` |
| `progress/workbench_readonly.py` | 工作台只读原型：校验资料绑定与审核记录，导出快照；不迁移或修改笔记 | `progress.md` |
| `progress/workbench_store.py` | 受控保存底层：书籍身份、按书计划、审核补丁、版本检查与备份恢复 | `progress.md` |
| `new_note/new_note.py` | 从模板创建一本新笔记（复制骨架 → 清测试内容 → `git init`） | 见下 |
| `outline_tool/outline_tool.py` | 大纲的创建 / 导出 / 校验 | 见下 |
| `note_tools/note_tools.py` | 单本笔记的入口：提交 / 切换习题编排模式 | 见下 |
| `clean_aux/clean_aux.py` | 清理编译产物（aux / log / xdv / fls / synctex …），无参数即交互面板 | 见下 |
| `repo_check/repo_check.py` | 仓库体检：规范文件 / 误跟踪 / 未提交 | 见下 |
| `check_sensitive/check_sensitive.py` | 提交前扫描本机信息（用户名 / 本机路径 / 专有词） | 见下 |
| `commit/commit.py` | 一键提交：`add → commit → push`，含 `--check` 模式供 git 钩子调用 | `commit.md` |
| `video2text/video2text.py` | 视频/合集增量转文字：默认仅字幕，可选本地转写与分块恢复 | `video2text.md` |
| `spec_sync/spec_sync.py` | 项目规范副本一致性：比对原件与副本，不一致时可用原件覆盖 | `spec_sync.md` |

## launcher.py — 总面板

运行 `python Tools/launcher.py`，选项 4 进入工作台的启动配置面板。进入面板不会自动启动服务；选择「5. 启动服务」后由面板在后台线程管理服务并打开浏览器，选择「6. 停止」或返回总面板时，若有运行服务，会先提醒保存网页未保存输入并要求输入 `y` 确认；确认后关闭本面板创建的服务，端口立即释放。输入结束或中断也会清理本面板服务。端口占用时显示错误，不停止、不接管、不复用身份不明的现有服务。

面板可配置单个 `root`、端口（统一默认 `7656`）、独立 `allow-open` 开关和 TeXstudio 可执行文件路径。首次 root 从工具目录相对推导到工作区的 `LaTeX_Notes`；可改为其他书架目录或含 `LaTeX_Notes` 的工作区，含空格路径可直接输入，无需引号。空路径、文件、不存在目录、无 `*_Content.md` 书籍登记入口、登记冲突或绑定路径越界的目录均会拒绝；启动前逐本进行轻量导航校验。TeXstudio 留空时由服务自动查找，`allow-open` 默认关闭，开启不授予写入权限。

配置自动原子保存到 `progress/workbench_local.json`，已加入 `.gitignore`；相对 root 以配置文件所在目录为基准。配置损坏时显示可读错误并保留原文件，不回退后覆盖。改变 root 会清空旧写白名单、写入及打开权限。默认仍只读；选项7提供逐书保存许可，输入已初始化的书名到永久book_id的JSON对象并以SAVE确认许可根；原单GT输入方式保留。仅write_books不授予保存权限；需allow_write、逐书独立ID、绝对write_root完整匹配。外部同名书、复制ID的别名或不同根均不继承许可；启动及每次写请求重新核验根与身份，root变化清空许可根和全部ID。面板不初始化书、不迁移旧标记、不自动修改审核结论。旧标记迁移已彻底退役：旧版一套文件（脚本、页面、配置、标记数据及 legacy 拒绝入口）已于 2026-10-15 全部删除，不再有任何认领任务，也不纳入工作台运行数据。书内 legacy 归档与本机退役声明仅作历史证据，详见 progress/progress.md。界面区分持久配置与当前服务的实际 root、端口、打开和写入权限；配置在下次显式启动时生效，运行期间禁止修改。

启动与读取链路不导入任何旧版脚本，也不读取旧配置或标记数据（旧版文件已删除）；书内 legacy 归档与退休声明不作为运行数据源，不参与日常启动。

保存许可核验：本机既有八书许可根与各永久ID匹配；正式启动面板独立端口GET确认八书可写导航及已初始化运行时基线，页面保存判定另有Node VM验证，未对真实书试写。本机许可不入公开库，新配置仍默认只读，allow-open不随保存自动开启。发布范围仅为提交并推送现有main，不创建tag、Release或PR；其它工具未提交改动原样保留。

PDF最终有界验收（2026-10-14）：独立HTTP/Blob标签页及新增「独立标签页打开PDF」备用按钮实际点击均PASS，真实页码和画布已核验；当前嵌入Blob/直接HTTP iframe仍灰屏、UNVERIFIED，整体保持 **PARTIAL/UNVERIFIED，不宣称全部PDF修复**。备用按钮仅在完整已验证Blob加载后启用，需用户点击，以noopener打开目标页码，不自动打开或下载，不改PDF/后端。冻结测试exit 0仅代表完成及保护检查通过，须看各路线渲染结果；详见 `progress/progress.md`。

可独立运行 `python Tools/progress/workbench_launcher.py --no-browser`，进入同一面板但显式启动时不自动打开浏览器；`--config <本机JSON路径>` 可指定隔离配置。独立服务 CLI 的默认端口同样为 `7656`，更多服务参数见 `progress/progress.md`。

总面板选项 1–14 编号不变，提交项仍为 12；选项 4 是工作台的前台配置入口。后台模式仍支持 `后台:<附加参数>`，脚本以参数列表调用，不经过 shell。

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
  5. 检验并删除未使用的符号
  6. 引入新的记号（选归属子段，自动刷新补全）
  7. 退出
```

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

## 目录结构

**一个面板选项 = 一个同名目录**（脚本、说明、配置都放在自己目录里，互不混）：

```
Tools/
├── launcher.py            总面板：列出并调起下面各工具
├── git_setup/             Git 基本信息（环境检测 / 账户 / SSH）
│   └── git_setup.py
├── manager/               笔记工作区管理
│   └── manager.py / manager.md / manager.conf(.example)
├── symbols/               符号库管理
│   └── symbols.py / symbols.md / symbols.conf(.example)
├── progress/              写作工作台（选项 4）
│   ├── workbench_launcher.py / workbench_server.py / workbench_editor.html
│   └── workbench_store.py / workbench_features.py / workbench_pdf.py / workbench_daily.py / workbench_tex.py / progress.md / progress_design.md
├── new_note/              从模板新建笔记
│   └── new_note.py / outline_example.md
├── outline_tool/          大纲的创建 / 导出 / 校验
│   └── outline_tool.py
├── note_tools/            单本笔记的入口（提交 / 习题模式）
│   └── note_tools.py
├── clean_aux/             清理编译产物
│   └── clean_aux.py
├── repo_check/            仓库体检
│   └── repo_check.py
├── check_sensitive/       提交前本机信息扫描
│   └── check_sensitive.py / pre-commit   ← 钩子模板也在这里
├── sync_paths/            配置路径检查与修复
│   └── sync_paths.py
├── commit/                一键提交
│   └── commit.py / commit.md
├── video2text/            视频转文字（默认仅字幕 / 可选本地恢复转写）
│   └── video2text.py / video2text.md / video2text.conf(.example) / _data/
├── spec_sync/             项目规范副本一致性（检查 / 同步）
│   └── spec_sync.py / spec_sync.md
└── show_memory/           （已从面板移除；需要时单独运行）
    └── show_memory.py
```


直接运行 `python launcher.py` 即可进入总面板；也可以进入子目录单独运行某个脚本
（脚本的配置与运行档案都放在**它自己所在的目录**，所以单独运行同样正常）。

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

列表会显示每本笔记的未提交改动数，选中后可选「提交并推送」或「切换习题编排模式」。

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

**这是本工具集中唯一需要第三方依赖的工具**（`yt-dlp`、`faster-whisper`、`av<19`、
`playwright`）。脚本启动时若发现当前解释器缺依赖，会自动改用配置里指定的解释器重跑，
所以从总面板进来不必操心解释器问题。数据目录（模型 / 登录态 / 转写产物）与
本机 `.conf` 均不入版本库。

> 注意 `av` 必须 `<19`：PyAV 19 移除了 faster-whisper 仍在使用的参数，转写会直接报错。
> 用 `--status` 可检查是否合规。


增量边界：已成功且本地产物哈希一致的同 cid 不会再次探测远端字幕是否改版；要重新取字幕请用 `--force`。匿名公开元信息接口可能受风控或网络限制；发现失败时保留已有状态与产物，不把未完整发现的合集记为成功。

详见 `video2text.md`。

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

## 生成的档案

| 文件 | 说明 |
|---|---|
| `manager.conf` / `symbols.conf` | 工具配置，含绝对路径 |
| `progress/workbench_local.json` | 工作台启动配置（root / 端口 / 打开与保存许可） |
| `video2text/video2text.conf` | 视频转文字工具配置（另见其 `_data/` 目录） |
| `symbols_extract.json` | 符号提取记录，`{文件夹: {日期: {命令名: 定义行}}}` |
| `notes_tree.json` | 笔记目录结构快照 |

## 环境要求

- Python 3.8+，**除 `video2text/` 外仅用标准库，无第三方依赖**
- 用 `python xxx.py` 直接运行；终端与文件路径需支持 UTF-8
- `video2text/` 需第三方依赖（`yt-dlp`、`faster-whisper`、`av<19`、`playwright`），
  装在专用解释器里即可；脚本会自动探测并切换，见 `video2text.md`
- 推送走 SSH（`~/.ssh/config` 中 `github.com` 指向 `ssh.github.com:443`），可用 `manager.py` 选项 3 自动配置
- `manager.py` 选项 7 在 `gh` 可用时一步创建远程仓库，否则退化为打印手动命令
- 工作台的 TeXStudio 探测针对 Windows（查注册表 `.tex` 关联与常见安装位置）
- 笔记项目须用 XeLaTeX 编译（`structure.sty` 的要求）
