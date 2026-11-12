"""Public source catalogue. Registration is not evidence of successful ingestion."""

# Government links: https://www.ccgp.gov.cn/ (地方分网).
# Trading links: https://www.ggzyzx.jl.gov.cn/kzgn/wzdt/ and provincial portals.
# Direct provincial feeds and national supplements have separate identities/health.
PROVINCES = (
    ('11', '北京', 'beijing', 'https://ggzyfw.beijing.gov.cn/'),
    ('12', '天津', 'tianjin', 'http://ggzy.zwfwb.tj.gov.cn/'),
    ('13', '河北', 'hebei', 'https://szj.hebei.gov.cn/hbggfwpt/'),
    ('14', '山西', 'shanxi', 'http://prec.sxzwfw.gov.cn/'),
    ('15', '内蒙古', 'neimenggu', 'http://ggzyjy.nmg.gov.cn/'),
    ('21', '辽宁', 'liaoning', 'http://www.lnggzy.gov.cn/lnggzy/'),
    ('22', '吉林', 'jilin', 'http://www.jl.gov.cn/ggzy/'),
    ('23', '黑龙江', 'heilongj', 'http://ggzyjyw.hlj.gov.cn/'),
    ('31', '上海', 'shanghai', 'https://www.shggzy.com/'),
    ('32', '江苏', 'jiangsu', 'http://jsggzy.jszwfw.gov.cn/'),
    ('33', '浙江', 'zhejiang', 'https://ggzy.zj.gov.cn/'),
    ('34', '安徽', 'anhui', 'http://ggzy.ah.gov.cn/'),
    ('35', '福建', 'fujian', 'https://ggzyfw.fujian.gov.cn/'),
    ('36', '江西', 'jiangxi', 'https://www.jxsggzy.cn/'),
    ('37', '山东', 'shandong', 'http://ggzyjy.shandong.gov.cn/'),
    ('41', '河南', 'henan', 'http://ggzy.fgw.henan.gov.cn/'),
    ('42', '湖北', 'hubei', 'https://www.hbggzyfwpt.cn/jyxx/index?pageSize=9'),
    ('43', '湖南', 'hunan', 'https://www.hnsggzy.com/'),
    ('44', '广东', 'guangdong', 'https://ygp.gdzwfw.gov.cn/ggzy-portal/#/44/index'),
    ('45', '广西', 'guangxi', 'http://gxggzy.gxzf.gov.cn/'),
    ('46', '海南', 'hainan', 'https://ggzy.hainan.gov.cn/ggzy/'),
    ('50', '重庆', 'chongqing', 'https://www.cqggzy.com/'),
    ('51', '四川', 'sichuan', 'http://ggzyjy.sc.gov.cn/'),
    ('52', '贵州', 'guizhou', 'http://ggzy.guizhou.gov.cn/'),
    ('53', '云南', 'yunnan', 'http://ggzy.yn.gov.cn/'),
    ('54', '西藏', 'xizang', 'http://ggzy.xizang.gov.cn/'),
    ('61', '陕西', 'shaanxi', 'http://www.sxggzyjy.cn/'),
    ('62', '甘肃', 'gansu', 'http://ggzyjy.gansu.gov.cn/'),
    ('63', '青海', 'qinghai', 'http://www.qhggzyjy.gov.cn/ggzy/'),
    ('64', '宁夏', 'ningxia', 'https://ggzyjy.fzggw.nx.gov.cn/'),
    ('65', '新疆', 'xinjiang', 'https://ggzy.xinjiang.gov.cn/'),
)

ENTERPRISES = (
    ('ceec', '中国能建电子采购平台', 'https://ec.ceec.net.cn/'),
    ('powerchina', '中国电建采购招标平台', 'https://bid.powerchina.cn/bidweb/'),
    ('sgcc', '国家电网电子商务平台', 'https://ecp.sgcc.com.cn/'),
    ('csg', '南方电网供应链统一服务平台', 'https://www.bidding.csg.cn/'),
    ('chng', '华能集团电子商务平台', 'https://ec.chng.com.cn/'),
    ('crc', '华润集团守正电子招标采购平台', 'https://szecp.crc.com.cn/'),
    ('ctg', '中国三峡电子采购平台', 'https://eps.ctg.com.cn/'),
    ('cecep', '中国节能电子采购平台', 'https://www.ebidding.cecep.cn/'),
    ('cnpc', '中国石油招标投标网', 'https://www.cnpcbidding.com/'),
    ('sinopec', '中国石化建设工程电子招标平台', 'https://ebidding.sinopec.com/'),
    ('cmcc', '中国移动采购与招标网', 'https://b2b.10086.cn/'),
    ('unicom', '中国联通采购与招标网', 'https://www.chinaunicombidding.cn/'),
    ('telecom', '中国电信阳光采购网', 'https://caigou.chinatelecom.com.cn/'),
    ('crcc', '铁建云链', 'https://www.crccep.cn/'),
    ('cscec', '中国建筑云筑网', 'https://www.yzw.cn/'),
    ('cccc', '中交集团供应链管理系统', 'https://ec.ccccltd.cn/'),
    ('minmetals', '中国五矿集团供应链管理平台', 'https://ec.minmetals.com.cn/'),
    ('cnbm', '中国建材集团采购平台', 'https://c.cnbm.com.cn/'),
    ('faw', '中国一汽电子招标采购交易平台', 'https://srm.etp.faw.cn/'),
    ('sdic', '国投集团电子采购平台', 'https://www.sdicc.com.cn/'),
)


def catalogue():
    rows = [dict(id='ccgp', name='中国政府采购网 · 中央及地方', kind='政府采购',
                 province='全国', url='https://www.ccgp.gov.cn/cggg/dfgg/index.htm',
                 adapter='ccgp', channel='国家主网直采', scope='中央及地方公开公告；按栏目分页')]
    for code, name, slug, trading in PROVINCES:
        procurement = f'http://www.ccgp-{slug}.gov.cn/'
        if slug in ('hainan', 'jiangxi'):
            procurement = f'https://ccgp-{slug}.gov.cn/'
        elif slug == 'guangdong':
            procurement = 'https://www.ccgp-guangdong.gov.cn/'
        rows.append(dict(id=f'gov-{code}', name=f'{name}政府采购网', kind='政府采购',
                         province=name, url=procurement, adapter='html', channel='省站直采',
                         scope='公开列表；动态页面需独立适配，采集状态以实测为准'))
        if code not in ('32', '42'):
            rows[-1].update(adapter='national', province_code=code+'0000', deal_classify='02',
                            channel='全国平台汇聚', feed_url='https://www.ggzy.gov.cn/deal/dealList.html',
                            scope='省站已登记；当前通过全国平台政府采购分频道获取本省公告，非省站直连或全量')
        rows.append(dict(id=f'trade-{code}', name=f'{name}公共资源交易', kind='公共资源',
                         province=name, province_code=code+'0000', url=trading,
                         adapter='national', channel='全国平台汇聚',
                         feed_url='https://www.ggzy.gov.cn/deal/dealList.html?DEAL_PROVINCE='+code+'0000',
                         scope='全国平台已汇聚的本省交易公告；含工程、采购、土地、产权等；非省站全量'))
    for key, name, url in ENTERPRISES:
        rows.append(dict(id=key, name=name, kind='企业招标', province='全国', url=url,
                         adapter=key if key in ('ceec', 'crcc', 'cnbm') else 'html', channel='企业直采',
                         scope='公开公告列表；登录后或未公开的数据不采集'))
        if key in ENTERPRISE_FEEDS:
            rows[-1].update(adapter='national', source_type='2', bid_platform=ENTERPRISE_FEEDS[key],
                            channel='全国平台汇聚', feed_url='https://www.ggzy.gov.cn/deal/dealList.html',
                            scope='全国平台已汇聚的该企业公开公告，非企业站直连或全量')
    from .provincial import direct_sources
    rows.extend(direct_sources(rows))
    return rows


# Platform IDs published by https://www.ggzy.gov.cn/data/platform.js.
ENTERPRISE_FEEDS = {'powerchina': 'D1101080711,91110000717825966F',
 'sgcc': 'D1100000001,D1100000002,D1100000003,91110000710922296C,91110000710922296C-1,91110000710922296C-2',
 'chng': 'D1100000028,91130100721612218G',
 'crc': 'D4403030148,914403003426144591',
 'cecep': 'D1101080855,91110000100010310K',
 'cnpc': 'B1100000010,91110102600087445F',
 'sinopec': 'B1100000013,91110000710931731K',
 'cmcc': 'I1100000073,91110000717851160R',
 'unicom': 'I1100000727,91110000710939135P',
 'telecom': 'I1100000755,91110000100017707H',
 'cscec': 'E5101000890,915101053320852827',
 'cccc': 'E1100000179,911100004008344000-1',
 'minmetals': 'E1100000879,9111000010000093XR',
 'faw': 'C2201000275,91220101735930559D',
 'sdic': 'L1100000165,91110000710932216U'}
