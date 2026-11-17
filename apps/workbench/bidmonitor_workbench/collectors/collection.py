"""Persistent source health and a single non-overlapping local collection scheduler."""
import threading
from urllib.parse import urlsplit
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from .sources import catalogue
from .sectors import matches_industry, source_sectors, source_names
from .feeds import collect_source, FeedUnavailable
from ..storage.workbench import now, ConflictError


def source_host(source):
    if source['adapter'] == 'national':
        return 'ggzy.gov.cn'
    parsed = urlsplit(source.get('list_url') or source['url'])
    port = f':{parsed.port}' if parsed.port not in (None, 80, 443) else ''
    return parsed.hostname.removeprefix('www.') + port


def future(minutes):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(timespec='seconds')


class CollectionService:
    def __init__(self, store, runner=collect_source, sources=None):
        self.store, self.runner = store, runner
        self.catalogue = {s['id']: s for s in (sources if sources is not None else catalogue())}
        for source in store.setting('custom_sources', []):
            self.catalogue[source['id']] = self.catalogue.get(source['id'], {}) | source
        for source in self.catalogue.values():
            source['sectors'] = source_sectors(source)
        self.lock, self.national_lock = threading.RLock(), threading.Lock()
        self.stop, self.closed, self.wake = threading.Event(), threading.Event(), threading.Event()
        self.worker = self.scheduler = None
        self.discovered_candidates = []
        saved_host_blocks = store.setting('source_host_blocks', None)
        self.host_blocks = saved_host_blocks or {}
        self.job = dict(running=False, message='等待采集', count=0, completed=0, total=0, failures=0)
        self.job.update(store.setting('collection_last_job', {}))
        self.job['running'] = False
        with store.connection() as db:
            db.executemany('INSERT OR IGNORE INTO workbench_sources(id) VALUES (?)', [(k,) for k in self.catalogue])
            for source in self.catalogue.values():
                name = source['name'] + ('（全国平台汇聚）' if source['adapter'] == 'national' else '')
                if source['id'] == 'ccgp':
                    name = '中国政府采购网'
                db.execute('UPDATE workbench_sources SET search_name=? WHERE id=?', (name, source['id']))
            if saved_host_blocks is None:
                for row in db.execute("SELECT id FROM workbench_sources WHERE status='blocked'"):
                    if row['id'] in self.catalogue:
                        host = source_host(self.catalogue[row['id']])
                        self.host_blocks[host] = list(dict.fromkeys(self.host_blocks.get(host, []) + [row['id']]))[:3]
        if saved_host_blocks is None:
            self.store.set_setting('source_host_blocks', self.host_blocks)
        default = dict(enabled=True, interval_minutes=60, pages_per_source=3, next_run=future(60), last_run=None)
        self.schedule = default | store.setting('collection_schedule', {})
        self.store.set_setting('collection_schedule', self.schedule)

    def _record_host_block(self, source):
        host = source_host(source)
        with self.lock:
            observations = set(self.host_blocks.get(host, []))
            observations.add(source['id'])
            self.host_blocks[host] = sorted(observations)[:3]
            self.store.set_setting('source_host_blocks', self.host_blocks)
            # A single private/login-only path must not disable public lists.
            # Three independently blocked channels establish a site-wide skip.
            if len(self.host_blocks[host]) >= 3:
                keys = [s['id'] for s in self.catalogue.values() if source_host(s) == host]
                with self.store.connection() as db:
                    db.executemany("UPDATE workbench_sources SET enabled=0,status='blocked',message=? WHERE id=?",
                                   [('同一站点多个频道限制访问，已停用该站点；可手动启用来源后重试', key) for key in keys])

    def _clear_host_block(self, source):
        with self.lock:
            if self.host_blocks.pop(source_host(source), None) is not None:
                self.store.set_setting('source_host_blocks', self.host_blocks)

    def import_sources(self, content):
        from .registry import parse_import
        return self.add_sources(parse_import(content))

    def add_sources(self, candidates):
        from .registry import source_identity
        with self.lock:
            # Treat http/https spellings and trailing slashes as the same list.
            known = {source_identity(s) for s in self.catalogue.values()}
            added, duplicate = [], 0
            for source in candidates:
                key = source_identity(source)
                if key in known:
                    duplicate += 1
                    continue
                known.add(key)
                added.append(source)
            custom = self.store.setting('custom_sources', []) + added
            # Persist definitions and health atomically, before publishing them in memory.
            import json
            with self.store.connection() as db:
                db.execute('INSERT INTO workbench_settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                           ('custom_sources', json.dumps(custom, ensure_ascii=False)))
                db.executemany('INSERT OR IGNORE INTO workbench_sources(id,search_name,enabled,status,message) VALUES (?,?,?,?,?)',
                               [(s['id'], s['name'], 0, 'blocked', '同站多个频道限制访问，新入口已跳过')
                                if len(self.host_blocks.get(source_host(s), [])) >= 3 else
                                (s['id'], s['name'], 1, 'pending', '') for s in added])
            self.catalogue.update({s['id']: s for s in added})
        return {'added': len(added), 'duplicates': duplicate, 'total': len(self.catalogue)}

    def snapshot(self):
        with self.lock:
            return dict(self.job)

    def sources(self):
        with self.lock:
            catalogue = list(self.catalogue.values())
        with self.store.connection() as db:
            health = {r['id']: dict(r) for r in db.execute('SELECT * FROM workbench_sources')}
            counts = {r[0]: r[1] for r in db.execute('SELECT source_id,count(*) FROM project_sources GROUP BY source_id')}
        coverage = self.store.setting('source_coverage', {})
        return [s | health[s['id']] | coverage.get(s['id'], {}) | {'enabled': bool(health[s['id']]['enabled']),
                                       'stored_count': counts.get(s['id'], 0)} for s in catalogue]

    def source_scope(self, industry='', sector=''):
        with self.lock:
            sources = [s for s in self.catalogue.values()
                       if matches_industry(s, industry) and matches_industry(s, sector)]
        return {'ids': [s['id'] for s in sources],
                'names': sorted({name for s in sources for name in source_names(s)})}

    def schedule_snapshot(self):
        with self.lock:
            return dict(self.schedule)

    def configure(self, enabled, interval_minutes, pages_per_source):
        if not 15 <= interval_minutes <= 1440 or not 1 <= pages_per_source <= 20:
            raise ValueError('更新间隔须为 15–1440 分钟，每个来源 1–20 页')
        with self.lock:
            self.schedule.update(enabled=enabled, interval_minutes=interval_minutes,
                                 pages_per_source=pages_per_source,
                                 next_run=future(interval_minutes) if enabled else None)
            self.store.set_setting('collection_schedule', self.schedule)
            self.wake.set()
            return dict(self.schedule)

    def enable(self, key, enabled):
        if key not in self.catalogue:
            raise KeyError(key)
        if enabled:
            self._clear_host_block(self.catalogue[key])
        with self.store.connection() as db:
            db.execute('UPDATE workbench_sources SET enabled=? WHERE id=?', (int(enabled), key))
        return {'saved': True}

    def start(self, key=None, automatic=False, provincial=False, pending_only=False, industry='', sector='', source_name='', source_ids=None):
        with self.lock:
            if self.closed.is_set():
                raise ConflictError('服务正在关闭')
            if self.job['running']:
                raise ConflictError('已有采集任务正在运行')
            if key and key not in self.catalogue:
                raise KeyError(key)
            sources = [s for s in self.sources() if s['id'] == key] if key else [s for s in self.sources() if s['enabled']]
            sources = [s for s in sources if matches_industry(s, industry) and matches_industry(s, sector)
                       and (not source_name or source_name in source_names(s))]
            if source_ids is not None:
                requested = set(source_ids)
                sources = [s for s in sources if s['id'] in requested]
            if pending_only:
                sources = [s for s in sources if s['status'] in ('pending', 'interrupted', 'stopped')]
            if provincial:
                sources = [s for s in sources if s.get('channel') == '省站直采']
            sources.sort(key=lambda s: ({'pending': 0, 'needs_adapter': 1, 'error': 2}.get(s['status'], 3),
                                        s.get('channel') != '省站直采'))
            # A manual bulk run must not defeat a server's rate-limit cooldown.
            cooldown = [s for s in sources if s['retry_at'] and s['retry_at'] > now()
                        and any(marker in (s.get('last_error') or '') for marker in ('HTTP 429', '限流提示页'))]
            sources = [s for s in sources if s not in cooldown]
            if automatic:
                sources = [s for s in sources if not s['retry_at'] or s['retry_at'] <= now()]
            if not sources:
                if automatic:
                    self.schedule['next_run'] = future(self.schedule['interval_minutes'])
                    self.store.set_setting('collection_schedule', self.schedule)
                raise ValueError('当前行业或来源范围内没有可采集的已启用来源，请检查来源状态或筛选条件')
            if key:
                self._clear_host_block(self.catalogue[key])
            self.stop.clear()
            self.discovered_candidates = []
            scope_label = ' / '.join(dict.fromkeys(x for x in (industry, sector, source_name) if x)) or ('当前来源筛选' if source_ids is not None else '全部行业')
            self.job.update(running=True, industry=industry, sector=sector, explicit_sources=source_ids is not None, scope_label=scope_label, message=f'正在采集：{scope_label}…', count=0, completed=0,
                            total=len(sources), failures=0, discovered=0, cooldown_skipped=[s['name'] for s in cooldown], trigger='自动更新' if automatic else '手动采集', started_at=now(), finished_at=None, source_id=key or source_name or ('省站直采' if provincial else None))
            self.schedule['last_run'] = now()
            self.store.set_setting('collection_schedule', self.schedule)
            pages = self.schedule['pages_per_source']
            self.worker = threading.Thread(target=self._collect, args=(sources, pages), daemon=True, name='workbench-collector')
            self.worker.start()
            return dict(self.job)

    def _one(self, source, pages):
        if self.stop.is_set():
            return
        key, added, found = source['id'], 0, 0
        with self.store.connection() as db:
            # Honor source toggles even when this source was already queued.
            enabled = db.execute('SELECT enabled FROM workbench_sources WHERE id=?', (key,)).fetchone()[0]
            if not enabled and self.job['total'] > 1:
                with self.lock:
                    self.job['completed'] += 1
                return
            db.execute("UPDATE workbench_sources SET status='running',last_attempt=? WHERE id=?", (now(), key))
        try:
            with self.lock:
                site_blocked = len(self.host_blocks.get(source_host(source), [])) >= 3
            if site_blocked:
                raise FeedUnavailable('同站多个频道限制访问，跳过该站点', 'blocked')
            source = source | {'checkpoint': self.store.setting('source_cursor_'+key, {})}
            if source['adapter'] == 'national':
                # All provincial and enterprise channels share a host; serialize and pace them.
                with self.national_lock:
                    if self.stop.wait(1):
                        result = {'rows': [], 'warnings': [], 'message': '已停止'}
                    else:
                        result = self.runner(source, self.stop, pages)
            else:
                result = self.runner(source, self.stop, pages)
            with self.lock:
                self.discovered_candidates.extend(result.get('discovered_sources', []))
            for row in result['rows']:
                if self.stop.is_set():
                    break
                project, created = self.store.upsert_project(row, preserve_source=True)
                added += int(created)
                found += 1
                with self.store.connection() as db:
                    db.execute('INSERT OR IGNORE INTO project_sources VALUES (?,?)', (key, project))
            if not self.stop.is_set():
                if 'checkpoint' in result:
                    self.store.set_setting('source_cursor_'+key, result['checkpoint'])
                with self.lock:
                    coverage = self.store.setting('source_coverage', {})
                    coverage[key] = {'coverage': result.get('coverage', 'limited' if result.get('truncated') else 'window'),
                                     'truncated': bool(result.get('truncated'))}
                    self.store.set_setting('source_coverage', coverage)
            if self.stop.is_set():
                status, message = 'stopped', f'已停止；入库 {found} 条，新增 {added} 条'
            else:
                if not found and not result.get('empty_ok'):
                    raise FeedUnavailable('没有有效公告，不计为采集成功', 'needs_adapter')
                status = 'partial' if result['warnings'] else 'success' if found else 'empty'
                message = result['message'] + f'；新增 {added} 条'
                if result['warnings']:
                    message += '；部分失败：' + '；'.join(result['warnings'])
            if result.get('blocked'):
                self._record_host_block(source)
            with self.store.connection() as db:
                if result.get('blocked'):
                    status = 'blocked'
                    message += '；访问受限，已自动停用，可在来源页手动启用'
                    db.execute('UPDATE workbench_sources SET enabled=0 WHERE id=?', (key,))
                failures = source['failures'] + 1 if status == 'partial' and result.get('retryable', True) else 0
                retry = future(max(min(1440, 15 * 2 ** min(failures-1, 7)), result.get('retry_after', 0)/60)) if failures else None
                db.execute('''UPDATE workbench_sources SET status=?,last_count=?,message=?,
                              last_success=CASE WHEN ? THEN ? ELSE last_success END,
                              last_error=?,failures=?,retry_at=? WHERE id=?''',
                           (status, found, message[:700], bool(found), now(),
                            '；'.join(result['warnings'])[:500], failures, retry, key))
        except Exception as error:
            with self.lock:
                self.discovered_candidates.extend(getattr(error, 'discovered_sources', []))
            status = getattr(error, 'status', 'error')
            message = str(error) if isinstance(error, ValueError) else f'来源采集异常（{type(error).__name__}），请重试'
            failures = source['failures'] + 1
            if status == 'blocked':
                self._record_host_block(source)
                message += '；访问受限，已自动停用，可在来源页手动启用'
            with self.store.connection() as db:
                if status == 'blocked':
                    db.execute('UPDATE workbench_sources SET enabled=0 WHERE id=?', (key,))
                db.execute('''UPDATE workbench_sources SET status=?,last_count=?,last_error=?,message=?,
                              failures=?,retry_at=? WHERE id=?''',
                           (status, found, message[:500], message[:500], failures,
                            future(max(min(1440, 15 * 2 ** min(failures-1, 7)), getattr(error, 'retry_after', 0)/60)), key))
        self.store.record_run(source['name'], status, added, message)
        with self.lock:
            self.job['count'] += added
            self.job['completed'] += 1
            self.job['failures'] += int(status not in ('success', 'empty', 'stopped'))
            self.job['message'] = f"范围：{self.job.get('scope_label', '全部行业')}；已处理 {self.job['completed']}/{self.job['total']} 个来源，新增 {self.job['count']} 条；最近：{source['name']}"

    def _collect(self, sources, pages):
        try:
            pending = sources
            # Continue into newly found platforms during this run; later schedules
            # revisit the full persisted registry. Bound each run to two discovery waves.
            for wave in range(3):
                with ThreadPoolExecutor(max_workers=4, thread_name_prefix='source') as pool:
                    tasks = [pool.submit(self._one, s, pages) for s in pending]
                    for task in as_completed(tasks):
                        task.result()
                with self.lock:
                    candidates, self.discovered_candidates = self.discovered_candidates, []
                if not candidates or not self.store.setting('source_discovery_enabled', True):
                    break
                known = set(self.catalogue)
                imported = self.add_sources(candidates)
                with self.lock:
                    self.job['discovered'] = self.job.get('discovered', 0) + imported['added']
                if self.stop.is_set() or not imported['added'] or wave == 2 or self.job.get('source_id') or self.job.get('explicit_sources'):
                    break
                pending = [s for s in self.sources() if s['id'] not in known and s['enabled']
                           and matches_industry(s, self.job.get('industry', ''))
                           and matches_industry(s, self.job.get('sector', ''))]
                if not pending:
                    break
                with self.lock:
                    self.job['total'] += len(pending)

        except Exception as error:
            with self.lock:
                self.job['failures'] += 1
            self.store.record_run('采集调度', 'error', 0, f'任务异常：{type(error).__name__}')
        finally:
            with self.lock:
                self.job['running'] = False
                self.job['message'] = (f"{'已停止；' if self.stop.is_set() else ''}已处理 {self.job['completed']}/{self.job['total']} 个来源，"
                                       f"新增 {self.job['count']} 条，{self.job['failures']} 个来源异常或部分失败")
                if self.job.get('discovered'):
                    self.job['message'] += f"；自动发现并保存 {self.job['discovered']} 个关联来源"
                if self.job.get('cooldown_skipped'):
                    self.job['message'] += '；限流冷却跳过：' + '、'.join(self.job['cooldown_skipped'])
                if not self.job.get('source_id'):
                    self.schedule['next_run'] = future(self.schedule['interval_minutes']) if self.schedule['enabled'] else None
                self.job['finished_at'] = now()
                self.store.set_setting('collection_last_job', self.job)
                self.store.set_setting('collection_schedule', self.schedule)

    def tick(self):
        with self.lock:
            due = self.schedule['next_run']
            if self.schedule['enabled'] and due and due <= now() and not self.job['running']:
                try:
                    self.start(automatic=True)
                except ValueError:
                    pass

    def open(self):
        if self.scheduler and self.scheduler.is_alive():
            return
        with self.store.connection() as db:
            db.execute("UPDATE workbench_sources SET status='interrupted', message='上次采集因服务退出中断，下次更新会重试' WHERE status='running'")
        def loop():
            while not self.closed.is_set():
                try:
                    self.tick()
                except Exception as error:
                    self.store.record_run('定时调度', 'error', 0, f'调度异常：{type(error).__name__}')
                self.wake.wait(5)
                self.wake.clear()
        self.scheduler = threading.Thread(target=loop, daemon=True, name='workbench-scheduler')
        self.scheduler.start()

    def close(self):
        self.closed.set()
        self.stop.set()
        self.wake.set()
        if self.scheduler:
            self.scheduler.join(timeout=2)
