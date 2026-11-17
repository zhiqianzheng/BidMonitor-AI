# 全国招投标网站普查进度

更新：2026-11-16T15:08:33+00:00

状态：**普查进行中，未证明找全，已有快照导入工作台，详见 [导入回执](IMPORT.md)。**

当前 18,186 个去重入口，涉及 13,724 个主机。入口数不等于独立机构数，同一统一平台的栏目、地区入口会保留但分开统计。

核验状态：

- reachable_needs_review：8,982
- blocked：634
- notice_links_found：5,914
- request_failed：926
- http_error：1,207
- pending：512
- parked_or_closed：11

`notice_links_found` 只表示网页中发现公告形式的链接，仍需核对主办方与采购栏目；`reachable_needs_review` 只表示可访问，导入后仍需定位采购栏目，不能当作公告采集成功。网络失败、拦截、失效均单列，不算成功。

- [候选名录 CSV](candidates.csv)：名称、网址、地区、行业、类型、层级、访问结果、依据。
- [完整证据 JSON](candidates.json)：每项保留所有来源网页和发现时间。
- [地市×类型查漏表](city-type-checklist.csv)及[20行业门类查漏表](industry20-checklist.csv)。
- [域名主机去重汇总](hosts.csv)和[排除记录](excluded-links.csv)。
- [方法、证据和未完成事项](METHOD.md)。
- [省份×行业缺口表](province-sector-gaps.csv)：不能以某格非零作为完成标记。
- [机器可读进度](progress.json)。

全国全量网站没有可据以证明完备的单一名册；目录有遗漏、旧域名、动态页面。历史登记只作为线索。层级和行业为自动推断，标记为待核实；“全国/待核实”地区条目不摊派到31省，不虚增覆盖率。
