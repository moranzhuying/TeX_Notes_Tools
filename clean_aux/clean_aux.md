# clean_aux.py

清理 LaTeX 编译产物：按目录分组列出占用，确认后删除。只按扩展名匹配，不碰源码，默认不动 PDF。

## 用法

```bash
python clean_aux.py                  # 交互面板
python clean_aux.py --write          # 删除全部（先确认）
python clean_aux.py --write --yes    # 删除且不再确认
python clean_aux.py --with-pdf       # 连同 PDF 一起清
python clean_aux.py --area notes     # 只处理某区域：notes / template / tools / all
```

**不带任何参数才是交互面板**；只要给了参数就按命令行模式跑。`--area` 缺省为 `all`（整个工作区）。总面板选项 8 以无参数方式运行，即直接进交互面板。

## 会被删的扩展名

`.aux` `.log` `.out` `.toc` `.lof` `.lot` `.fls` `.fdb_latexmk` `.synctex` `.synctex.gz` `.bbl` `.blg` `.dvi` `.xdv` `.listing` `.nav` `.snm` `.vrb` `.idx` `.ind` `.ilg` `.run.xml`

加 `--with-pdf` 才把 `.pdf` 一并算进来。扫描时跳过 `.git`、`__pycache__`、`node_modules`、`.workbuddy`。

## 交互面板

面板先列出各目录的「文件数 · 占用 · 涉及的扩展名」，每组一个序号，末尾给合计。然后：

| 输入 | 含义 |
|---|---|
| `a` | 删除全部 |
| `1`、`1,3`、`2-4` | 只删这些序号 |
| `p` | 切换是否连 PDF 一起处理（切换后重新列表） |
| `notes` / `template` / `tools` / `all` | 换区域 |
| 回车 | 什么都不删，退出 |

选定后再问一次「确认删除 N 个文件（大小）？」，答 `y` 才执行；删完按回车重新扫描。

## 命令行模式

按区域扫描并列出同样的分组，然后：

- 不带 `--write`：只列出，末尾提示加 `--write`；
- 带 `--write`：删除**扫描到的全部**文件（不是选中项）；没有 `--yes` 时先问一次。

## 退出码

`0` 正常；`1` 区域名无效，或区域目录不存在。

## 注意事项

- 删除是直接 `unlink`，不进回收站，不可撤销；释放的空间按删除前的大小统计。
- 区域名只认 `notes`、`template`、`tools`、`all`，分别对应工作区下的 `LaTeX_Notes`、`Template`、`Tools` 与整个工作区。
- 删掉的都是可再生产物，但下次编译要重跑两趟才能恢复目录与交叉引用。
- 只按扩展名判断，同名却并非编译产物的文件（例如手工维护的 `.idx`）也会被删。
