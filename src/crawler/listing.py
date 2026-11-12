"""Common public-list parsing and access-error classification."""
import re
from urllib.parse import urljoin, urlsplit, parse_qs
from bs4 import BeautifulSoup
from .base import BidInfo


def is_notice_noise(title, url=''):
    """Recognize site navigation/admin content, not business keyword exclusions."""
    title = re.sub(r'\s+', '', str(title or ''))
    parsed = urlsplit(str(url or ''))
    path = parsed.path.lower()
    fragment = parsed.fragment.lower()
    # A platform homepage/category without a record identifier is not a notice.
    if not parsed.query and fragment in ('', '/', '/home', '/index', '/dashboard'):
        leaf = path.rstrip('/').rsplit('/', 1)[-1]
        if path in ('', '/') or leaf in {'index', 'index.html', 'index.htm', 'index.jhtml', 'home', 'home.html', 'portal'}:
            return True
    if re.search(r'会员(?:续费|续签|充值|权益|注册|服务)|加入.{0,20}会员|注册会员|用户服务协议|操作手册|用户指南|软件下载|平台登录|平台入口|寻源询价系统', title):
        return True
    if re.search(r'(?:平台|网站|系统)(?:临时)?(?:升级)?维护(?:完成)?(?:的)?(?:公告|通知)|平台临时升级维护|平台.{0,20}(?:收费细则|缴费公告|收费公告)|数字证书.{0,15}(?:收费细则|办理指南|办理流程)|(?:平台|系统).{0,10}(?:正式)?上线(?:的)?(?:通知|公告)', title):
        return True
    if re.search(r'采购从业人员.{0,15}注册|招标人代表注册|关于注册.{0,12}供应商.{0,12}资格条件.*通知|专家入驻|区块链应用区块链技术', title):
        return True
    if re.search(r'采购管理须知|平台.{0,15}投标实操培训.*通知|VIP会员购买|^招e通会员$', title, re.IGNORECASE):
        return True
    if re.search(r'/(?:login|register|signup|specialist|companyinfo|noticebulletin|xtgg|downtools)(?:[/.]|$)', path):
        return True
    if parsed.hostname in ('www.dlzb.com', 'dlzb.com') and path.startswith(('/announce/', '/about/')):
        # This section also contains genuine supplier recruitment notices.
        # Don't hide those merely because they share a path with site FAQs.
        opportunity = re.search(r'采购项目|招标公告|采购公告|(?:征集|招募|遴选).{0,20}(?:供应商|服务商|承包商|合作伙伴)', title)
        return not bool(opportunity)
    return False


def page_problem(html, url=''):
    soup = BeautifulSoup(html, 'lxml')
    title = soup.title.get_text(' ', strip=True) if soup.title else ''
    for tag in soup(['script', 'style', 'noscript']):
        tag.decompose()
    text = soup.get_text(' ', strip=True)
    if url.startswith(('chrome-error:', 'about:neterror')) or soup.select_one('#main-frame-error'):
        return 'network_error', 'Chrome网络错误页，未取得公告'
    signs = ['访问频繁', '请求过于频繁', '访问被拒绝', '请求已被阻断', 'access denied', '403 forbidden', '人机验证', '安全验证', '滑动验证', '访问验证', '请按住滑块', '请完成验证', '请输入验证码', '非法请求', '纳入黑名单', '不允许访问本网站', 'verify you are human', 'just a moment', 'checking your browser']
    lower = text.lower()
    if title.strip() in ('401', '403', '405', '429'):
        return 'blocked', f'站点返回访问限制页面（{title.strip()}），未取得公告'
    if any(s in title.lower() for s in signs) or (len(text) < 2000 and any(s in lower for s in signs)):
        return 'blocked', '页面要求验证或拒绝访问；需要人工确认，未作为正常空结果'
    if any(s in title.lower() for s in ['404 not found', 'page not available', '500 internal server', '502 bad gateway', '503 service', 'welcome to nginx', 'privacy error', '隐私设置错误', '页面不存在', '网站维护', '系统维护']):
        return 'site_error', title
    if not text.strip():
        return 'empty_page', '站点返回空页面，未取得公告'
    if (('登录' in title or 'sign in' in title.lower() or ('/login' in url.lower() and len(text) < 500)) and not parse_links(html, url, '')):
        return 'login_required', '该入口为登录页面，无法匿名获取公告'
    return None


def parse_links(html, base_url, source, generic=False):
    soup, bids, seen = BeautifulSoup(html, 'lxml'), [], set()
    base = soup.find('base', href=True)
    if base:
        base_url = urljoin(base_url, base['href'])
    if urlsplit(base_url).hostname == 'etp.faw.cn':
        for card in soup.select('.property-new-content-item[onclick]'):
            args = re.fullmatch(r"bgGgDetail\('([\w-]+)','(\d+)'\)", card['onclick'])
            # Mirror the observed public handler's GET branch. Type 7 uses an
            # encrypted form submission, so it needs separate support.
            if not args or args[2] == '7':
                continue
            heading = card.select_one('.property-new-text')
            date_node = card.select_one('.property-new-content-item-time-text')
            if heading:
                link = soup.new_tag('a', href='/gg/toGongGaoDetail?guid=' + args[1] + '&gongGaoType=' + args[2] + '&isNew=1')
                link.string = heading.get_text(' ', strip=True)
                link['data-published'] = date_node.get_text(' ', strip=True) if date_node else ''
                soup.append(link)
    for a in soup.select('a[href]'):
        href = a.get('href', '').strip()
        if urlsplit(base_url).hostname == 'www.chdtp.com':
            match = re.fullmatch(r"javascript:toGetContent\(['\"]([^'\"]+)['\"]\);?", href)
            if match:
                href = '/staticPage/' + match[1].lstrip('/')
        if not href or href.startswith('#') or href.lower().startswith(('javascript:', 'mailto:', 'tel:')):
            continue
        url = urljoin(base_url, href)
        if urlsplit(url).scheme.lower() not in ('http', 'https') or url in seen:
            continue
        title = a.get_text(' ', strip=True)
        tooltip = a.get('title', '').strip()
        parsed = urlsplit(url)
        ceec = parsed.hostname == 'ec.ceec.net.cn'
        ceec_detail = ceec and parsed.path.lower().rsplit('/', 1)[-1] in {'yugao_detail.aspx', 'zigeysgg_details.aspx', 'zhaobiaogg_details.aspx', 'projectdetail.aspx', 'windiddetails.aspx'}
        public_detail = ceec_detail or (
            parsed.hostname == 'new.ebidding.cecep.cn' and bool(re.fullmatch(r'/cgxx/\d+/\d+/\d{8}/[\w-]+\.html', parsed.path))
        ) or (
            parsed.hostname in ('www.szecp.com.cn', 'szecp.com.cn') and bool(re.fullmatch(r'/(?:first_[\w]+|gyszj_gys|zbjhgg)/\d{4}-\d{2}-\d{2}/\d+\.html', parsed.path))
        ) or (
            parsed.hostname == 'etp.faw.cn' and parsed.path == '/gg/toGongGaoDetail' and bool(parse_qs(parsed.query).get('guid'))
        )
        if not generic and parsed.hostname == 'new.ebidding.cecep.cn' and not public_detail:
            continue
        if not generic and parsed.hostname in ('www.szecp.com.cn', 'szecp.com.cn') and not public_detail:
            continue
        if not generic and ceec and not ceec_detail:
            continue
        if (len(tooltip) > len(title) or (parsed.hostname == 'etp.faw.cn' and tooltip)) and (not ceec or 'yugao_detail.aspx' not in url.lower()):
            title = re.split(r'\s*发布时间\s*[:：]', tooltip)[0].strip()
        if is_notice_noise(title, url) or a.find_parent(['nav', 'footer', 'header']):
            continue
        if len(title) < (4 if generic else (6 if public_detail else 10)):
            continue
        if not generic and not public_detail and not any(k in title for k in ['招标', '采购', '中标', '询价', '竞价', '成交', '谈判', '磋商', '遴选', '比选', '公示', '公告', '招募']):
            continue
        if any(k in title for k in ['寻源询价系统', '操作手册', '平台登录', '平台入口']):
            continue
        row = a.find_parent(['li', 'tr'])
        date_text = a.get('data-published', '') + ' ' + tooltip + ' ' + (row.get_text(' ', strip=True) if row else '')
        if parsed.hostname == 'new.ebidding.cecep.cn':
            card = a.find_parent(class_='bid-box')
            date_node = card.select_one('.bid-date') if card else None
            if date_node:
                date_text = date_node.get_text(' ', strip=True)
        if parsed.hostname in ('www.szecp.com.cn', 'szecp.com.cn'):
            card = a.find_parent(class_='szb-homeRhc-block-listTitle')
            date_node = card.parent.select_one('.szb-homeRhc-block-listDesc3-time') if card else None
            if date_node:
                date_text = date_node.get_text(' ', strip=True)
        if parsed.hostname == 'etp.faw.cn':
            date_node = a.select_one('[class$="-time"]')
            if date_node:
                date_text = date_node.get_text(' ', strip=True)
        if urlsplit(base_url).hostname == 'www.chdtp.com':
            date_text += ' ' + urlsplit(url).path
        match = re.search(r'(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})(?:日)?', date_text)
        date = ''
        if match:
            from datetime import date as Date
            try:
                date = Date(*map(int, match.groups())).isoformat()
            except ValueError:
                pass
        seen.add(url)
        bids.append(BidInfo(title=title, url=url, publish_date=date, source=source))
    return bids
