"""Source coverage labels, separate from the industry of individual projects."""
import re

# A broad public-resource feed is not counted as every specialist industry.
SECTORS = ('综合采购', '电力新能源', '煤炭矿业', '石油化工', '交通运输', '医疗卫生', '教育科研',
           '金融保险', '建筑市政', '水利水务', '电子通信', '航空航天', '汽车制造', '钢铁冶金',
           '机械装备', '生态环保', '农林牧渔', '文体旅游', '商业服务', '物流贸易', '纺织轻工',
           '食品烟草', '国际招标', '产权交易', '公共安全', '行政办公', '其他行业')
RULES = (
    ('公共安全', r'公安|警察|消防|应急|安防|保安|监狱|政法|司法|军队|兵器|兵工|兵装|融通'),
    ('行政办公', r'机关|政务|政府办公|事务管理|人大|政协|税务|海关|外交部|中央政府采购|中共中央直属|人民法院|检察院'),
    ('电力新能源', r'电力|电网|电投|电建|能建|华能|华电|大唐|国能|国家能源|能源|浙能|皖能|京能|深能|申能|粤电|核电|中核|中广核|水电|风电|光伏|储能|发电|热电|热力|电气|南瑞|许继|平高|东方电气|哈尔滨电气'),
    ('煤炭矿业', r'煤|矿业|矿产|有色|铝业|铜业|冶金|金属|黄金|五矿|地质'),
    ('石油化工', r'石油|石化|化工|化学|中化|化建|燃气|管网|橡胶'),
    ('交通运输', r'交通|交投|交控|铁道|中铁|铁路|国铁|铁建|公路|高速|港口|港务|航运|机场|航空公司|南航|国航|东航|海事|地铁|轨道|中交|路桥'),
    ('医疗卫生', r'医院|卫生|医疗|医药|药品|药械|医保|疾控|血液|健康|妇幼'),
    ('教育科研', r'大学|学院|学校|教育|科研|研究院|科学院|实验室|技工'),
    ('金融保险', r'银行|保险|证券|信托|金融|资产管理|融资|投资控股'),
    ('建筑市政', r'建筑|城建|市政|建设|建工|城投|置业|地产|建材|水泥'),
    ('水利水务', r'水利|水务|供水|自来水|南水北调|水投|水运'),
    ('电子通信', r'电子科技|电子信息|电子集团|中国电子|通信|电信|移动|联通|广电|广播|网络科技|信息技术|信息产业|数据集团|软件|电科|华录'),
    ('航空航天', r'航空|航天|航发|飞机|卫星|空天|商飞'),
    ('汽车制造', r'汽车|一汽|二汽|东风|长安|上汽|广汽|重汽|北汽'),
    ('钢铁冶金', r'钢铁|钢材|宝武|宝钢|鞍钢|武钢|首钢|河钢|太钢|铸造|中钢|冶金|冶炼'),
    ('机械装备', r'机械|重工|装备|机床|机电|船舶|兵器|中车|通用技术|中机'),
    ('生态环保', r'环保|环境|生态|节能|固废|污水|再生资源|园林'),
    ('农林牧渔', r'农业|农垦|农发|农投|林业|林场|森工|渔业|牧业|种业|种子|粮食'),
    ('文体旅游', r'文化|旅游|文旅|体育|传媒|出版|报业|酒店|宾馆|景区'),
    ('商业服务', r'商贸|物业|服务集团|商业|咨询|会计|法律'),
    ('物流贸易', r'物流|贸易|外贸|港航|货运|邮政|仓储|供应链'),
    ('纺织轻工', r'纺织|轻纺|恒天|中纺|轻工|服装|纤维|丝绸|造纸|家具|包装'),
    ('食品烟草', r'食品|烟草|中烟|烟叶|酒业|茅台|五粮液|食盐|中盐|粮油|中粮|乳业'),
    ('国际招标', r'国际招标|国际组织|世界银行|亚洲开发银行|联合国'),
    ('产权交易', r'产权|股权|资产交易|要素交易|土地交易|碳交易'),
)


def source_sectors(source):
    if source.get('kind') == '高校科研':
        return ['教育科研']
    if source.get('kind') == '医疗卫生':
        return ['医疗卫生']
    text = source['name'] + ' ' + source.get('sector_hint', '')
    result = [sector for sector, pattern in RULES if re.search(pattern, text)]
    if source.get('sector') in SECTORS and source['sector'] not in result:
        result.append(source['sector'])
    return result or ['综合采购' if source.get('kind', '行业平台') in ('政府采购', '公共资源', '综合招标', '招标代理') else '其他行业']

# Search industries and source specialisms use different names. One mapping is
# shared with the browser so displayed options, SQL results and collection agree.
INDUSTRY_SOURCE_SECTORS = {
    '建筑市政': ('建筑市政', '水利水务'),
    '交通运输': ('交通运输', '物流贸易'),
    '医疗卫生': ('医疗卫生',),
    '教育科研': ('教育科研',),
    '信息技术': ('电子通信',),
    '能源电力': ('电力新能源', '煤炭矿业', '石油化工'),
    '生态环保': ('生态环保', '水利水务'),
    '农林牧渔': ('农林牧渔', '食品烟草'),
    '机械制造': ('机械装备', '汽车制造', '钢铁冶金', '航空航天', '纺织轻工'),
    '文体旅游': ('文体旅游',),
    '金融保险': ('金融保险', '产权交易'),
    '公共安全': ('公共安全',),
    '行政办公': ('行政办公',),
    '商业服务': ('商业服务', '物流贸易'),
    '待分类': ('其他行业',),
}


def matches_industry(source, industry=''):
    if not industry:
        return True
    wanted = INDUSTRY_SOURCE_SECTORS.get(industry, (industry,))
    return bool(set(source.get('sectors') or source_sectors(source)).intersection(wanted))


def source_names(source):
    names = {source['name']}
    if source['id'] == 'ccgp':
        names.add('中国政府采购网')
    if source['adapter'] == 'national':
        names.add(source['name'] + '（全国平台汇聚）')
    return names
