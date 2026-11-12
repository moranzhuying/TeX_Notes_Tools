# 写作工作台 · 设计文档

> 本文记录工作台的现行边界。总面板只有选项 4 一个入口；工作台默认只读，保存与打开编辑器须分别授权。

---

## 旧标记迁移已弃用

工作台不规划、迁移、确认、归档或建立任何认领任务；启动面板及编辑页无迁移按钮，运行数据不读取旧标记或 legacy 归档。

## PDF 预览的边界

嵌入预览（嵌入 Blob 与直接 HTTP iframe）在部分环境中显示灰屏，根因未确认，状态为部分可用而非整体通过。前台测试脚本 exit 0 允许部分通过，只说明运行完成与保护检查通过；判断结果须联合读取整体状态、viewer 页码与真实截图标记，不能仅凭片段、load 事件或 DOM 页码断言成功。

## 2026-10-13 日常工作台读取边界

`workbench_daily.py`将低成本变化提示与审核依据分开：stat签名不读文件正文，不代替SHA256 basis；锁加3秒TTL合并全书架元数据枚举，前端可见时每10秒singleflight，并在focus/visibility恢复时检查。版本历史每书最多16份，超出历史仅提示变化而不伪造新增/删除明细。外部变化只令快照过期，保留dirty字段与审核结论；手动重读展示新基线但保留同书输入。

源码参与提示按书根main递归静态解析基础input/include/includeonly。解析遇条件、宏、特殊控制、缺目标、歧义或环则unknown；seen只表示静态链可见，不保证实际激活，unseen也不阻止授权打开。PDF与最新已见源码及目标时间比较仅提示可能过期，不以mtime证明内容一致。不存在自动编译、启用章节或修改真实tex/marks/index的路径。

打开审核单位和命中目标分别确认，后端按同书登记 TeX 白名单再次解析，命中 path 须严格相等且 line 在当前文件范围内；allow-open 保持独立、默认关闭。TeXstudio 的 `--line` 按分离参数提交，仅报告已提交请求，不声称编辑器完成定位。session 身份接口只读且不含 CSRF。

## 五项移植边界

全文搜索与源码只读登记文件，实时请求不维护全局正文缓存。问题聚合只读，review疑点不混结论，未检查不计欠账；TODO编号book作用域，审核解决不改TeX注释，主动计划单列。统计与Markdown报告使用同一aggregate函数，四阶段按目/直接节/附录适用单位，总结仅已有summaries按章/§分表；缺basis和stale不能冒称核验完成，无单一总完成率。默认报告不读旧私有备注或源码全文。

PDF书根main.pdf流读、单Range、固定pdftotext文本层定位并清楚降级；iframe限定CSP frame-src self，PDF不保证与源码同步。TeXstudio须独立allow-open和confirm true、POST原CSRF/Host/Origin保护、登记TeX白名单、subprocess list无shell；不因此开放TeX写接口。所有慢扫描和OS打开均非首页动作；总面板选项 4 是唯一前台启动配置入口。

## 2026-10-10 已确认的新工作台方向

工作台先以独立只读适配层 `workbench_readonly.py` 与静态页面 `workbench_readonly.html` 验证绑定与审核语义，不写入笔记或任何旧标记。

- 现行资料目录绑定与 record/review 交叉核验；支持目、节级直接正文与附录，冲突显式列出，不猜补身份。
- review.md 为阶段审核权威，默认未检查；正文、来源对照、数学审核、证明回填独立，总结主要在章/§层面。TeX 有内容不代表审核完成。
- 三视图为正文、证明、总结；源码 TODO 首版只读关联；习题不计入正文阶段。
- 正式阶段按书保存运行位置、计划与版本依据，永久书籍身份独立于可变缩写；只读原型临时命名空间不冒称永久 ID 已落实。
- 旧 JSON 不参与运行；缺省或显式 done 不升级为已审核，不真实迁移。
- 原型输出只读快照；通过绑定全量核查、合成边界、旧新 A/B 和真实网页交互后，再开发带版本检查/备份/锁的受控编辑。不自动修改 TeX，不对外联网。

## 2026-10-10 受控保存层

实现入口为独立 `workbench_store.py`，不替换只读原型。审核权威仍是 review.md；stage 与 basis 采用同文件 HTML 注释原子持久化，避免审核行已完成但 JSON 依据未保存的跨文件半事务。basis 是原始 TeX、登记入口、record、Source 的完整 SHA256；变化仅提示 stale，缺失显示 missing。运行 JSON 的 version_basis 不是审核权威。

每书身份 UUID 显式 init 后写 Materials/workbench/book.json，已存在绝不重写；runtime 字段补丁须 SHA256 和 revision 双条件。总结另放显式创建的 Materials/workbench/summaries.md，按已登记 C/S/A 范围独立分母，不与目级 body/proof/source/math 混合。

每次保存使用持久 `.workbench-store.advisory.lock` 文件：Windows 为 msvcrt.locking，POSIX 为 fcntl.flock，非阻塞获取，finally 解锁并关闭句柄，文件保留。旧 mkdir 锁目录仅留证不清理；外部锁占用返回冲突。失败 tmp 保留，不执行删除操作。修改前以时间/UUID 唯一目录记录不可覆盖备份和 manifest；条件核对后 os.replace，读后核对失败不报成功。恢复仅可指定本书清单 backup_id 和当前完整 expected，不能提供任意文件路径。resolve 边界包括符号链接；不支持对抗有书目录写权限者恶意并发替换符号链接的操作系统级沙箱。

当前只交付本地模块/argparse CLI 与隔离测试；未开发 HTTP/UI、自动迁移、结构化问题编辑或真实批量初始化。接口与命令参见 progress.md。

## 2026-10-10 独立HTTP/UI隔离阶段

新入口workbench_server.py/workbench_editor.html：回环127.0.0.1、默认只读、启动allow-write加逐书write-book白名单；网页init再次确认。未初始化GET不创建任何目录/锁。最新catalog只读扫描不落盘，永久身份仍为书内UUID而非展示目录名。

精确Host及Origin；POST要求同源Origin、随机进程CSRF自定义header和定长JSON≤65536字节。无CORS、no-store、无任意静态文件服务、无网页退出接口。读写复用BookStore，400/403/409/500分开；错误及响应丢失不冒称成功。冲突保留编辑输入、刷新SHA256/revision基线，明确提示用户核对后重新点击，不自动覆盖。

UI包含书/单位/总结范围选择、四阶段/疑点/结论、当前位置/计划、总结依据及备份恢复确认。有限真实fixture上的HTTP安全/故障注入与jsdom真实HTTP交互，不初始化真实八书，不修改真实笔记数据，不引入云后端。真实文件hash前后验证；探针finally收尾仅终止自己创建的服务。

## 2026-10-10 请求级读取性能优化

书名授权校验使用实时轻量入口发现，拒绝越过书架的链接；不以全量正文扫描作为每个详情请求的前置。GET 的 BookStore 仅存本次请求目录及多值 review 索引，POST 不共享读快照，任何写操作进入书锁后清空快照并执行 fresh 目录与版本核对。普通直接 BookStore 默认不缓存，无全局长生命周期缓存。

readonly 每单位 TeX 读取一次 bytes 供内容/SHA256/TODO，共享按单位多值 review 索引但保留全部冲突；record 行为不变。详情 review/summary 行和 hash 同 bytes，避免返回旧行搭配外编辑新 hash。一次请求不是整个书目录的原子文件系统快照；不承诺抵抗恶意并发链接替换或外编辑遵守 advisory 锁。真实只读 A/B 必须剔除 snapshot_at 后全量相同，性能以实际执行 old/new 记录为准。

## 2026-10-10 首页导航与审计分离

首屏 `/navigation` 只提供实时登记导航和标题/冲突，不加载完整正文/record，也不产生审核状态或完成依据。全量按钮单独请求 `/data`，成功仅标现行登记绑定扫描完成；失败清除旧结果，刷新导航使旧审计过期。导航刷新重取书/单位/范围列表，同书输入保留。错误登记路径、重复入口及越界书链接失败关闭；写锁内 fresh 校验不降级。完整扫描不是全书原目录或数学核验，也不是已保存 basis 的全量审计。
