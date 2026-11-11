# outline_tool.py

大纲 Markdown 的创建、导出与校验。`new_note.py` 按大纲建笔记骨架，本工具负责把大纲本身弄出来。

## 用法

```bash
python outline_tool.py                                 # 面板
python outline_tool.py --check <大纲.md>                # 只校验，不弹提问
python outline_tool.py --check <大纲.md> --write-levels # 顺手把推断的 levels 写进 md
python outline_tool.py --export <笔记目录> [输出.md]     # 从现有笔记反推大纲
python outline_tool.py --from-text <清单.txt> [输出.md]  # 缩进清单 → 大纲 md
python outline_tool.py --from-text <清单.txt> --levels textbook
```

总面板选项 6。

## 面板

| 选项 | 作用 |
|---|---|
| 1 | 新建大纲：逐行输入 `目录名 \| 中译名`（中译可省），用缩进表示层级，单独一行 `END` 结束；按层数推断 `levels:` 后写成 md |
| 2 | 从现有笔记导出大纲 |
| 3 | 校验一份大纲 md，并预览它会生成哪些文件 |
| 0 | 退出 |

## 三种入口

**新建**：读缩进清单，转成大纲 md（头部 `---` 块写 `levels:`，填了笔记名时另有 `name:`，正文用 Markdown 标题表示层级），再列出将生成的文件数与前若干个路径，并给出接着可用的 `new_note.py` 命令。输出路径默认 `<工作区>/<笔记名>.md`，笔记名留空则为 `outline.md`。

**导出**：读 `main.tex` 中 `\mainmatter` 与 `\backmatter` 之间（找不到就用全文）的「标题命令 + `\input`」对，按 `\input` 的形状递归搭出目录树，再从各层文件里读中译名。要点：

- 顶层命令取自 `main.tex`，其余层按 LaTeX 章节命令的固定次序顺延，不按各层实际读到什么去投票。
- 被 `%` 注释掉的章照样收（多半是还没写的章），并单独提示条数。
- 中译名读不到时只写目录名，末尾汇总提示处数。
- 写完即回读校验：导出的 md 必须能重新解析出同一份文件清单。

**校验**：读 md，核对 `levels:` 与标题层数是否一致；缺 `levels` 或与之不符时按结构推断并说明依据，然后列出元信息、层级模式、顶层节点数与将生成的完整文件清单。

## 层级模式

`levels:` 写「由外到内」的章节命令序列，`-` 表示该层只作分组、不产生标题命令。也可写简写名：`textbook`、`textbook-part`、`two-level`、`article`、`grouped`。解析、推断与写回都由 `new_note.py` 提供，两个脚本共用同一套规则。

## 退出码

`0` 正常；`1` 校验未通过、找不到输入，或解析失败。

## 注意事项

- 命令行模式一律不弹提问，只给结论与改法；只有 `--write-levels` 会改动 md。
- `--export` 与 `--from-text` 省略输出路径时，分别落到 `<工作区>/<笔记名>_outline.md` 与 `<工作区>/outline.md`。
- 导出的是「计划」而非现状：注释掉的章、没写标题的目录都会出现在结果里，导入前宜人工核对 `levels:` 那行。
