# commit.py / commit.sh

一键提交并推送到 GitHub。

## 运行

```bash
python commit.py                      # 以默认说明「更新笔记」提交
python commit.py "说明"                # 以指定说明提交
python commit.py "说明" -y             # 跳过确认
python commit.py "说明" --dry-run      # 只显示将要提交的内容，不实际执行
python commit.py "说明" --log config   # 同时写入 CHANGELOG 的「tex 配置调整」
python commit.py "说明" --log content  # 同时写入 CHANGELOG 的「正文内容调整」
python commit.py "说明" --log auto     # 按关键词自动判断分类
python commit.py --help               # 查看用法
```

Bash 版行为一致：

```bash
bash commit.sh "说明"
```

## 选项

| 选项 | 功能 |
|---|---|
| （位置参数）`"说明"` | 提交说明。省略则用默认的「更新笔记」 |
| `-y` | 跳过提交前的 `[y/N]` 确认（脚本化调用时使用） |
| `--dry-run` | 只列出将要提交的文件与提交说明，不执行任何 git 操作 |
| `--log config` | 提交前把说明写入 `CHANGELOG.md` 的「tex 配置调整」 |
| `--log content` | 同上，写入「正文内容调整」 |
| `--log auto` | 按关键词自动判断该写入哪一节 |
| `-h` / `--help` | 显示用法 |

## 执行后在命令行窗口看到的内容

**正常提交**（提交前列出改动，便于核对）：

```
将要提交 3 个文件的改动：
   M Content/1_Topological_Structures/1_Open_sets.tex
   M CHANGELOG.md
  ?? commit.md

提交说明：补充开集的定义

确认提交并推送？[y/N] y

==> 暂存改动
==> 提交：补充开集的定义
==> 推送到 GitHub
完成，已同步到 GitHub。
```

**没有改动**：

```
没有改动，无需提交。
```

**推送失败**（已自动重试，仍不通）：

```
==> 推送到 GitHub
    …等待 3 秒后重试（第 1 次）
    …等待 6 秒后重试（第 2 次）
    …尝试备选通道：改用 22 端口
[警告] 连接超时或被拒 —— 检查网络；若使用代理，请确认 git 的 http.proxy 设置。

本地提交已成功，仅未推送到远程。
网络恢复后单独运行下面这条命令即可：
  git push
```

**不是 git 仓库**：

```
[错误] 不是 git 仓库，或 git 不可用：
  fatal: not a git repository ...
```

## 推送失败的自动处理

推送失败时脚本按下列顺序处理，不需要人工干预：

1. **自动重试两次**，间隔 3 秒、6 秒（应对网络抖动）；
2. **尝试备选通道**——若远程是 SSH 地址，改用 **22 端口**重试一次（本机默认走 `ssh.github.com:443`，两个端口互补）；
3. **归类报错并给出针对性建议**：

| 报错特征 | 提示 |
|---|---|
| `Permission denied` / `publickey` | 认证失败——SSH 密钥未被接受，检查密钥与连通性 |
| `Could not resolve` | 域名解析失败——检查网络与 DNS |
| `timed out` / `connection refused` | 连接超时或被拒——检查网络，确认 `http.proxy` 设置 |
| `No configured push destination` | 未配置远程仓库——先 `git remote add origin <地址>` |
| `Repository not found` | 仓库不存在或无权限——检查仓库名与账户 |
| `non-fast-forward` / `rejected` | 远程有新提交——先 `git pull --rebase` 再推送 |

若全部失败，脚本明确告知**本地提交已成功**，只需在恢复网络后单独执行 `git push`。

## 行为

1. 切换到脚本所在目录（即项目根目录）
2. 用 `git status --porcelain` 检查改动，无改动则直接退出
3. 列出将要提交的文件与提交说明
4. 若指定 `--log`，先把说明写入 `CHANGELOG.md`
5. 请求确认（`-y` 可跳过）
6. 依次执行 `git add -A` → `git commit` → `git push`

推送走 SSH（GitHub 443 端口）。

**提交失败与推送失败分开处理**：前者说明改动未被记录，后者说明改动已提交但未上传，脚本会明确提示是哪一种，并给出补救命令。

## 与 CHANGELOG 联动

`--log` 会把提交说明写入 `CHANGELOG.md`，格式与手工维护的一致（见该文件的既定结构）：

- 自动定位到当天的日期小节；当天没有则新建，**按日期倒序**插在合适位置。
- 同一天多次提交，自动编号为「第 N 次提交」。
- 说明中的**分号**（`;` 或 `；`）会拆成多个列表项。

```bash
# 写入「tex 配置调整」，生成两条列表项
python commit.py "新增符号管理说明;更新 README" --log config

# 自动判断：含「符号库」等关键词 → 配置节；否则 → 内容节
python commit.py "补充第 4 章正文" --log auto
```

自动分类依据关键词（符号、structure、cwl、编号、目录、脚本、配置、模板、记号、编译等）判断；**判断不准时请显式指定** `config` 或 `content`。
