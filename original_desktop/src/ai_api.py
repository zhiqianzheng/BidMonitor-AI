"""API discovery and real inference checks for compatible chat providers."""
from urllib.parse import urlsplit, urlunsplit
import requests


class ApiError(ValueError):
    pass


def uses_messages(url, model):
    p = urlsplit(url)
    return p.path.rstrip('/').endswith('/messages') or (not p.path.rstrip('/').endswith('/chat/completions') and 'honoursoft' in (p.hostname or '') and 'claude' in model.lower())


def endpoints(url, resource='chat/completions'):
    p = urlsplit(str(url).strip())
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.fragment or any(c in url for c in '\r\n'):
        raise ApiError('请填写有效的 HTTP/HTTPS API URL，不包含用户名、密码或片段。')
    path = p.path.rstrip('/')
    for suffix in ('/chat/completions', '/messages', '/models'):
        if path.endswith(suffix):
            return [urlunsplit(p._replace(path=path[:-len(suffix)] + '/' + resource))]
    paths = [path + '/' + resource]
    if not path:
        paths.append('/v1/' + resource)
    return [urlunsplit(p._replace(path=path)) for path in paths]


def request_json(url, key, resource, payload=None):
    key = key.strip()
    if not key or any(c in key for c in '\r\n'):
        raise ApiError('请填写有效的 API Key。')
    candidates = endpoints(url, resource)
    for index, target in enumerate(candidates):
        native = resource == 'messages' or urlsplit(url).path.rstrip('/').endswith('/messages')
        headers = {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}
        if native:
            headers.update({'x-api-key': key, 'anthropic-version': '2023-06-01'})
        try:
            response = requests.request('POST' if payload is not None else 'GET', target, headers=headers, json=payload, timeout=(8, 35), allow_redirects=False)
        except requests.Timeout:
            raise ApiError('API 请求超时，请检查地址和网络后重试。') from None
        except requests.RequestException:
            raise ApiError('无法连接 API，请检查 URL、网络和证书。') from None
        if response.status_code in (404, 405) and index + 1 < len(candidates):
            continue
        if not 200 <= response.status_code < 300:
            reasons = {401:'API Key 无效或已失效',403:'API Key 没有访问权限',404:'接口不存在，请检查 API URL；该服务可能不提供模型列表',405:'接口方法不支持，请检查 API URL',402:'账户余额不足',429:'额度不足或请求被限流',400:'请求参数或所选模型不兼容'}
            reason = '接口发生重定向，请填写服务的最终 API 地址' if 300 <= response.status_code < 400 else reasons.get(response.status_code,'服务返回错误')
            raise ApiError(f'{reason}（HTTP {response.status_code}）。')
        try:
            result = response.json()
        except ValueError:
            raise ApiError('接口没有返回有效 JSON，可能填入了网站首页而非 API 地址。') from None
        if not isinstance(result, dict) or result.get('error'):
            raise ApiError('API 返回错误或响应结构不符合兼容接口规范。')
        return result


def list_models(url, key):
    result = request_json(url, key, 'models')
    data = result.get('data')
    if not isinstance(data, list):
        raise ApiError('模型列表格式不正确，期望 data 数组。')
    models = sorted({item['id'].strip() for item in data if isinstance(item, dict) and isinstance(item.get('id'), str) and item['id'].strip()})
    if not models:
        raise ApiError('接口未返回模型；请确认此 Key 的权限和模型列表接口。')
    return models


def test_model(url, key, model):
    endpoints(url)
    if not model.strip():
        raise ApiError('请先获取模型列表并选择模型。')
    native = uses_messages(url, model)
    result = request_json(url, key, 'messages' if native else 'chat/completions', {'model':model.strip(), 'messages':[{'role':'user','content':'Reply with OK only.'}], 'max_tokens':64})
    try:
        content = result.get('content') if native else result['choices'][0]['message'].get('content')
        if isinstance(content, list):
            content = ''.join(block.get('text','') for block in content if isinstance(block, dict))
        if not isinstance(content, str) or not content.strip():
            raise ValueError()
    except (KeyError, IndexError, TypeError, ValueError):
        raise ApiError('请求已响应，但没有有效的模型文本输出，尚不能确认可用。') from None
    return True
