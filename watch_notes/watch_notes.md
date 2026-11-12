# watch_notes.py

笔记目录监测：定时检测某个笔记仓库的改动并自动提交推送，同时按另一个间隔把历史**裁剪到固定条数**，让历史长度收敛而不是无限增长。

## 用法

```bash
python watch_notes.py                        # 交互面板：选仓库、设间隔后启动
python watch_notes.py --list                 # 只列 LaTeX_Notes 下的仓库
python watch_notes.py --dir Algebra          # 直接监测（相对 LaTeX_Notes）
python watch_notes.py --dir Algebra --once   # 只跑一轮后退出
python watch_notes.py --dir Algebra --fresh  # 丢弃上次状态，重新开始
python watch_notes.py --dir Algebra --keep 5 # 历史只留最新 5 条
python watch_notes.py --dir "D:/某处/仓库"    # 也可给绝对路径
```

不带任何参数才是交互面板；只要给了参数就按命令行模式跑。

## 三个参数

| 参数 | 默认 | 作用 |
|---|---|---|
| `--interval` | 300 秒 | 每轮 `git status --porcelain` 检查目录，有改动就 `add -A` + commit + push |
| `--prune-interval` | 900 秒 | 每隔这么久检查一次历史长度 |
| `--keep` | 20 | 历史保留条数上限；超过就裁到这么多 |

**为什么不是「每次删最早一条」**：提交按 `--interval` 不断产生，一次只删一条时净增长永远为正。按 5 分钟检测、15 分钟删一条算，每 15 分钟新增 3 条、删 1 条，历史只会变慢地涨下去。必须按上限裁剪才收敛。

裁剪只在工作区干净时执行；工作区还有未提交改动就跳到下一轮。

## 裁剪怎么裁

用 `commit-tree` 从保留段的起点逐条重建：沿用原来的树、提交信息、作者与提交时间，只断掉更早的父链。然后 `update-ref`（带旧 head 做 CAS）→ `reset --hard` 对齐工作区 → `push --force-with-lease`。推送成功后再 `reflog expire --expire=now --all` 与 `gc --prune=now`，让旧对象从 reflog 和对象库里真正消失。

不开 `rebase`，所以不会被空提交判定或冲突打断。推送失败时不做清理，保留现场可回滚；历史未超上限时原样跳过。

**注意**：这会重写该仓库全部后续提交的哈希。若别的机器也有同一仓库的副本，那边需要重新 clone 或 `reset --hard` 对齐。

## 状态与恢复

状态存在 `watch_notes/_state/watch-<目录哈希>.json`，记录 `cycles`、`last_prune_ts`、`last_commit`，每轮原子写入。

- 默认（不带 `--fresh`）：启动时读取上次状态，沿用轮次计数与上次裁剪时间，不会一启动就裁历史。
- `--fresh`：清空状态，从头开始。
- Ctrl+C 中断：保存状态并写一行退出日志。

日志在 `watch_notes/_logs/watch-<目录哈希>.log`。`_state/` 与 `_logs/` 均由 `.gitignore` 排除，不随仓库分发。

## 面板

不带参数运行，面板列出 `LaTeX_Notes` 下的 git 仓库，填序号选一个，再设检测间隔、裁剪间隔、保留条数，并选择是否从头开始，随后进入监测循环（Ctrl+C 停止）。总面板选项 16 以无参数方式运行本工具，即直接进这个面板。

## 约束

- `--dir` 指向的目录必须是 git 仓库根（会校验 `--show-toplevel`），否则不提交。
- 同目录同时只允许一个监测实例（文件锁）。
- 推送用 `--force-with-lease`，远端若有他人提交会拒绝，不会强行覆盖。
