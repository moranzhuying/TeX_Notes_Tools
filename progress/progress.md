# 写作工作台 · 使用说明

日常入口为 `workbench_launcher.py`，设计依据见 `progress_design.md`。默认只读；逐书保存和打开编辑器须分别显式授权。

旧版写作进度追踪表已于 2026-10-15 全部删除：`progress.py`、`progress_ui.html`、`progress.conf(.example)`、`progress_marks.json(+.bak)`、`progress_settings.json(+.bak)`、`progress_report.md`，以及退役拒绝入口 `workbench_legacy.py`。`progress/` 下只留本工作台一套文件。

---

## 总面板入口

从工作区运行 `python Tools/launcher.py`：

- **选项 4「写作工作台（默认只读）」**：打开前台日常配置面板 `progress/workbench_launcher.py`，检查root、端口和TeXstudio路径后启动本面板托管的服务。默认端口 `7656`，默认不授权保存、初始化或调起编辑器；allow-open须单独开启。
- `progress/` 只有本工作台一套文件，没有并存的旧版目录，也不设旧版面板入口；总面板编号 1–14 与提交项 12 不变。
- 端口被占用时报告错误，不结束占用进程；需另选端口可使用下面的独立命令。

启动与读取链路不导入、不读取任何旧版脚本、配置或标记数据。

在工作区独立启动（不打开浏览器）：

```text
python Tools/progress/workbench_server.py --root LaTeX_Notes --port 7656 --no-browser
```

`workbench_server.py` 仍要求显式 `--root`；日常配置面板从本机配置读取并验证根目录，不依赖当前目录猜测。独立 CLI 与日常面板默认端口均为 `7656`；历史验收端口保持独立，不自动停止或替换。独立 CLI 用 Ctrl+C 退出；日常面板选择停止或返回前会提醒保存网页输入，退出后停止自己托管的服务，不接管其它服务。

## 逐书日常保存独立许可（2026-10-13）

面板选项7独立启用/撤销保存；首次默认只读，allow-open互不授予权限。启用可输入已核实的书名到永久book_id的JSON对象，再输入SAVE确认当前许可根；原单个GT永久ID输入及GT确认保留。多书配置包含allow_write、write_books、绝对write_root和write_book_ids；每书独立UUID，重复ID或别名不能继承许可。不完整配置保持只读，完整失配拒绝启动；root变化清空全部许可。启动及每次POST重新核验根、书目录边界与永久身份。面板不自动初始化书、不迁移旧marks、不生成审核结论、不写TeX。

### 保存许可核验与发布边界（2026-10-13）

本轮在本机既有配置中核验八本登记书的许可根与独立永久ID，均已匹配，无需重新授权或初始化。正式启动面板 `Session` 在独立空闲端口提供只读GET证据：八书导航均为 `writable=true`，运行时基线均已有SHA256；未向真实书执行初始化、保存或恢复请求。页面 `enabled()` 的Node VM条件验证表明，在这些许可与初始化基线满足且无加载/冲突时，保存位置和编辑输入可用；这不冒充真实浏览器逐书点击或新的真实保存验收。

本机逐书许可不随公开代码分发；新配置依然默认只读，换根清空许可，已建立永久ID保持不变。`allow-open` 独立保持原值，不因保存许可而自动开启。测试服务只停止本轮自己创建的实例，不接管或停止既有服务。发布仅提交与推送现有 `main`，不创建tag、Release或PR；本机配置、真实书内数据、旧私密备注、输出证据和其它工具未提交改动均不纳入本轮提交。

### 旧标记迁移与旧版文件处置（2026-10-15 现行）

旧标记迁移已弃用：启动、读取、保存、报告和界面都不使用旧 JSON 或 legacy 归档，启动面板与编辑页也没有迁移或认领按钮。

2026-10-15 起旧版本体与拒绝入口一并删除：`progress.py`、`progress_ui.html`、`progress.conf(.example)`、`progress_marks.json(+.bak)`、`progress_settings.json(+.bak)`、`progress_report.md`、`workbench_legacy.py`。本机不再保留任何旧状态文件。

2026-10-15 用户要求彻底清空，残留的历史证据也已删除：书内 `Materials/workbench/legacy/<源hash>/` 归档（仅 Algebra、General_Topology 两本有）与本机 `progress/._data/` 退役声明一并清除；工作区 `outputs/legacy_retirement_20261013/` 此前已随 outputs 目录清理消失。工作台侧不再保留任何旧标记数据、归档或声明，书内 `Materials/workbench/` 只剩工作台自己的身份、运行、总结与备份文件。

配置使用临时文件fsync及原子替换，配置与临时文件均gitignore；损坏配置不自动覆盖。运行期间须先停止服务再修改配置，配置只在下次显式启动生效。隔离测试位于`Tools/progress/tests/test_gt_daily.py`，覆盖GT runtime/review/summary、三类409、永久ID替换拒绝及七书六类写端点（含恢复）拒绝；默认只读原测试保留。

## 日常外部编辑、重读与源码提示

新版顶部显示基线读取时间、文件变化提示及「重新读取磁盘（保留输入）」按钮。页面重新获得焦点、变为可见及可见期间每10秒检查 `/changes?since=<书名版本JSON>`；请求singleflight，隐藏后停止定时检查。服务只采集相关TeX、登记入口/Materials Markdown、Source、runtime/book身份与main.pdf的路径、mtime_ns、大小；排除.git、辅助文件、备份与锁。3秒TTL与锁合并并发扫描，保留最近16个版本用于新增/修改/删除比较；手动重读使用force=1绕过TTL，扫描失败保留最后有效基线并显示错误，响应标注实际扫描时间而非缓存请求时间。这是stat元数据签名，不是文件内容hash或完整审计；相同元数据的内容替换可能漏报。

变化仅标记书名与已有快照过期，不自动重读覆盖未保存输入、不重写审核结论、不自动编译。手动重新读取沿用同书输入保留行为，最新磁盘基线另列供比较；原书、单位或总结范围移除时保留原导航和草稿，并禁止保存；明确确认放弃旧草稿、重新选择后才恢复编辑，避免草稿错绑到新目标。

GET `/participation?book=&unit=` 递归检查main.tex中的基础input/include/includeonly，返回已见静态链/未见/待核实、原因、源码与PDF时间。注释不算静态输入；宏目标、条件、缺失/歧义目标、循环和复杂控制语义保守待核实，不据此断言分支激活。当前审核单位和搜索命中分别显示，不启用被注释章节。

「打开当前审核单位」与「打开当前搜索命中」是两个明确入口。命中按钮确认完整路径与行号，POST `/open`额外字段path/line须与同书已登记TeX及有效行号匹配；仍须独立allow-open与CSRF。TeXstudio随附background.html核验支持`--line xx[:cc]`，使用分离参数提交；响应不保证编辑器已完成定位。GET `/session`只读返回服务标识、随机会话ID、root/port及启动授权，用于识别同一服务；不返回CSRF，不改变权限。

## 2026-10-13 四项界面调整

全文搜索仅保留按需面板中的 `fullQuery/fullSearch/bookSearch`，顶部不再重复、无镜像或隐藏兼容输入；展开面板后 Enter 搜索当前书，全书与本书按钮保持原接口。当前单位和命中输入链均按结论、PDF时间与过期提示、静态链三行显示。源码/PDF tabs紧凑等高并与操作栏左对齐，兼顾390px布局。登记树、审核单位、正文/证明位置和总结范围共用 `Chap1`、`§1` 展示标签，中文标题保留；稳定ID、资料与TeX路径不变。仅保存HTML后刷新现有只读7656，不需要编译或重启服务。

可移植只读验收：`tests/test_ui_feedback_20261013.py` 调用同名 `.cjs` 运行独立jsdom及真实Edge深色1200/390截图，复用7656；`WORKBENCH_BASE` 可配置，jsdom依赖通过 `NODE_PATH` 指定。证据保存于 `outputs/workbench_ui_feedback_20261013`，真实笔记及index仅hash读取，不调用写接口。

## 五项按需功能

`workbench_features.py` 提供实时登记TeX同文件AND全文搜索、行号只读上下文、review疑点/阶段待补修订/TODO聚合，以及统计和报告共用汇总。未检查不计欠账，结论不混疑点，runtime主动计划和当前位置单列；旧私有备注及原全文不导出。未初始化书仍读取review权威，缺basis不算版本核验完成，stale单列；四阶段分母为全书登记目/直接节/附录单位；总结仅既有summaries scope，章与§分表，不与review逐目总结混算或合成总完成率。

新增GET `/search?q=&book=&limit=`（book空为八书，limit1..300）、`/source?book=&unit=&line=`、`/aggregate?book=`、`/stats?book=`、`/issues?book=`、`/report?book=`（Markdown附件，book空为全书架）。慢全量操作仅按钮显式请求，无全局陈旧缓存。审核按钮仅提交相对最新基线发生变化的字段，不为未变阶段重写依据；保存/恢复后使审计和汇总失效，已加载汇总重新读取，409保留输入但清除旧汇总。

`workbench_pdf.py` 只读登记书根main.pdf：GET `/pdf?book=`流读并支持单Range206/416，`/pdfinfo?book=`、`/pdfpage?book=&q=`；文本层pdftotext固定参数30秒超时，最长连续命中段优先，空词拒绝，没有PDF/工具或失败则清楚降级，不做OCR/自动编译。PDF时间与源码同步性不保证。页面CSP仅增加frame-src self，允许同源受控PDF，不允许任意外部地址。

POST `/open` 精确字段book/unit/confirm=true，沿用CSRF及Host/Origin；另须CLI `--allow-open`（默认禁OS）才能调起登记TeX。`--texstudio <现有绝对exe路径>`或本地探测，不用shell；该开关不授权TeX写入或自动打开，不管理/结束用户编辑器。页面按当前服务权限禁用打开按钮并显示原因；授权后当前单位确认框展示其登记路径，不自动采用搜索命中；搜索命中使用独立按钮确认完整路径和行号。章节input被注释不影响登记源码打开，但现有PDF可能没有该章节；不会自动启用或编译。启动失败显示专用错误，成功响应仅表示请求已提交。

若已明确授权调起编辑器，可另开独立只读服务（不停止7655/7656、不添加写权限；示例端口须空闲）：

```text
python Tools/progress/workbench_server.py --root <书架目录> --port 7657 --no-browser --allow-open --texstudio <TeXstudio可执行文件路径>
```

打开该服务控制台打印的回环地址，再选择审核单位并确认打开。`--allow-open`只授权调起程序；工作台仍只读，但不限制用户在TeXstudio中自行编辑。总面板选项4的默认权限保持不变。

## 只读原型

`workbench_readonly.py` 与 `workbench_readonly.html` 是独立验证入口。只读目录绑定、record/review 与源码 TODO，生成离线快照；默认未检查，不把源码有内容或旧 done 标记当审核通过。

支持节级直接正文、标准目及附录；绑定冲突和旧记录匹配候选仅列出，不迁移、不重编号、不修改 TeX 或 Markdown。总结视图按章/§收尾展示，现行缺少总结记录时明确未登记。原型中的书籍目录命名空间仅为临时标识，不冒称永久书籍 ID 已落盘。

快照是生成时的数据，不实时保存状态；查看与筛选不会改笔记。审核编辑、版本检查与跨进程冲突控制属于后续受控写入阶段。

## 受控保存模块

`workbench_store.py` 仅用标准库，提供 `init(root, book_dir)` 与 `BookStore(root, book_dir)`。打开对象只读；必须显式初始化后才有每书 `Materials/workbench/book.json` UUID 和 `runtime.json`。身份已存在不改，目录或展示缩写改变不重编号。不要对真实八书批量初始化。

- `read_review(unit_id)` / `patch_review(unit_id, patch, expected)`：按登记、record 和唯一 review 行核验，仅补丁 body/source/math/proof/issues/conclusion；expected 为完整原文件 SHA256。
- `read_runtime()` / `patch_runtime(patch, expected, expected_revision)`：当前位置、plan、version_basis 的强类型字段补丁；不接受整文件覆盖。
- `create_summaries()` 显式建立章/§/附录范围表；`read_summary(scope)` / `patch_summary(scope, patch, expected)` 只接受 summary/reason。
- `list_backups()` / `restore(backup_id, expected)`：仅恢复本书备份清单内已存在的 runtime、summary 或登记审核文件，禁止任意路径或恢复身份文件。

审核状态及原始 TeX/登记/record/Source SHA256 依据在同一 Markdown 原子保存（HTML 注释）。正文变化仅显示 stale，不改结论；缺依据显示 missing。改结论或疑点但不重新声明阶段，会使原依据 missing，不能冒充复核。数学通过须明确通过结论且无未决疑点。

保存有持久文件 OS advisory 书锁（Windows msvcrt.locking / POSIX fcntl.flock，解锁关闭句柄而不删除锁文件）、完整 SHA256 条件检查、时间/UUID 不覆盖备份、临时文件 fsync、原子替换和读后核对。失败 tmp 留证，不删除；旧 mkdir 锁目录保持不动。任何异常不返回成功；读后核对失败可能已经更改目标，应重新读取并选择备份恢复。陈旧或他人锁不自动删除。备份目录不是抗恶意篡改存储；本地有写权限者及不遵守书锁的编辑器不在协作锁保证范围内。

```text
python Tools/progress/workbench_store.py --help
python Tools/progress/workbench_store.py --root <隔离root> --book <书目录> init
python Tools/progress/workbench_store.py --root <隔离root> --book <书目录> review C05/S02
python Tools/progress/workbench_store.py --root <隔离root> --book <书目录> patch-review C05/S02 --patch '{"body":"进行中"}' --expected <完整SHA256>
```

保存模块不提供 TeX 编辑接口；HTTP/UI 由下述独立服务提供。初始化须显式操作；旧数据迁移已退役，不能执行。

## 独立HTTP/UI（隔离验收阶段）

`workbench_server.py` + `workbench_editor.html` 自带 HTTP 与保存逻辑。默认只读；`--allow-write` 与重复 `--write-book <已登记目录名>` 同时指定才授权该书，初始化还需网页明确确认。是否可保存由当前启动许可决定，未初始化书不会因读取而自动初始化。

```text
python Tools/progress/workbench_server.py --root <隔离root> --port 7655 --no-browser
python Tools/progress/workbench_server.py --root <隔离root> --port 7655 --no-browser --allow-write --write-book Book
```

仅绑定127.0.0.1；退出仅CLI中断，无网页关闭接口。GET `/data` 实时只读扫描而不保存快照；GET `/review?book=&unit=`、`/runtime?book=`、`/summary?book=&scope=`、`/backups?book=`。POST `/init`、`/patch-review`、`/patch-runtime`、`/create-summaries`、`/patch-summary`、`/restore` 接收精确JSON字段；init/create/restore要求confirm=true，补丁/恢复要求expected完整SHA256，runtime额外要求revision。400输入、403授权、409冲突、500持久化或读取失败。

精确Host/Origin、POST必需Origin与进程随机CSRF header、定长application/json最多65536字节、无CORS、no-store；仅根页面可静态访问。GET不建立锁和目录。页面展示missing/stale；冲突刷新基线但保留输入，必须明确重试；失败或无响应不显示成功。锁沿用保存层持久句柄，不删除。

回归测试位于 `tests/`，使用隔离资料副本，启动和结束自己拥有的临时服务；真实书架只读核对，不在其中试写。

HTTP/UI 验收应覆盖默认只读、显式许可、版本冲突和保存失败反馈；测试仅写隔离 fixture，并核对输入文件哈希。

可启动完整隔离交互演示（fixture Book 已初始化，Other 不在白名单；并非真实八书）：

```text
python Tools/progress/workbench_server.py --root <隔离fixture书架目录> --port 7655 --no-browser --allow-write --write-book Book
```

浏览器打开控制台打印的回环地址，结束用Ctrl+C。只读演示将root改为同轮`readonly`目录并去掉allow-write/write-book。不要直接双击editor.html冒充在线保存；本轮不另外生成静态假保存页面。

## 读取性能优化（2026-10-10）

启动白名单和详情书名验证只做实时书名/入口发现，不再扫描八书正文。每个 GET 的 BookStore 可共享一次登记目录及多值审核索引；默认直接使用 BookStore 不缓存，POST/写锁内强制放弃读快照并重新校验。没有全局、跨请求或长期缓存，下一请求识别入口增删、改路径及外部编辑；resolve 边界和完整版本保护不变。

只读扫描从同一次 TeX bytes 派生内容状态、SHA256 与 TODO；审核按单位建立多值索引，不丢重复冲突。review/summary 响应行与 SHA256 来自同一次读取。页面和接口保持不变；读取不自动初始化书籍或执行旧数据迁移。

性能对比应使用相同输入与同一扫描范围，并逐字段比较结果；不能以轻量导航代替完整审计作为加速证据。

## 首页轻量导航（2026-10-10）

独立编辑页首屏使用实时 GET `/navigation`，不读全量正文/record，不宣称完成审核；仅登记入口、路径存在及边界、review 标题和冲突提示。显式「执行全量审计」调用原完整 `/data`，完成仅表示现行登记绑定扫描，不表示数学、原书目录或已保存版本依据核验。错误入口、重复绑定及越界链接失败关闭，不静默隐藏。

「刷新基线」重新获取导航和详情，更新新增/消失书及单位列表，同书输入保留；刷新后旧审计标为须重跑。无跨请求导航缓存，POST 锁内 fresh 核验保持。完整扫描仍有 I/O 开销，拆分首屏不等于完整扫描加速。

## PDF 前台验收冻结与剩余风险（2026-10-13）

2026-10-14最终有界诊断：独立HTTP标签页、独立Blob标签页及产品备用按钮实际用户点击均为 **PASS**，已核对第一/第二页真实画布与页码。当前嵌入Blob与直接HTTP iframe仍为 **UNVERIFIED**（灰屏），整体保持 **PARTIAL/UNVERIFIED，不宣称全部PDF修复**；根因未确认，不归因于Blob释放或擅自调整浏览器安全设置。

本轮最小产品改动仅在 `workbench_editor.html` 增加 `openPdfTab` 备用按钮。完整已验证Blob加载后才可用，目标重置即禁用；必须用户明确同步点击才以 `noopener` 打开独立标签页并带目标页码，不自动打开、不下载、不修改PDF或后端。嵌入灰屏时可使用该已实际验收的备用路线；它不代表嵌入阅读器已修复。

冻结测试 `tests/test_pdf_foreground_acceptance.py` 联合核对实际页码与截图页首marker，并验证备用按钮真实点击。最终脚本exit 0、无失败项且保护检查通过；**exit 0不是所有路线渲染通过码**，必须读取各路线状态与画布证据。本机证据保留在输出目录，不随公开代码提交。

测试通过默认安装位置发现普通Edge，以独立临时profile进行有界验收，不固定本机用户目录。产品与测试现已冻结；不继续GUI重试，不安装PDF.js或宣称已定位嵌入灰屏根因。
