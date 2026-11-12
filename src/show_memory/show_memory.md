# show_memory.py

查看工作记录：列出 `.workbuddy/memory/` 下按日期归档的工作日志与长期记忆 `MEMORY.md`，按需打印内容。只读。

已从总面板移除，需要时单独运行。

## 用法

```bash
python show_memory.py            # 列出全部记录与大小
python show_memory.py --list     # 只列文件名
python show_memory.py --last 3   # 看最近 3 天
python show_memory.py <日期>     # 看某一天，格式 YYYY-MM-DD（可带或不带 .md）
python show_memory.py 2          # 按列表里的编号看
python show_memory.py MEMORY     # 看长期记忆
```

记录目录固定为工作区下的 `.workbuddy/memory/`，只取其中的 `*.md`。

## 列什么

不带参数时先打印记录目录，再逐行列出「序号 · 文件名 · 字节数」，末行给出用法提示。

排序按文件名**倒序**，因此 `MEMORY.md` 排在最前（字母排在数字之后），其后的日期记录由新到旧。列表里的序号就是 `python show_memory.py <编号>` 用的编号。

## 按日期取

- `--last N`：按日期取最近 N 份，**不含 `MEMORY.md`**（它没有日期，不该占名额）；N 缺省或不是数字时按 1 处理。
- 直接给日期（`YYYY-MM-DD`，或带 `.md` 的全名）：打印该文件。
- 给数字：按列表序号取。
- 给 `MEMORY`：打印长期记忆。

每份内容前有一行标题，含文件名与字节数；正文原样输出，不截断、不做转换。

## 退出码

`0` 正常；`1` 记录目录不存在，或给的关键词匹配不到任何记录。

## 注意事项

- 全程只读；记录目录不存在时直接报错退出，不会去创建它。
- 输出是纯文本，Markdown 不渲染。
- 本工具不解析记录内容，也不做汇总或检索。
