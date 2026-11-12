"""Persistent source health and a single non-overlapping local collection scheduler."""
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from .sources import catalogue
from .feeds import collect_source, FeedUnavailable
from ..storage.workbench import now, ConflictError


def future(minutes):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(timespec='seconds')


class CollectionService:
    def __init__(self, store, runner=collect_source, sources=None):
        self.store, self.runner = store, runner
        self.catalogue = {s['id']: s for s in (sources if sources is not None else catalogue())}
        self.lock, self.national_lock = threading.RLock(), threading.Lock()
        self.stop, self.closed, self.wake = threading.Event(), threading.Event(), threading.Event()
        self.worker = self.scheduler = None
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
        default = dict(enabled=True, interval_minutes=60, pages_per_source=3, next_run=future(60), last_run=None)
        self.schedule = default | store.setting('collection_schedule', {})
        self.store.set_setting('collection_schedule', self.schedule)

    def snapshot(self):
        with self.lock:
            return dict(self.job)

    def sources(self):
        with self.store.connection() as db:
            health = {r['id']: dict(r) for r in db.execute('SELECT * FROM workbench_sources')}
            counts = {r[0]: r[1] for r in db.execute('SELECT source_id,count(*) FROM project_sources GROUP BY source_id')}
        coverage = self.store.setting('source_coverage', {})
        return [s | health[s['id']] | coverage.get(s['id'], {}) | {'enabled': bool(health[s['id']]['enabled']),
                                       'stored_count': counts.get(s['id'], 0)} for s in self.catalogue.values()]

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
        with self.store.connection() as db:
            db.execute('UPDATE workbench_sources SET enabled=? WHERE id=?', (int(enabled), key))
        return {'saved': True}

    def start(self, key=None, automatic=False, provincial=False):
        with self.lock:
            if self.closed.is_set():
                raise ConflictError('服务正在关闭')
            if self.job['running']:
                raise ConflictError('已有采集任务正在运行')
            if key and key not in self.catalogue:
                raise KeyError(key)
            sources = [s for s in self.sources() if s['id'] == key] if key else [s for s in self.sources() if s['enabled']]
            if provincial:
                sources = [s for s in sources if s.get('channel') == '省站直采']
            sources.sort(key=lambda s: s.get('channel') != '省站直采')
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
                raise ValueError('没有可采集的来源，请先启用来源或等待失败退避结束')
            self.stop.clear()
            self.job.update(running=True, message='正在读取公开公告…', count=0, completed=0,
                            total=len(sources), failures=0, cooldown_skipped=[s['name'] for s in cooldown], trigger='自动更新' if automatic else '手动采集', started_at=now(), finished_at=None, source_id=key or ('省站直采' if provincial else None))
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
            with self.store.connection() as db:
                failures = source['failures'] + 1 if status == 'partial' and result.get('retryable', True) else 0
                retry = future(max(min(1440, 15 * 2 ** min(failures-1, 7)), result.get('retry_after', 0)/60)) if failures else None
                db.execute('''UPDATE workbench_sources SET status=?,last_count=?,message=?,
                              last_success=CASE WHEN ? THEN ? ELSE last_success END,
                              last_error=?,failures=?,retry_at=? WHERE id=?''',
                           (status, found, message[:700], bool(found), now(),
                            '；'.join(result['warnings'])[:500], failures, retry, key))
        except Exception as error:
            status = getattr(error, 'status', 'error')
            message = str(error) if isinstance(error, ValueError) else f'来源采集异常（{type(error).__name__}），请重试'
            failures = source['failures'] + 1
            with self.store.connection() as db:
                db.execute('''UPDATE workbench_sources SET status=?,last_count=?,last_error=?,message=?,
                              failures=?,retry_at=? WHERE id=?''',
                           (status, found, message[:500], message[:500], failures,
                            future(max(min(1440, 15 * 2 ** min(failures-1, 7)), getattr(error, 'retry_after', 0)/60)), key))
        self.store.record_run(source['name'], status, added, message)
        with self.lock:
            self.job['count'] += added
            self.job['completed'] += 1
            self.job['failures'] += int(status not in ('success', 'empty', 'stopped'))
            self.job['message'] = f"已处理 {self.job['completed']}/{self.job['total']} 个来源，新增 {self.job['count']} 条；最近：{source['name']}"

    def _collect(self, sources, pages):
        try:
            with ThreadPoolExecutor(max_workers=4, thread_name_prefix='source') as pool:
                tasks = [pool.submit(self._one, s, pages) for s in sources]
                for task in as_completed(tasks):
                    task.result()
        except Exception as error:
            with self.lock:
                self.job['failures'] += 1
            self.store.record_run('采集调度', 'error', 0, f'任务异常：{type(error).__name__}')
        finally:
            with self.lock:
                self.job['running'] = False
                self.job['message'] = (f"{'已停止；' if self.stop.is_set() else ''}已处理 {self.job['completed']}/{self.job['total']} 个来源，"
                                       f"新增 {self.job['count']} 条，{self.job['failures']} 个来源异常或部分失败")
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
