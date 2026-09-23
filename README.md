# LaTeX 笔记工具集

一套维护本地 LaTeX 笔记的工具，配合「笔记写作」等模板使用。

**本目录既是运行位置，也是发布仓库** —— 每个脚本只有一份，改完直接提交即可，不需要在「本机副本」与「仓库副本」之间手工同步。

| 脚本 | 用途 | 详细说明 |
|---|---|---|
| `launcher.py` | **总面板**：列出并调起下面各工具 | 见下 |
| `guard/git_setup.py` | Git 基本信息：环境检测 / 配置账户 / 配置 SSH | 见下 |
| `manager/manager.py` | 笔记工作区管理：仓库状态 / 批量提交 / 建仓库 | `manager.md` |
| `symbols/symbols.py` | 符号库管理：提取 / 回填 / 刷新补全 / 分发 | 见下 |
| `progress/progress.py` | 写作进度追踪：扫描笔记并在浏览器中查看 | `progress.md`、`progress_design.md` |
| `guard/check_sensitive.py` | 提交前扫描本机信息（用户名 / 本机路径 / 专有词） | 见下 |
| `guard/commit.py` | 一键提交：`add → commit → push`，含 `--check` 模式供 git 钩子调用 | `commit.md` |

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

> 本面板只做**笔记区的仓库管理**。环境检测 / 账户 / SSH 属于「换机器时配置一次」的事，
> 已剥离为 `guard/git_setup.py`（总面板选项 1）；符号库、写作进度等子工具入口也统一由
> `launcher.py` 提供，本面板不再重复。

配置写在脚本同目录的 `manager.conf`（含本机路径，已列入 `.gitignore`）：

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

### 配置

把 `symbols.conf.example` 复制为 `symbols.conf`（与本脚本同目录），按本机情况填写：

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

## progress.py — 写作进度追踪

扫描本地 LaTeX 笔记的写作进度，在浏览器中查看。

面向「每个笔记目录一个 Git 仓库」的工作区：从各笔记的 `main.tex` 出发递归解析 `\input` 树，统计每个小节写了多少、哪些还没动、哪些定理环境是空的，并把结果呈现为一个可交互的本地页面。

### 它解决什么问题

翻目录看不出写作进度，而简单的「字数统计」会误导：

- **结构完成不等于内容完成**。骨架搭好后大量文件是空的，两者必须分开展示。
- **未纳入编译的章不一定没写完**。为加快编译速度，作者常把已完成但暂时不需要编译的章在 `main.tex` 里注释掉。若把这类章当作「未开始」，进度会被严重低估；反之，从未动工的空壳章若计入分母，进度又会虚高。

本工具按「是否纳入编译」与「有无已写内容」两个维度分别处理，并允许手动覆盖自动判定（自动统计出错时可在界面上直接干预）。

### 运行方式

```
python progress.py                 启动服务并自动打开浏览器
python progress.py --rescan        仅扫描并打印统计，不启动服务
python progress.py --report out.md 导出 Markdown 报告
python progress.py --port 8766     指定端口
python progress.py --no-browser    启动但不打开浏览器
```

服务只监听 `127.0.0.1`，端口默认 `8765`，被占用时自动顺延。

若你另有一个总入口面板，可在其中增加一项调用本脚本；建议采用「调起后立即返回」的方式，让服务在后台运行。

### 界面

**总览页**：顶部是续写入口（已标记「设为下一步」的节、最近改动的文件、停滞提醒），其下是全库合计卡片与各笔记卡片。点卡片进入该笔记的明细页。

**明细页**：左侧是可按需展开的层级树，右侧是详情面板。树支持按状态筛选（已写 / 未写 / 未建 / 待补）与关键字搜索。底部有可展开的「未启用章节」分组。

每个小节有三个可点击的标记（**环境 / 正文 / 证明**），默认视为已完成，发现没弄利索时点一下标为待补；另有备注（自由文本）与待办（可勾选条目）两块独立区域。

点击「用 TeXStudio 打开」可直接在编辑器中打开该小节的 tex 文件。

配色只有一套语义：**蓝色 = 已写，中灰 = 已建空壳，深灰 = 规划未建**，橙色是全屏唯一的暖色，只用于待补标记。

### 配置

把 `progress.conf.example` 复制为 `progress.conf`（与脚本同目录），按本机情况修改：

```ini
[paths]
root =            # 笔记工作区根目录，留空则用脚本所在目录
texstudio =       # TeXStudio 可执行文件路径，留空则自动探测

[server]
host = 127.0.0.1
port = 8765
auto_open = true

[scan]
ignore =
min_chars = 50
stagnant_days = 14
recent_count = 6
```

## check_sensitive.py — 提交前本机信息扫描

防止把本机路径、用户名或项目专有词推进公开仓库。三种模式：

```bash
python check_sensitive.py                # 扫暂存区新增行（供 git 钩子调用）
python check_sensitive.py --tracked      # 全量体检：扫所有已跟踪文件
python check_sensitive.py --dir <路径>   # 扫指定目录（非 git 目录也能用）
```

- 内置模式只匹配通用形态（Windows 与 Unix 的家目录路径），本机专有词放在工作区根的 `.sensitive-words.txt` 中，脚本会**逐级向上**收集合并，因此各仓库不必各放一份。
- **只扫新增行**：被删除的内容不构成泄露，所以「清理本机信息」这类提交不会被自己误拦。
- 命中时打印「文件 + 类别 + 内容片段」并以退出码 1 结束，可直接用作 `pre-commit` 钩子。

装钩子（每个仓库执行一次）：

```bash
cp hooks/pre-commit "<仓库>/.git/hooks/pre-commit" && chmod +x "<仓库>/.git/hooks/pre-commit"
```

钩子是本地文件（`.git/hooks/` 不进版本控制），换机器或重新 clone 后需重装。临时跳过单次检查用 `git commit --no-verify`。

## 目录结构

每个工具一个子目录，根目录只放总面板：

```
Tools/
├── launcher.py            总面板：列出并调起下面各工具
├── manager/               笔记工作区管理
│   ├── manager.py / manager.md / manager.conf
├── symbols/               符号库管理
│   ├── symbols.py / symbols.md / symbols.conf(.example)
├── progress/              写作进度追踪
│   ├── progress.py / progress.md / progress_design.md / progress_ui.html / progress.conf(.example)
└── guard/                 防护与提交
    ├── git_setup.py       Git 基本信息（环境检测 / 账户 / SSH）
    ├── check_sensitive.py 提交前本机信息扫描
    ├── commit.py / commit.md
    ├── sync_paths.py      配置路径检查（目录改名后修复 .conf）
    └── hooks/pre-commit   供各仓库安装的 git 钩子
```

直接运行 `python launcher.py` 即可进入总面板；也可以进入子目录单独运行某个脚本
（脚本的配置与运行档案都放在**它自己所在的目录**，所以单独运行同样正常）。

## 生成的档案（仅在本机，勿入库）

| 文件 | 说明 |
|---|---|
| `manager.conf` / `symbols.conf` / `progress.conf` | 本机配置，含绝对路径 |
| `symbols_extract.json` | 符号提取记录，`{文件夹: {日期: {命令名: 定义行}}}` |
| `notes_tree.json` | 笔记目录结构快照 |
| `progress_marks.json` | 进度标记数据（三维标记、备注、待办、计划、章统计覆盖），原子写入并在每次写入前留一份 `.bak` |

想重置全部进度标记，删掉 `progress_marks.json` 即可。以上文件均已在 `.gitignore` 中。

## 环境要求

- Python 3.8+，**仅用标准库**，无第三方依赖
- 用 `python xxx.py` 直接运行；终端与文件路径需支持 UTF-8
- 推送走 SSH（`~/.ssh/config` 中 `github.com` 指向 `ssh.github.com:443`），可用 `manager.py` 选项 3 自动配置
- `manager.py` 选项 7 在 `gh` 可用时一步创建远程仓库，否则退化为打印手动命令
- `progress.py` 的 TeXStudio 探测针对 Windows（查注册表 `.tex` 关联与常见安装位置）
- 笔记项目须用 XeLaTeX 编译（`structure.sty` 的要求）
