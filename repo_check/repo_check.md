# repo_check.py

仓库体检：只读检查各仓库是否缺规范文件、是否误跟踪了编译产物与本机文件，并汇总未提交改动与远程配置。

## 用法

```bash
python repo_check.py                 # 巡检全部区域
python repo_check.py --area notes    # 只查笔记区：notes / template / tools / all
```

总面板选项 9。

## 检查项

| 检查 | 判据 | 归类 |
|---|---|---|
| `.gitignore` / `.gitattributes` | 文件是否存在 | 问题 |
| 编译产物被跟踪 | `git ls-files` 中出现 `.aux` `.log` `.out` `.toc` `.lof` `.lot` `.fls` `.fdb_latexmk` `.synctex.gz` `.xdv` `.listing` `.nav` `.snm` `.vrb` `.bbl` `.blg` `.dvi` | 问题 |
| 本机 / 运行文件被跟踪 | `*.conf`、`.cwl_source`、`.sensitive-words.txt`、`*_extract.json`、`notes_tree.json`、`progress_marks.json`、路径含 `__pycache__` | 问题 |
| 未提交改动 | `git status --porcelain` 的条目数 | 提示 |
| 远程 | 有没有配置 `origin` | 提示 |

「问题」使该仓库计入失败；「提示」只列出，不影响结论。

## 仓库从哪来

- **笔记区**：`manager/manager.conf` 的 `root` 下各子目录，须自身是 git 仓库；`root` 未配置或目录不存在时这一区为空。
- **模板区**：工作区 `Template/` 下各子目录。
- **工具区**：工作区 `Tools/` 自身是仓库时算一个，否则按其下的子目录算。

## 输出与退出码

每个仓库一行结论：通过，或「N 项问题」并逐条列出，提示项另起一行；末尾给出「巡检 N 个仓库：全部通过 ／ M 个存在问题」。

退出码：`0` 巡检完成（发现问题是 `0`）；`1` 区域名无效，或一个仓库都没找到。

## 注意事项

- 全程只读，不改任何文件，也不执行任何 git 写操作。
- `*.conf` 一律视为本机配置，入库的模板应是 `*.conf.example`。
- 有问题时退出码仍是 `0`；要拿它做门禁需解析输出，不能只看返回码。
