# check_sensitive.py

提交前的本机信息把关：扫出会被推到公开仓库的本机路径与专有词。命中即返回非 0，可直接用作 git 钩子。

## 用法

```bash
python check_sensitive.py                # 扫暂存区的新增行（默认）
python check_sensitive.py --tracked      # 全量体检：扫所有已跟踪文件
python check_sensitive.py --dir <路径>   # 扫指定目录，非 git 目录也可用
```

总面板选项 10 以 `--tracked` 运行本脚本。

退出码：`0` 干净；`1` 命中。

## 扫什么

两类判据叠加：

- **内置形态**（与具体机器无关的通用写法）
  - Windows 用户目录路径：`<盘符>:\Users\<用户名>…`
  - Unix 用户目录路径：`/Users/<名字>`、`/home/<名字>`
- **专有词表**：从脚本所在目录起向上最多 4 级，逐级合并沿途的 `.sensitive-words.txt`；
  空行与 `#` 开头的行忽略。词表本身不入版本控制，脚本自身因此不会变成新的泄露源。

词表始终相对**脚本所在目录**解析，与当前工作目录、与 `--dir` 的目标目录无关。

## 三种扫描范围

| 模式 | 范围 | 说明 |
|---|---|---|
| 默认 | 暂存区的**新增行** | 只读 `git diff --cached` 里 `+` 开头的行；删除的内容不造成泄露，所以「清理本机信息」这类提交不会被误拦 |
| `--tracked` | 全部已跟踪文件 | 以仓库根为工作目录跑 `git ls-files`，逐文件逐行扫 |
| `--dir <路径>` | 该目录递归 | 跳过 `.git`、`__pycache__`、`.workbuddy`、`node_modules` |

二进制后缀（图片、PDF、压缩包、字体、视频、`.pyc` 等）一律跳过。不在 git 仓库内又没给 `--dir` 时，只打印提示并返回 `0`。

## 命中后的输出

列出前 60 处，每处给出「位置 · 判定理由 · 原文片段」，末尾给处理建议（改写成环境变量、把 `*.conf` 移入 `.gitignore`、或单次提交用 `--no-verify` 跳过）。超过 60 处只报总数。

## pre-commit 钩子

同目录的 `pre-commit` 是可直接安装的钩子模板，本身不含本机绝对路径，工具目录改名或挪窝都不必重装。

安装（每个仓库一次）：

```bash
cp Tools/check_sensitive/pre-commit <仓库>/.git/hooks/pre-commit
chmod +x <仓库>/.git/hooks/pre-commit
```

钩子按下列顺序找脚本，命中即用：

1. `<仓库根>/check_sensitive.py`
2. `<仓库根>/*/check_sensitive.py`
3. `<仓库根>/../Tools/*/check_sensitive.py`
4. `<仓库根>/../../Tools/*/check_sensitive.py`

找不到脚本、或系统里既没有 `python` 也没有 `py` 时放行（`exit 0`）：检查本身绝不阻断提交。脚本返回非 0 时钩子以 `1` 中止提交。

卸载：删除该钩子文件。临时跳过单次检查：`git commit --no-verify`。

## 注意事项

- 只做文本匹配，不做语义判断；行内出现被列为专有词的普通字符串同样命中。
- 默认模式只看新增行：早已写进历史提交的本机信息，只有 `--tracked` 能发现。
- 逐行读取、不解析语法，大文件会慢。
