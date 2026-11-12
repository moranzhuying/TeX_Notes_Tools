# sync_paths.py

检查各工具配置里写死的绝对路径是否仍有效，失效时在整个工作区内重新定位候选，并可写回。

目录一旦改名或移动，配置就会悄悄失效：工具不报错，只是扫不到笔记、或找不到符号来源。

## 用法

```bash
python sync_paths.py         # 交互：先检查、只报告；发现失效再问要不要修
python sync_paths.py --check # 只检查、只报告，不修改任何文件
python sync_paths.py --write # 检查并修复（多个候选时逐个询问）
python sync_paths.py --yes   # 配合 --write：不询问，取唯一候选，多候选则跳过
```

总面板选项 11 以无参数方式运行，即「先检查，再问是否修复」。

## 检查哪些配置的哪些字段

| 配置文件 | 键 | 期望指向 | 失效时如何重定位 |
|---|---|---|---|
| `symbols/symbols.conf` | `template` | 某个 `structure.sty` | 先在该路径的祖父目录下找 `*/structure.sty`，再全工作区搜同名文件 |
| `symbols/symbols.conf` | `root` | 笔记根目录 | 找「其下至少两个子目录各含 `structure.sty`」的目录 |
| `manager/manager.conf` | `root` | 笔记根目录 | 同上 |
| `progress/progress.conf` | `root` | 笔记根目录 | 同上 |

此外扫描工作区内所有 `.cwl_source`：取其第一条非注释、非空的行作为路径，目标不存在就同样给候选并（在 `--write` 下）改写。

配置值支持环境变量（如 `%APPDATA%` 形式）与相对配置文件所在目录的相对路径。**留空不算失效**：`progress.conf` 的 `root` 留空表示「用脚本所在目录」。

## 修复方式

- 只有一个候选：直接采用。
- 多个候选：交互式逐个询问（给编号，回车跳过）；加了 `--yes` 则不猜，直接跳过该处。
- 写配置时只替换那一行，其余行原样保留；文件按 UTF-8 无 BOM、LF 重写。`.cwl_source` 则替换其内容里的旧路径。

扫描时跳过 `.git`、`__pycache__`、`_tools`、`node_modules`、`.workbuddy`、`_backup_tools`。

## 注意事项

- 不带参数运行是安全的：先只检查，报告完再问是否就地修复。
- 重定位靠目录特征（子目录里 `structure.sty` 的数量）与文件名，不读内容；同名文件较多时务必人工确认候选。
- 不动任何笔记或模板内容，只改配置文件。
- 退出码：没有失效、或 `--write` 后全部修复返回 `0`；仍有失效未解决返回 `1`。无参数的交互模式恒返回 `0`。
  所以要拿它当门禁就用 `--check`：`python sync_paths.py --check || echo "有配置失效"`。
- `--write --yes` 遇到多个候选会跳过该处，此时退出码为 `1` —— 这不是出错，是提示还需人工选定。
