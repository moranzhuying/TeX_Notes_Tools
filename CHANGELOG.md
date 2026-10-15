# 变更记录

## 2026-10-15 · new_note 可选建导引与小结

- `new_note.py` 新增 `--intro` / `--summary`，按大纲生成骨架时一并建导引与小结（**默认都不带**，交互式引导会问一句：`y` 都建 / `i` 只建导引 / `s` 只建小结）。规则照 Math-Note 模板的既有约定：最外层建 `intro.tex`（无编号标题 ＋ `\phantomsection` ＋ `\addcontentsline`，手工进目录），所有会产生目录的层建 `Summary/`（`index.tex` ＋ `intro.tex` ＋ `01_summary.tex`）；小结自己占下一级的编号标题，内部导引与条目再降一级（带 `*` 与不带 `*` 区分），所以节的小结用到 `\subsubsection`。导引只加在最外层，末层是 `.tex` 文件、不加小结。
- 对应的 `\input` 插进该层 `index.tex`：导引在第一条 `\input` 之前（开头的注释行留在最上面），小结在附录之前（没有附录就接在最后一条 `\input` 之后）；已存在的那一行不重复插。新文件里只留一行 `%` 注释写「这一节该写什么」，不写正文占位句。
- `note_tools.py` 新增「补导引与小结」（面板选项 7 内，单本），对**已有笔记**做同样的事：扫描 `Content/` 现有结构、按 `main.tex` 与正文里出现过的命令推断层级，先给「将新建几个文件、改动几个 index.tex」的清单、确认后才写入，只补缺、不覆盖，可反复跑。实现直接复用 `new_note.py`，不另写一份规则。
- 已有八本笔记按此补全：新建 1161 个文件、改动 425 个 index.tex（层级推断：七本为 `chapter, section, subsection`，「节即叶子」的 Algebraic_Topology 为 `chapter, section`）；General_Topology 编译通过（23 页）。执行明细见 `outputs/intro-summary-补全记录-2026-10-15.md`。
- 文档同步：`README.md`（new_note 用法与新增「导引与小结」一节、note_tools 一节）、`new_note/new_note.md`、`launcher.py` 面板文字。

## 2026-10-15 · 删除旧版写作追踪表

- 删除旧版写作进度追踪表的全部文件：`progress.py`、`progress_ui.html`、`progress.conf(.example)`、`progress_marks.json(+.bak)`、`progress_settings.json(+.bak)`、`progress_report.md`，以及退役拒绝入口 `workbench_legacy.py`；`progress/` 下只保留工作台（总面板选项 4）。
- 同步清理文档中的旧版章节：`README.md`、`progress.md`、`progress_design.md`、`launcher.py` 注释与 `.gitignore` 规则；旧版使用说明与设计正文不再保留。
- 测试相应调整：删除 `test_legacy_retired.py`，从 `test_multi_permission_legacy.py`、`test_retirement_independent.py` 移除依赖旧模块的用例；其余「旧名不得出现」的守卫测试保留。
- 连残留旧数据一并清空：书内 `Materials/workbench/legacy` 归档（Algebra、General_Topology 两本）与本机 `progress/._data` 退役声明删除；全量测试无新增回归（唯一失败项与改动前一致，为环境缺 jsdom 所致）。

## 2026-10-14 · PDF独立标签页备用路线

- 新增用户显式点击的独立标签页PDF备用按钮；只有完整已验证Blob加载后启用，目标重置禁用，以noopener打开并携带目标页码，不自动打开、下载或修改PDF与后端。
- 普通Edge独立临时profile实际验收：独立HTTP、独立Blob及产品按钮真实点击均PASS，已核对第一/第二页画布与页码。
- 已知限制：嵌入Blob及直接HTTP iframe仍灰屏、UNVERIFIED；整体PARTIAL/UNVERIFIED，根因未确认，不宣称全部PDF修复。产品与有界诊断测试冻结，不继续猜测性修改阅读器。

## 2026-10-13 · 工作台保存许可与发布边界

- 核验本机既有八书的独立永久ID与许可根；正式启动面板只读GET确认八书可写导航及已初始化运行时基线，正式页面保存判定通过Node VM验证。未对真实书执行初始化、保存或恢复，不将条件验证称为浏览器逐书试写。
- 保存许可仍属本机配置，不随公开代码分发；新配置默认只读，换根清空许可，allow-open保持独立授权，已有永久ID不变。
- 旧工作台入口与旧标记迁移保持退役，历史源数据与证据留存，不重新迁移、认领或改变审核结论。
- 本轮发布仅提交与推送现有main；不创建tag、Release或PR，不提交真实书数据、本机配置、输出证据及其它工具未提交改动。
