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
   └─ 无字幕 ──→ 下载音频流 → faster-whisper 转写 → 带时间戳 txt
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
| 1. 转写视频 | 粘贴链接即可，自动判断走字幕还是 whisper |
| 2. 批量转写 | 一行一个链接（也支持逗号/空格分隔），逐个转写并汇总 |
| 3. 已转写 | 列出已有产物，可预览前几条、可删除 |
| 4. 重新登录 B站 | 扫码登录，登录态长期复用 |
| 5. 环境与模型状态 | 检查依赖版本、模型、登录态有效期 |

### 命令行

```
python video2text.py <URL>                     # 直接转写
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
| `--model NAME` | whisper 模型名，默认取配置（`medium`） |
| `--model-dir DIR` | 指定本地模型目录（默认自动探测 `_data/models/`） |
| `--device` / `--compute-type` | 默认 `cpu` / `int8` |
| `--no-vad` | 关闭静音过滤（默认开启，讲座类提速明显） |
| `--drop-audio` | 转写后删除音频文件 |
| `--whisper-language` | 转写语言，默认 `zh`；传 `''` 为自动识别 |

## 输出格式

产物写到 `<数据目录>/transcripts/<视频标题>/transcript.txt`：

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
