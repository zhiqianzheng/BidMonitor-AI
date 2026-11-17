"""Refresh a public navigation directory as *candidates*, without executing its JS.

Use: PYTHONPATH=. .venv/bin/python scripts/refresh_source_directory.py
Optional script dependency: json5 (listed in scripts/requirements.txt).
"""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import json5
import requests

from apps.workbench.bidmonitor_workbench.collectors.registry import normalize_source, source_identity
from apps.workbench.bidmonitor_workbench.collectors.sources import catalogue

GROUPS = {'NATIONAL': '政府采购', 'MKT': '综合招标', 'INTL': '行业平台', 'SOES': '企业招标',
          'PSOES': '企业招标', 'SOEWEBS': '企业招标', 'UNIV': '高校科研', 'YLCG': '医疗卫生', 'CQJYS': '行业平台'}


identity = source_identity


def parse_arrays(text):
    """JSON5 parses data only; never eval/execute a downloaded JavaScript file."""
    arrays = {}
    for match in re.finditer(r'const\s+(\w+)\s*=\s*(\[.*?\n\]);', text, re.S):
        if match[1] in GROUPS:
            data = json5.loads(match[2])
            if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
                raise ValueError('目录数据结构变化')
            arrays[match[1]] = data
    if not arrays:
        raise ValueError('没有找到已知的目录数据，未修改来源库')
    return arrays


def main():
    url = 'https://biaoxun.vip/nav/data.js?v=164'
    response = requests.get(url, timeout=(8, 25))
    response.raise_for_status()
    if len(response.content) > 5 * 1024 * 1024:
        raise ValueError('目录超过 5 MB')
    response.encoding = 'utf-8'
    groups = parse_arrays(response.text)
    path = Path('apps/workbench/bidmonitor_workbench/collectors/extra_sources.json')
    extra = json.loads(path.read_text())
    existing = catalogue()
    known = {identity(s) for s in existing}
    added, enriched, skipped = 0, 0, 0
    by_identity = {identity(s): s for s in extra}
    for group, records in groups.items():
        for entry in records:
            # Directories also list legal information sites, which aren't tender sources.
            if not entry.get('u') or not entry.get('n') or re.search('贸易法委员会|仲裁|法律法规', entry['n']):
                continue
            try:
                candidate = normalize_source(dict(name=entry['n'], url=entry['u'], province=entry.get('p') or '全国', kind=GROUPS[group]))
            except ValueError:
                skipped += 1
                continue
            key = identity(candidate)
            if key in by_identity:
                old = by_identity[key]
                if entry.get('g'):
                    old['sector_hint'] = entry['g']
                if entry.get('p'):
                    old['province'] = entry['p']
                enriched += 1
            if key in known:
                continue
            candidate.update(evidence_url='https://biaoxun.vip/nav/', directory_group='公开跨行业目录·'+group,
                             sector_hint=entry.get('g') or '', catalogue_checked_at='2026-11-16')
            known.add(key)
            extra.append(candidate)
            added += 1
    path.write_text(json.dumps(extra, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'added': added, 'metadata_enriched': enriched, 'invalid_urls': skipped, 'extra_total': len(extra)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
