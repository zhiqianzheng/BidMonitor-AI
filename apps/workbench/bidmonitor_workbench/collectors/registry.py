"""Persistent, deduplicated website registry and bulk CSV imports."""
import csv
import hashlib
import io
import ipaddress
from urllib.parse import urlsplit, urlunsplit


KINDS = ('政府采购', '公共资源', '企业招标', '行业平台', '招标代理', '高校科研', '医疗卫生', '金融采购', '综合招标')


def source_identity(source):
    parsed = urlsplit(source['url'])
    port = parsed.port if parsed.port not in (None, 80, 443) else 0
    fragment = parsed.fragment if parsed.fragment.startswith(('/', '!/')) else ''
    return (parsed.hostname.removeprefix('www.'), port, parsed.path.rstrip('/'), parsed.query, fragment)


def normalize_source(item):
    name, url = str(item.get('name') or '').strip(), str(item.get('url') or '').strip()
    parsed = urlsplit(url)
    if not 2 <= len(name) <= 100:
        raise ValueError('来源名称须为 2–100 字')
    if len(url) > 2000 or parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password or parsed.port == 0:
        raise ValueError('请填写公开 HTTP/HTTPS 网址，不允许账号密码')
    host = parsed.hostname.lower()
    if host == 'localhost' or '.' not in host or host.endswith(('.local', '.localhost', '.internal')):
        raise ValueError('来源网址不能是本机或内网地址')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError('来源网址不能是本机或内网地址')
    url = urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path or '/', parsed.query, parsed.fragment))
    kind = str(item.get('kind') or '行业平台').strip()
    province = str(item.get('province') or '全国').strip()
    if kind not in KINDS or len(province) > 40:
        raise ValueError('来源类别或地区无效')
    source = dict(id='site-'+hashlib.sha256(url.encode()).hexdigest()[:20], name=name, url=url,
                kind=kind, province=province, adapter='generic', channel='网站直采',
                scope='公开列表通用采集；仅标题、原始链接和发布时间；动态页面需适配，成功状态以实测为准')
    from .sectors import source_sectors
    source['sectors'] = source_sectors(source)
    return source


def parse_import(content):
    """Accept CSV with Chinese or English headers; validate before changing state."""
    aliases = {'名称': 'name', '网站名称': 'name', '网址': 'url', '链接': 'url', '地区': 'province', '类别': 'kind'}
    content = content.lstrip('\ufeff').strip()
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        raise ValueError('请填写 CSV，首行为 名称,网址,地区,类别')
    headers = [aliases.get(x.strip(), x.strip()) for x in reader.fieldnames]
    if 'name' not in headers or 'url' not in headers or len(set(headers)) != len(headers):
        raise ValueError('CSV 表头须包含 名称,网址，且列名不能重复')
    rows = []
    for number, row in enumerate(reader, 2):
        if number > 10001:
            raise ValueError('每次最多导入 10000 行，请分批导入')
        try:
            if None in row:
                raise ValueError('列数多于表头，请使用 CSV 引号包裹含逗号的值')
            normalized = {aliases.get(k.strip(), k.strip()): v for k,v in row.items()}
            rows.append(normalize_source(normalized))
        except ValueError as error:
            raise ValueError(f'第 {number} 行：{error}') from None
    if not rows:
        raise ValueError('CSV 没有来源记录')
    return rows


def redact_url_secrets(value):
    """Keep public routing parameters, remove credentials from captured redirects."""
    from urllib.parse import parse_qsl, urlencode
    if not isinstance(value, str) or not value.startswith(('http://', 'https://')):
        return value
    try:
        parsed = urlsplit(value)
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        kept = []
        for key, item in pairs:
            normalized = key.lower().replace('-', '').replace('_', '')
            if (any(word in normalized for word in ('secret', 'password', 'accesskey', 'signature', 'credential', 'authorization'))
                    or normalized in ('token', 'accesstoken', 'refreshtoken', 'expires', 'xamzsecuritytoken')):
                continue
            kept.append((key, redact_url_secrets(item)))
        fragment = parsed.fragment
        if '?' in fragment:
            route, query = fragment.split('?', 1)
            cleaned = redact_url_secrets('https://redaction.invalid/?' + query)
            fragment = route + ('?' + urlsplit(cleaned).query if urlsplit(cleaned).query else '')
        if kept == pairs and fragment == parsed.fragment:
            return value
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(kept), fragment))
    except ValueError:
        return value
