"""Refresh vendor-published procurement portals; fetch public directory data only.

Run from the repository root with .venv/bin/python scripts/discover_etrading_sources.py.
Writes a candidate manifest; it does not claim those sites have been collected.
"""
import argparse
import json
import string
import time
from pathlib import Path

import requests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='runtime/workbench/discovered_etrading_sources.json')
    args = parser.parse_args()
    categories = {'035001': '公共资源', '035002': '招标代理', '035003': '高校科研', '035004': '企业招标'}
    rows, errors = [], []
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with requests.Session() as session:
        for category, kind in categories.items():
            count = 0
            for letter in string.ascii_uppercase:
                url = f'https://www.etrading.cn/json/websiteheadZiZhanInfo_{category}_{letter}.json'
                try:
                    response = session.get(url, timeout=(5, 12))
                    response.raise_for_status()
                    data = response.json()
                    if not isinstance(data, list):
                        raise ValueError('Unexpected directory structure')
                    for entry in data:
                        if not isinstance(entry, dict) or not entry.get('urlname') or entry['urlname'] == '/':
                            continue
                        rows.append(dict(name=entry.get('zqname', ''), url=entry['urlname'],
                                         province=entry.get('province') or '全国', kind=kind,
                                         evidence_url=url, directory_group='新点官方专区目录'))
                        count += 1
                except (requests.RequestException, ValueError) as error:
                    errors.append({'url': url, 'error': type(error).__name__})
                time.sleep(0.6)
            Path(args.output).write_text(json.dumps({'rows': rows, 'errors': errors}, ensure_ascii=False, indent=2)+'\n')
            print(kind, count, '累计', len(rows), '目录请求失败', len(errors), flush=True)


if __name__ == '__main__':
    main()
