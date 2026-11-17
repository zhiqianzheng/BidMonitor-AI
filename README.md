# BidMonitor AI · 应用与代码导航

`main` 中按应用维护代码。**找桌面版进入 `apps/desktop/`；找团队工作台进入 `apps/workbench/`。** 原始归档通过 Git 标签保留，不以版本号目录重复堆放源码。

| 应用 | 状态 | 唯一业务代码位置 | 启动命令 |
| --- | --- | --- | --- |
| 原版桌面修复版 1.7.6 | 维护中 | [`apps/desktop/bidmonitor_desktop`](apps/desktop/bidmonitor_desktop) | `python run_original.py` |
| 团队工作台 2.0 维护线 | 维护中 | [`apps/workbench/bidmonitor_workbench`](apps/workbench/bidmonitor_workbench) | `python run_workbench.py` |
| 历史 Web 后台 | 兼容保留 | [`apps/legacy_web/bidmonitor_legacy_web`](apps/legacy_web/bidmonitor_legacy_web) | 旧入口 `server/app.py`，默认 8080 |
| 未经维护的原始 1.7 | 只读归档 | [`v1.7-original`](https://github.com/zhiqianzheng/BidMonitor-AI/tree/v1.7-original) 标签 | 单独克隆归档标签运行 |

## 目录说明

```text
apps/
  desktop/bidmonitor_desktop/
    gui.py                    桌面界面
    monitor_core.py           桌面监控调度与处理
    ai_api.py、ai_guard.py     模型发现、调用检测、AI筛选
    crawler/                  桌面来源适配
    storage/                  桌面SQLite数据存储
    notifier/                 邮件、短信、微信、语音
    paths.py                  桌面私有数据路径
  workbench/bidmonitor_workbench/
    api.py                    工作台HTTP接口
    collectors/               全国与省级来源采集
    storage/                  项目、线索、分类、截止状态
    web/                      工作台页面与静态资源
    paths.py                  工作台私有数据路径
  legacy_web/bidmonitor_legacy_web/
    app.py                    历史Web接口
    core/                     历史后台所需的冻结实现
    web/                      历史页面
run.py、run_original.py        桌面兼容启动命令
run_workbench.py              工作台兼容启动命令
original_desktop/run.py        更早的桌面兼容命令
server/                       历史部署资料、依赖清单和薄兼容入口
runtime/                      新安装的配置、数据库、日志；运行时生成，不提交
```

原先混在根 `src/`、`server/` 里的业务实现已按归属迁入上述应用目录。`server/app.py` 和 `server/workbench_app.py` 仅保留兼容导出，修改功能时应进入实际应用包。`original_desktop/` 不再保存另一套桌面业务源码。

本轮只整理应用边界、导入、路径与入口，保留各版业务行为；没有强行合并两版的采集器。`legacy_web/core/` 是历史后台兼容实现，不能把它当作桌面维护版或工作台的修改入口。

## 安装

推荐带 Tkinter 的 Python 3.10 或更高版本。Windows PowerShell：

```powershell
git clone https://github.com/zhiqianzheng/BidMonitor-AI.git
cd BidMonitor-AI
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r server/requirements.txt
```

只运行桌面版时可只安装根目录依赖；浏览器模式另外需要 `selenium`、`webdriver-manager` 和本机 Google Chrome。部分省级公开接口的解析需要 `cryptography`：

```powershell
.\.venv\Scripts\python.exe -m pip install selenium webdriver-manager cryptography
```

依赖清单本轮保留原位置；`server/requirements.txt` 中的 Web 和浏览器依赖也供工作台使用。短信、语音等服务还需安装对应 SDK 并配置自己的账号。

## 启动与功能

桌面维护版：

```powershell
.\.venv\Scripts\python.exe run_original.py
# 旧命令 python run.py 和 python original_desktop/run.py 仍可使用
# 也可使用包入口：python -m apps.desktop.bidmonitor_desktop
```

支持自定义网站、普通/浏览器采集、AI模型列表与实际调用检测、历史结果查询和CSV导出、规则预览及通知重试。至少启用一个有效来源；填写 AI 信息本身不会配置采集来源。模型列表不保证每个模型都有调用权限，调用检测可能消耗接口额度。

团队工作台：

```powershell
.\.venv\Scripts\python.exe run_workbench.py
# 可选：--no-browser --port 8766
# 包入口：python -m apps.workbench.bidmonitor_workbench
```

默认访问 <http://127.0.0.1:8765>。支持标题搜索、公告类型多选、与已有条件同时满足的关键词二次筛选、负责人和销售线索跟进、来源状态及定时更新。工作台仅收录标题、原始 URL 和公告发布时间，保留来源及分类用于筛选；不再提取正文，不展示截止时间、预算或招标单位。CSV 导出仅包含标题、原始 URL、公告发布时间三列。中标、成交及合同验收等结果类公告不再入库，已有结果记录保留但不显示在公告搜索中。遇到访问限制或安全验证时自动停用来源，可在来源页手动重新启用。服务进程停止后不会继续采集；默认入口是本机工作台，不等于已部署多人公网服务。

历史 Web 后台：旧 `server/start.sh`、`server/setup.sh` 和服务文件继续指向兼容入口，运行的是历史 8080 后台，**不会启动 8765 团队工作台**。`server/README.md` 和 `server/DEPLOY.md` 是这套历史服务的资料。新开发和新部署应先选择所需应用，不要混用历史后台说明。

## 工作台来源库与覆盖验证

来源不按行业限制：包含全国、省市公共资源及政府采购、央企国企、市场化交易平台、代理机构、高校科研、医疗、金融、交通、能源、制造、农业、服务业等入口。跨行业目录保存在 `apps/workbench/bidmonitor_workbench/collectors/extra_sources.json`，每条保留网址出处。集团首页属于待识别入口，不能算已接通采购列表。辅助行业分类、网站数、频道数、实际入库数据、待适配及受限状态在“数据与成员”分别展示；同站跨行业会重复出现在行业统计中。

采集时会从公开导航中发现关联采购平台，保留发现页面、去重入库并接续验证；每轮最多扩展两层，后续定时更新继续推进。新增来源自动加入采集，优先核验新入口；反爬受限来源自动停用；同站多个频道重复限制访问时整体停用该站点，新发现的同站入口也会跳过。手动启用来源或单独重试会清除该站点的跳过记录。固定目录和动态发现均无法证明全国全部网站已经找全，不能将目录数量当作完整率。

也可通过页面上传 UTF-8 CSV 或粘贴 `名称,网址,地区,类别`，单批最多 10000 条；网址按主机、路径、查询参数及有意义的路由去重，导入后保存在工作台数据库，重启后继续使用。静态列表会识别栏目及下一页；动态接口未适配、日期不明或响应异常时明确报告，不作为成功采集。

维护目录和独立核验脚本（均只访问公开页面，不执行下载的 JavaScript）：

```bash
uv pip install --python .venv/bin/python -r scripts/requirements.txt
PYTHONPATH=. .venv/bin/python scripts/refresh_source_directory.py
.venv/bin/python scripts/discover_etrading_sources.py
PYTHONPATH=. .venv/bin/python scripts/verify_source_catalogue.py
```

核验结果保存在正常工作台的来源状态中，JSON 报告位于 `runtime/workbench/`。核验脚本直接写入本机工作台数据库，包含实际采集的公告；避免与页面采集同时执行。目录发现脚本的候选 JSON 仍需去重并入维护目录，不能将候选当作成功来源。支持公开网页的自定义端口，采集时仍拒绝本机或内网地址。

### 行业与来源联动

标讯搜索的“来源行业”和来源页的“采购主体行业”会同时约束来源选项、来源列表、搜索结果、导出和新发起的采集。搜索页和来源管理页的行业选择双向同步。切换行业会自动清除不匹配的原来源；选择“全部行业”恢复完整范围。来源页的采集按钮处理当前完整筛选结果，不局限于已展开的前 50 条。

来源行业以网站所属行业为准；例如能源网站发布的软件采购也属于能源网站范围。卡片上的“项目方向”仍是公告标题的辅助分类。人工录入项目按手动填写的行业归类保留。行业名与来源细分标签的映射统一维护在 `collectors/sectors.py`，前端和接口共用，不为单个行业另外编写筛选逻辑。

已经启动的后台任务保留原范围，页面显示其范围；界面筛选不会修改全库来源的启用状态或定时更新计划。新增关联网站可保存到全库，但行业限定任务只追采符合该行业的来源。没有匹配来源时返回明确的空范围，不会退回全网采集。

## 配置与数据库位置

程序使用明确路径，不再靠修改进程工作目录或 `sys.path` 来选择版本。不会自动移动、复制或覆盖已有私人配置、数据库。

| 应用 | 新安装默认目录 | 兼容原有数据 | 显式覆盖 |
| --- | --- | --- | --- |
| 桌面版 | `runtime/desktop/` | `original_desktop/` 下已有 JSON、YAML、数据库或日志时继续使用该目录 | `BIDMONITOR_DESKTOP_HOME` |
| 工作台 | `runtime/workbench/` | 根目录已有 `data/bids.db` 时继续使用根目录数据 | `BIDMONITOR_WORKBENCH_HOME`；数据库路径可用 `BIDMONITOR_DB` |
| 历史 Web | `runtime/legacy_web/` | 已有根目录数据库或 `server/server_config.json` 时保留历史路径 | `BIDMONITOR_LEGACY_HOME`、`BIDMONITOR_LEGACY_DB` |

- 桌面 JSON 为所选目录的 `user_config.json`，YAML 为 `config/config.yaml`，数据库为 `data/bids.db`；不会读取工作台的父目录配置。
- 工作台显式传入的数据库路径优先；其次是 `BIDMONITOR_DB`，再根据所选运行目录确定路径。
- 显式运行目录环境变量优先于旧目录识别。启动程序前设置变量，不要在运行中切换路径。
- 历史 Web 为兼容旧安装可能沿用根目录数据库；若与工作台并行使用，先为历史 Web 指定独立目录，避免两个服务写同一个旧库。迁移数据应另做备份与验证，本轮不会擅自迁移。
- `runtime/`、私人配置、数据库和日志不提交到 Git。转发源码或发布包时，也应排除这些数据和访问凭据。

桌面设置在开始检索、启动监控和保存网站配置等操作时写入本机；仅填写并测试 API 不等于已经保存全部设置。运行中修改规则或来源后，停止再启动才能应用新的本轮配置。

## 版本与维护方式

- `main` 是当前应用布局和日常开发基线，按应用目录修改，经独立功能分支和 PR 合入。
- `maintenance/original-v1.7` 保留旧布局的桌面维护线；不与 main 的新包布局自动同步，需要修补时明确目标，不能只修其中一份却宣称两边已更新。
- `v1.7-original` 和现有工作台标签保留历史状态。需要历史代码时按标签克隆，不在 main 中新增 `v1.7.6/`、`v2.0/` 等复制目录。
- 目录重组不会更新已安装程序或免安装包。Windows包需单独构建、排除私人数据并实际启动验证。

## 覆盖范围

来源已登记不等于当前采集成功，也不保证覆盖全部栏目、分页和历史数据。浏览器模式可读取动态内容，不能保证处理登录、验证码或会员限制；访问失败和部分采集会报告状态。字段提取以来源公开内容为基础，未知值不代表已核实，最终以原文为准。

采用 [MIT License](https://opensource.org/license/mit/)。报告问题时请注明应用名、版本/提交、入口和脱敏操作记录。
