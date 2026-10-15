# video2text —— 视频转文字

把没有字幕的讲座视频（B站 / YouTube）转成**带时间戳的纯文本**，供大模型整理成
LaTeX 笔记。全程本地、免费，不依赖按量付费的云端视频理解。

## 工作流程

工具是**两段式**的，先探测再决定怎么转：

```
输入链接
   │
   ├─ 探测字幕（yt-dlp --list-subs 等价物）
   │
   ├─ 有字幕 ──→ 下载字幕 → 解析 → 带时间戳 txt   （秒级）
   │
   └─ 无字幕 ──→ 默认记录失败；显式 auto/whisper 才下载音频并转写
                 （-f ba 直接取流，不转码，因此**不需要 ffmpeg**）
```

**为什么要先探测**：有字幕时几秒就能完成，走 whisper 则要按音频时长等比消耗时间
（实测实时率约 0.5x，即两小时视频需一小时）。两者差三个数量级，所以不要习惯性直接开转写。

## 用法

### 交互面板（推荐）

```
python video2text.py
```

从总面板 `launcher.py` 的第 13 项进来也是这条路。面板功能：

| 选项 | 说明 |
|---|---|
| 1. 转写视频 | 粘贴链接，自动识别合集并增量逐集处理；默认仅字幕，可配置允许语音转写 |
| 2. 批量转写 | 一行一个链接（也支持逗号/空格分隔），与单链接和 CLI 共用合集增量入口 |
| 3. 已转写 | 列出与预览已有内部产物；删除入口已停用，避免标题副本与内部索引失配 |
| 4. 重新登录 B站 | 扫码登录，登录态长期复用 |
| 5. 环境与模型状态 | 检查依赖版本、模型、登录态有效期 |
| 6. 合集管理 / 导出 / 锁诊断 | 按当前顺序查看，补同步标题目录，导出带索引及失败清单的 ZIP，只读诊断锁 |

### 命令行

```
python video2text.py <URL>                     # 自动识别合集并增量处理
python video2text.py <URL> --single            # 不展开合集，只处理当前视频
python video2text.py <URL> --force             # 强制重做本次所选视频
python video2text.py <URL> --force-whisper     # 忽略字幕，强制走 whisper
python video2text.py <URL> --model large-v3    # 换更大的模型
python video2text.py <URL> --lang ai-zh        # 指定字幕语言码
python video2text.py <URL> --no-cookies        # 匿名探测（不读登录态）
python video2text.py <URL> -o D:/某目录         # 换输出根目录
python video2text.py --list                    # 列出已转写
python video2text.py --status                  # 环境与模型状态
python video2text.py --login                   # 扫码登录
```

常用参数：

| 参数 | 作用 |
|---|---|
| `--mode subtitles/auto/whisper` | 默认仅字幕；auto 仅在无可用字幕时转写；whisper 强制转写。字幕下载/解析失败不静默回退 |
| `--only-failed` | 仅补做已记录 failed/pending 项；不处理本次新发现项，不能与 --force 同用 |
| `--collections` | 列出本地已记录合集，无需加载模型 |
| `--sync-titles ID` | 从已校验的内部转写文字同步某合集标题目录，不联网、不转写 |
| `--export-collection ID --export-to PATH` | 导出 ZIP；文件路径不得已存在，目录路径自动避让；不完整时包含失败清单并返回非零 |
| `--lock-status` | 只读诊断输出根锁，不自动删锁或抢锁 |
| `--single` | 只处理当前视频；无 p 的 BV 选择第 1P，不展开所属合集；纯合集链接需改用具体视频链接 |
| `--force` / `--refresh` | 强制重做本次所选集；不改变单集/合集选择范围 |
| `--all-parts` | 即使输入有 p 也展开全部分P及同页合集；不能与 `--single` 同用 |
| `--force-whisper` | 忽略字幕但仍跳过已有成功集；要重做须同时加 `--force` |
| `--model NAME` | whisper 模型名，默认取配置（`medium`） |
| `--model-dir DIR` | 指定本地模型目录（默认自动探测 `_data/models/`） |
| `--device` / `--compute-type` | 默认 `cpu` / `int8` |
| `--no-vad` | 关闭静音过滤（默认开启，讲座类提速明显） |
| `--drop-audio` | 转写后删除音频文件 |
| `--whisper-language` | 转写语言，默认 `zh`；传 `''` 为自动识别 |

## 合集识别与增量

- 无 `p` 的完整 B站 BV 链接自动识别分P，以及公开元数据提供的不同 BV 合集（`ugc_season`）；每个 BV 内的分P也会展开。
- 显式 `?p=N` 默认只处理这一集，不意外处理整套课程。`--all-parts` 是主动扩大范围的开关。
- B站空间合集/列表链接及其它 yt-dlp 支持的 playlist 使用 `extract_flat=in_playlist` 获取完整分页元信息，不下载视频、不设集数上限。普通 BV 的 extractor 不自动展开不同 BV 合集，因此公开 view 元数据用于补足这一限制。
- 每次重新发现当前成员；只补新增、失败、pending、文件缺失/空文件或 SHA-256 不匹配的集。标题修改、重排和重复成员不会重复转写；移除成员的文件不会自动删除。
- 集身份使用 BV+cid，或 extractor+稳定条目 ID；缺稳定 ID 时使用规范 URL 哈希，不以标题或序号作键。同名视频写入不同身份目录。
- 成功记录必须核验非空产物并保存 SHA-256。manifest 逐集原子写入；异常或 Ctrl+C 保留此前成功集，下次自动补做未完成集。损坏/不安全的 manifest 拒绝覆盖。
- 同一输出根通过独占锁禁止并发处理。正常异常和 Ctrl+C 自动释放；强制结束进程可能留下锁，须确认对应进程已退出后人工处理，工具不擅自抢锁。
- 旧标题目录或外部批处理产物不会隐式导入、覆盖或搬迁；缺少身份/哈希记录时不能靠文件名猜测。先前指定的图论课程历史 52 集已经人工核对公开视频分P与原文后单独登记到当前索引；其它旧结果仍须逐份核实，不能套用那次导入规则。
- 合集元信息不完整或不可访问时拒绝记录不完整成功。字幕和音频探测均明确 `noplaylist=True`。

## 可靠性与恢复

- 默认 `download.mode = subtitles`，只有显式 `--mode auto` / `--mode whisper` 或 `--force-whisper` 才允许长时间语音识别。探测、字幕下载采用有限重试；下载/解析失败、指定语言缺失、空字幕分别记录，不把它们当作无字幕直接回退。
- 过滤弹幕/评论轨，支持 B站 JSON、YouTube JSON3、SRT 与包含短时间戳的 VTT。字幕下载使用按域、路径及有效期匹配的 CookieJar，并校验 HTTPS 和重定向；不手工向任意字幕地址附加登录 Cookie。
- 文字正文与 manifest 都先写同目录临时文件再原子替换；写入失败保留旧正文。失败原因在 manifest 中保存安全分类，不持久化含请求凭据的异常。
- 音频写入每集 `.audio-cache/`；使用源链接、大小与 SHA-256 验证后复用，固定暂存目录支持下载器续传。身份未知的旧 `audio.*` 不自动复用、不移动；损坏缓存拒绝覆盖并提示先备份处理。
- 独立心跳定期报告加载/解码/转写阶段、完成百分比、耗时及已完成音频位置，不依赖片段返回。ETA 由本次已实测的转写速率推算（排除加载与解码耗时），样本不足时显示「待测速」而不给数字。
- Whisper 默认按 5 分钟无重叠音频块保存独立检查点，中断最多重做当前未提交块；绑定音频摘要、模型来源及转写参数，改变绑定不会误用旧结果。检查点损坏时拒绝覆盖；分块识别可能影响句子边界，不保证与整段推理逐字相同。
- `--force --mode whisper` 会新建转写代际，不复用旧完成检查点；该次中断后，不带 `--force`、保留相同转写模式和参数重跑即可恢复活动代际。再次加 `--force` 则明确另开新转写。旧检查点保留，不自动清理。
- `--drop-audio` 仅在转写文字成功后清理已验证的缓存音频，保留检查点及未知文件；下次需要音频会重新下载。强制杀进程可能残留主锁或音频缓存锁，`--lock-status` 会同时列出两者，不会自动抢锁。
- 缓存仅验证本地字节与源身份，不联网探测相同源的远端音频是否替换；检查点目前先解码整段音频，长课程仍需相应内存。分块质量与真实推理速度需在具体硬件上评估，不能把离线模拟测试等同于整套真实识别验收。

## 输出格式

日常阅读使用 `<数据目录>/transcripts/<合集标题>/`：合集里按当前集序放同一层 TXT，前缀 `01`、`02` 等补零序号后接每集转写头部视频标题（安全替换 Windows 非法字符、同名加稳定后缀）。单集使用 `<视频标题>/<视频标题>.txt`。增量运行会同步标题副本；离线补同步用 `python video2text.py --sync-titles <合集ID>`，现有成果可不联网、不重新转写直接整理。标题副本与权威内部产物内容相同，但不移动/删除原件；已登记文件被外部修改时拒绝覆盖。若合集或分集改名，旧管理副本会暂留而不自动删除，请以当前索引为准，不把旧同名文本当新增集。数理逻辑课程第一次同步因解析缺欠产生的 4 份 `studio_video_*.mp4.txt` 重复副本（与同号正式文件逐字节相同）已人工核对后移入回收站，索引中对应登记与一条失效登记同时清除；备份在 `.workbuddy/backup/logic-title-aliases-20261015/`。

内部断点、音频缓存与安全增量判断仍以 `<数据目录>/transcripts/episodes/<稳定集ID>/transcript.txt` 和同根 `.video2text-manifest.json` 为准，`-o` 替换输出根目录：

```
# 转写来源：B站/YouTube 字幕（语言码 ai-zh）
# 标题：拓扑（专业版）5:超滤与紧的刻画证亚历山大子基定理（黄书棋）
# 时长：02:50:30

[00:00:02] 上次讲了什么度量空间或者维度量空间
[00:00:09] 第二可数等价于可分等价零的咯
```

时间戳为 `[HH:MM:SS]`，便于回溯原视频对应位置。文件统一 UTF-8 无 BOM、LF 换行。

## 配置

复制 `video2text.conf.example` 为 `video2text.conf` 后按需修改。配置项：

| 段 | 键 | 说明 |
|---|---|---|
| `paths` | `python` | 运行用的解释器；留空自动探测 |
| `paths` | `data` | 数据目录；留空用脚本同级 `_data` |
| `whisper` | `model` | 模型名 |
| `whisper` | `device` / `compute_type` | 无独显用 `cpu` / `int8` |
| `whisper` | `vad` | 静音过滤开关 |
| `whisper` | `language` | 转写语言；留空自动识别 |
| `whisper` | `prompt` | **注入的领域术语，对专业词识别影响很大** |
| `download` | `browser` | 扫码登录用的浏览器通道 |
| `download` | `mode` | subtitles（默认）/ auto / whisper |
| `download` | `subtitle_retries` | 字幕探测与下载额外重试次数，0–5 |
| `download` | `keep_audio` | 转写后是否保留音频 |

## 注意事项

### 术语需要纠错

自动字幕对人名与音译词不友好，同一术语常有多种错误写法。整理成笔记时建议带上术语表，
由大模型统一校正。这是把转写文本喂给模型时最值得做的一步。

### whisper 会有重复幻觉

长音频转写偶发连续重复同一句。已用 `condition_on_previous_text=False` 缓解，但无法根除，
整理时留意删重。

### B站 字幕需要登录

B站 对匿名请求一律返回空字幕列表，取字幕必须带登录态。本工具用**专用 profile**扫码登录一次，
之后长期复用；不借用日常浏览器的登录态（原因见下）。

专用 profile 与扫码登录的设计，是为了在「浏览器加密存储凭据」的环境下仍能稳定取到字幕，
同时避免动到用户日常浏览器的数据。

### 依赖版本约束

`faster-whisper` 依赖 PyAV 解码音频。**PyAV 19 移除了 `av.open()` 的 `metadata_errors` 参数**，
而 faster-whisper 1.2.1 仍在传它，直接安装会得到不兼容的组合并导致转写报错。
安装时需约束版本：

```
pip install yt-dlp faster-whisper "av<19"
```

可用 `python video2text.py --status` 检查当前版本是否合规（工具会标出 PyAV 是否过高）。

### 模型下载

模型默认从 HuggingFace 生态拉取。两点注意：

- 需设 `HF_HUB_DISABLE_XET=1` 才能强制走传统 HTTP 分发端点；否则会走 Xet 协议而失败。
  （`HF_ENDPOINT` 只影响传统端点，管不到 Xet。）
- 国内环境推荐改用 ModelScope 源，实测明显更稳。

本工具已内置上述环境变量，无需手动设置。模型下载到 `_data/models/` 后即离线加载，
不再联网。

## 文件结构

```
video2text/
├── video2text.py            主脚本（面板 + 命令行双模式）
├── video2text.md            本说明
├── test_video2text.py       可重跑离线 unittest
├── video2text.conf.example  配置模板
├── video2text.conf          本机配置（不入库）
└── _data/                   运行时数据（不入库）
    ├── models/              whisper 模型
    ├── cookies/             登录态
    ├── profile/             扫码登录专用浏览器官案
    └── transcripts/         转写产物
```

`_data/` 与本机 `.conf` 均在 `Tools/.gitignore` 中排除：模型体积大、
cookie 含登录凭证、profile 含浏览数据，都不应进入版本库。

## 离线回归

从工作区根运行 `python -m unittest discover -s Tools/video2text -p "test_*.py" -v`。测试使用临时目录与模拟元信息，不下载视频、不加载模型、不读取登录凭据。

增量边界：已成功且本地产物哈希一致的同 cid 不会再次探测远端字幕是否改版；要重新取字幕请用 `--force`。匿名公开元信息接口可能受风控或网络限制；发现失败时保留已有状态与产物，不把未完整发现的合集记为成功。
