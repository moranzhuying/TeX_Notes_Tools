# 变更记录

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
