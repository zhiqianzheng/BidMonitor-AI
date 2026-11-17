# 全国招投标网站普查方法与交付边界

普查程序只查找、去重、核对网站名录，写入独立的 `runtime/source-census/census.sqlite3`。根据用户后续的明确导入指示，现已将当前快照合并至工作台，详见 [导入结果](IMPORT.md)。公告采集与定时扩源保持关闭，导入不会自行启动采集。全国完备性仍未证明。

## 范围

- 国家、省、地市、区县；省级统一平台的城市/区县入口单独记录归属，不能按独立网站重复计数。
- 政府采购信息发布、公共资源交易、依法必招公告发布、各部门采购、央国企及地方企业自采、高校科研、医疗与药械、金融采购、社会代理及第三方平台、小额工程与阳光采购、农村集体与产权交易。
- 行业查漏采用国民经济行业分类的20个门类，另保留工作台细分行业标签。名称匹配只形成待核线索，不能当作已审定行业或全覆盖。

## 正在使用的证据

| 证据入口 | 用途和限制 |
| --- | --- |
| [中国政府采购网](https://www.ccgp.gov.cn/) | 中央与地方分网、官方发布入口；访问拦截保留失败结果 |
| [全国公共资源交易平台导航](https://www.ggzy.gov.cn/platform/platform.html) | 全国平台目录；动态或不可访问部分不算已查完 |
| [中国招标投标公共服务平台](https://www.cebpubservice.com/) | 招标公告发布与交易平台线索 |
| [新点官方目录](https://www.etrading.cn/) | 四类平台、A–Z共104份公开目录文件逐份核对 |
| [广东省招标投标协会社会交易平台](https://www.gtba.org.cn/site/socialPlatForm/index) | 协会公布的具体平台链接 |
| [云南公共资源交易官方前端导航](https://ggzy.yn.gov.cn/) | 读取其公开脚本中城市名称、地区代码和跳转模板，保留16个城市共享入口的证据；不执行下载脚本，不推测未发布地址 |
| [公采汇公开站点地图](https://www.procdata.cn/site-map) | 已按服务端返回的分页规模遍历227页、11,335条原始目录记录；包含机构官网、第三方名录及旧地址，全部先作候选，不等于11,335个有效招标源 |
| [标讯导航](https://biaoxun.vip/nav/)、[投标人导航](https://www.tbrdh.com/)、[招采导航](https://jetbid.cn/navigation.html) | 跨行业补充线索，需官方站点核实 |
| [逐城市平台入口索引](https://www.getbidwin.cn/zhaobiao-wangzhan-daohang.html) | 相邻城市标签与明确的官网链接配对，只作线索，不接受第三方的“全部已核验”说法 |
| 各来源站点的友情链接、地区选择器、采购栏目 | 继续扩展到未出现的新平台；仅有限深度追踪导航，不批量下载公告正文 |

每项候选保留网址、名称、发现依据页、发现时间、访问时间、HTTP结果、重定向地址、页面标题、页面SHA-256。发现公告形式链接也只是机器核验线索，仍要检查主办方、栏目性质和更新情况。

## 防止虚增数量

1. HTTP/HTTPS、www别名按相同身份合并，保留所有依据。不同SPA城市路由保留，但额外提供按域名主机汇总的 `hosts.csv`。
2. 千里马等商业聚合站的地区页、行业页，以及社交平台、学校名录页不当作独立采购网站；排除原因另存 `excluded-links.csv`，原证据不丢弃。
3. 不用拼音猜域名。动态地区入口只有在官方公开脚本确实发布了名称、代码与模板时才整理，并明确标成共享入口。
4. 企业/学校官网可能没有采购栏目，只能放候选表，不能凭能打开网页就算有效招标源。
5. 403、验证码、证书错误、404、停站等单列。访问失败不表示该网站一定不存在，也不算核验成功。

## 查漏表与尚未完成的事项

- `city-type-checklist.csv`：以333个地级单位加4个直辖市的**2023年参考基线**建立类型清单。基线来自[开源区划数据](https://github.com/modood/Administrative-divisions-of-China)，已注明来源与日期；它不是2026年最新官方区划，仍需校对变更并补充直辖县市、兵团、港澳台等范围。
- `industry20-checklist.csv`：20门类×地区的候选计数，零项和非零项都需要继续核查。[分类依据](https://www.stats.gov.cn/zs/tjws/tjbz/202301/t20230101_1903769.html)。
- `province-sector-gaps.csv`：工作台细分行业维度的线索表。
- `search-checklist.json`：待执行检索任务；生成查询词不算已检索，更不算找到网站。
- 企业、代理机构、高校、医疗、社会组织等还需逐机构清单核对；单个导航站或几份目录都不能证明全国完备。
- 动态页面仍需适配/浏览器核验；机构主页需定位到实际采购公告栏目；旧址与新址需确认迁移关系。

## 可恢复的运行方式

在项目根目录使用虚拟环境Python，设置 `PYTHONPATH=.`：

```bash
.venv/bin/python scripts/census_tender_sites.py seed
.venv/bin/python scripts/census_tender_sites.py directories
.venv/bin/python scripts/census_supplement.py
.venv/bin/python scripts/census_dynamic_directories.py
.venv/bin/python scripts/census_city_navigation.py
.venv/bin/python scripts/census_tender_sites.py verify --workers 16
.venv/bin/python scripts/census_coverage.py
```

研究文件的 `complete` 仍为 `false`；`imported` 表示已有快照执行过导入，具体时间和数量以 [导入回执](import-receipt.json) 为准，不表示全国网站已经找全。离线导入程序 `scripts/import_census_sources.py` 支持只读预检、数据库备份、去重合并与保留原有采集状态；当前名录仍需继续复核。

网页重定向中出现的密钥、签名、令牌及过期时间参数在公开快照中移除；保留可公开使用的网站路由参数。
