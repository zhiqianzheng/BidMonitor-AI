"""Persistent announcement search and team lead tracking."""
import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urldefrag, urlsplit
from .taxonomy import NOTICE_TYPES, INDUSTRIES, CATEGORIES, classify_notice, suggest_category, suggest_industry
from .availability import availability_state, availability_fields


STAGES = ("待评估", "已认领", "已联系", "准备投标", "已投标", "成交", "失标", "放弃")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def classify(title):
    return classify_notice(title)


def is_notice(title):
    if re.search("平台上线|平台荣获|采购总量|采购累计|网站维护|停用通知|停机通知", title):
        return False
    return len(title.strip()) >= 12 and bool(re.search(
        "公告|招标|采购|中标|询价|询比|磋商|谈判|征集|公示|成交", title))


class ConflictError(Exception):
    pass


class WorkbenchStore:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '', region TEXT NOT NULL DEFAULT '',
                    notice_type TEXT NOT NULL DEFAULT '其他', published_at TEXT NOT NULL DEFAULT '',
                    deadline TEXT NOT NULL DEFAULT '', budget TEXT NOT NULL DEFAULT '',
                    purchaser TEXT NOT NULL DEFAULT '', agency TEXT NOT NULL DEFAULT '',
                    project_no TEXT NOT NULL DEFAULT '', content TEXT NOT NULL DEFAULT '',
                    attachments TEXT NOT NULL DEFAULT '[]', detail_status TEXT NOT NULL DEFAULT 'pending',
                    detail_error TEXT NOT NULL DEFAULT '', detail_fetched_at TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS projects_date ON projects(published_at DESC, created_at DESC);
                CREATE INDEX IF NOT EXISTS projects_region ON projects(region);
                CREATE TABLE IF NOT EXISTS members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL
                );
                CREATE TABLE IF NOT EXISTS leads (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL UNIQUE REFERENCES projects(id),
                    owner TEXT NOT NULL DEFAULT '', stage TEXT NOT NULL DEFAULT '待评估',
                    priority TEXT NOT NULL DEFAULT '普通', next_followup TEXT NOT NULL DEFAULT '',
                    contact_name TEXT NOT NULL DEFAULT '', contact_info TEXT NOT NULL DEFAULT '',
                    version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS lead_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id TEXT NOT NULL REFERENCES leads(id),
                    body TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'note', created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workbench_settings (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS collection_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
                    status TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workbench_sources (
                    id TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1,
                    search_name TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending', last_attempt TEXT,
                    last_success TEXT, last_error TEXT NOT NULL DEFAULT '',
                    failures INTEGER NOT NULL DEFAULT 0, retry_at TEXT,
                    last_count INTEGER NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS project_sources (
                    source_id TEXT NOT NULL REFERENCES workbench_sources(id),
                    project_id TEXT NOT NULL REFERENCES projects(id),
                    PRIMARY KEY(source_id, project_id)
                );
            """)
            source_columns = {r[1] for r in db.execute('PRAGMA table_info(workbench_sources)')}
            if 'search_name' not in source_columns:
                db.execute("ALTER TABLE workbench_sources ADD COLUMN search_name TEXT NOT NULL DEFAULT ''")
            columns = {r[1] for r in db.execute('PRAGMA table_info(projects)')}
            for column in ('industry', 'category'):
                if column not in columns:
                    db.execute(f"ALTER TABLE projects ADD COLUMN {column} TEXT NOT NULL DEFAULT '待分类'")
                    classify_field = suggest_industry if column == 'industry' else suggest_category
                    for row in db.execute('SELECT id,title FROM projects').fetchall():
                        db.execute(f'UPDATE projects SET {column}=? WHERE id=?', (classify_field(row['title']),row['id']))

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def upsert_project(self, data, preserve_source=False):
        url = data.get("url", "").strip()
        # Hash routers encode the actual announcement identity in the fragment.
        if not urlsplit(url).fragment.startswith(('/', '!/')):
            url = urldefrag(url)[0]
        key = hashlib.sha256(url.encode()).hexdigest() if url else uuid.uuid4().hex
        fields = ("title", "source", "region", "published_at", "deadline", "budget",
                  "purchaser", "agency", "project_no", "content")
        values = {k: str(data.get(k) or "").strip() for k in fields}
        values.update(id=key, url=url, notice_type=data.get("notice_type") or classify(values["title"]),
                      detail_status="ready" if values["content"] else "pending",
                      created_at=now(), updated_at=now())
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM projects WHERE id=?", (key,)).fetchone()
            if old:
                # A list refresh must not erase a previously fetched detail page.
                if values['title'].endswith(('..', '…')) and old['title'].startswith(values['title'].rstrip('.…')):
                    values['title'] = old['title']
                if values['published_at'] and old['published_at'].startswith(values['published_at']):
                    values['published_at'] = old['published_at']
                updates = {k: v for k, v in values.items()
                           if k not in ("id", "created_at", "detail_status", "updated_at") and v and v != old[k]}
                if preserve_source and old['source']:
                    updates.pop('source', None)
                if values["content"]:
                    updates["detail_status"] = "ready"
                if updates:
                    updates["updated_at"] = now()
                    db.execute("UPDATE projects SET " + ",".join(k + "=?" for k in updates) +
                               " WHERE id=?", (*updates.values(), key))
            else:
                values['industry'] = data.get('industry') or suggest_industry(values['title'])
                values['category'] = data.get('category') or suggest_category(values['title'])
                db.execute("INSERT INTO projects (" + ",".join(values) + ") VALUES (" +
                           ",".join("?" for _ in values) + ")", tuple(values.values()))
        return key, old is None

    def archive_bid(self, bid):
        return self.upsert_project(dict(title=bid.title, url=bid.url, source=bid.source,
                                       published_at=bid.publish_date, purchaser=bid.purchaser,
                                       content=bid.content))

    def import_legacy(self):
        with self.connection() as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='bids'").fetchone()
            rows = db.execute("SELECT * FROM bids").fetchall() if exists else []
        for row in rows:
            self.upsert_project(dict(row) | {"published_at": row["publish_date"]})

    def search(self, q="", region="", notice_type="", source="", date_from="", date_to="",
               scope="all", limit=20, offset=0, tracked=False, industry="", category="", availability="active", refine=""):
        if availability not in ("active", "open", "unknown", "closed", "all"):
            raise ValueError("未知截止状态筛选")
        checked_at = datetime.now(timezone.utc)
        clauses, args = [], []
        # Each keyword adds an AND clause before counting and pagination.
        for term in [*q.strip().split()[:12], *refine.strip().split()]:
            escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            cols = ("p.title",) if scope == "title" else ("p.title", "p.content", "p.purchaser", "p.project_no")
            clauses.append("(" + " OR ".join(c + " LIKE ? ESCAPE '\\'" for c in cols) + ")")
            args.extend(["%" + escaped + "%"] * len(cols))
        types = [notice_type] if isinstance(notice_type, str) else (notice_type or [])
        types = list(dict.fromkeys(t for t in types if t))
        if types:
            clauses.append("p.notice_type IN (" + ",".join("?" for _ in types) + ")")
            args.extend(types)
        for col, value in (("region", region),
                           ("industry", industry), ("category", category)):
            if value:
                clauses.append("p." + col + "=?")
                args.append(value)
        if source:
            clauses.append('''(p.source=? OR EXISTS (
                SELECT 1 FROM project_sources ps JOIN workbench_sources ws ON ws.id=ps.source_id
                WHERE ps.project_id=p.id AND ws.search_name=?))''')
            args.extend([source, source])
        if date_from:
            clauses.append("p.published_at>=?")
            args.append(date_from)
        if date_to:
            clauses.append("p.published_at<>'' AND substr(p.published_at,1,10)<=?")
            args.append(date_to)
        if tracked:
            clauses.append("l.id IS NOT NULL")
        states = {"active": ("open", "unknown"), "open": ("open",),
                  "unknown": ("unknown",), "closed": ("expired", "ended")}.get(availability)
        if states:
            clauses.append("announcement_state(p.deadline,p.notice_type,p.title) IN (" + ",".join("?" for _ in states) + ")")
            args.extend(states)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        base = " FROM projects p LEFT JOIN leads l ON l.project_id=p.id"
        with self.connection() as db:
            db.create_function("announcement_state", 3,
                               lambda deadline, kind, title: availability_state(deadline, kind, title, checked_at),
                               deterministic=True)
            db.execute("BEGIN")
            total = db.execute("SELECT COUNT(*)" + base + where, args).fetchone()[0]
            rows = db.execute("""
                SELECT p.id,p.title,p.url,p.source,p.region,p.industry,p.category,p.notice_type,p.published_at,p.deadline,
                       p.budget,p.purchaser,p.detail_status,p.created_at,substr(p.content,1,160) AS excerpt,
                       l.id AS lead_id,l.owner,l.stage
                """ + base + where + " ORDER BY p.published_at DESC,p.created_at DESC,p.id LIMIT ? OFFSET ?",
                (*args, limit, offset)).fetchall()
        return {"total": total, "items": [dict(r) | availability_fields(dict(r), checked_at) for r in rows],
                "limit": limit, "offset": offset, "availability": availability,
                "checked_at": checked_at.isoformat(), "deadline_timezone": "Asia/Shanghai"}

    def project(self, key):
        with self.connection() as db:
            row = db.execute("SELECT * FROM projects WHERE id=?", (key,)).fetchone()
            if not row:
                return None
            result = dict(row)
            result.update(availability_fields(result, datetime.now(timezone.utc)))
            result['collected_sources'] = [r[0] for r in db.execute('''
                SELECT s.search_name FROM project_sources ps JOIN workbench_sources s ON s.id=ps.source_id
                WHERE ps.project_id=? AND s.search_name<>'' ORDER BY s.search_name''', (key,))]
            result["attachments"] = json.loads(result["attachments"])
            lead = db.execute("SELECT * FROM leads WHERE project_id=?", (key,)).fetchone()
            result["lead"] = dict(lead) if lead else None
            result["notes"] = [dict(r) for r in db.execute(
                "SELECT * FROM lead_notes WHERE lead_id=? ORDER BY id DESC", (lead["id"],))] if lead else []
            result["related"] = [dict(r) for r in db.execute(
                "SELECT id,title,notice_type,published_at FROM projects WHERE project_no=? AND id<>? "
                "ORDER BY published_at DESC LIMIT 20", (row["project_no"], key))] if row["project_no"] else []
            return result

    def set_detail(self, key, data=None, error=""):
        with self.connection() as db:
            if error:
                db.execute("UPDATE projects SET detail_status=CASE WHEN content<>'' THEN 'ready' ELSE 'error' END,"
                           " detail_error=? WHERE id=?", (error[:500], key))
            else:
                data = dict(data or {})
                data["attachments"] = json.dumps(data.get("attachments", []), ensure_ascii=False)
                allowed = {"title", "content", "attachments", "published_at", "deadline", "budget", "purchaser",
                           "agency", "project_no", "region", "category"}
                updates = {k: v for k, v in data.items() if k in allowed and v}
                updates.update(detail_status="ready", detail_error="", detail_fetched_at=now(), updated_at=now())
                db.execute("UPDATE projects SET " + ",".join(k + "=?" for k in updates) +
                           " WHERE id=?", (*updates.values(), key))

    def create_lead(self, project_id, owner=""):
        key, timestamp = uuid.uuid4().hex, now()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
                raise KeyError(project_id)
            if owner and not db.execute("SELECT 1 FROM members WHERE name=?", (owner,)).fetchone():
                raise ValueError("请选择已添加的团队成员")
            existing = db.execute("SELECT id FROM leads WHERE project_id=?", (project_id,)).fetchone()
            if existing:
                return existing["id"], False
            db.execute("INSERT INTO leads(id,project_id,owner,created_at,updated_at) VALUES (?,?,?,?,?)",
                       (key, project_id, owner, timestamp, timestamp))
            db.execute("INSERT INTO lead_notes(lead_id,body,kind,created_at) VALUES (?,?,?,?)",
                       (key, "加入线索池" + ("，负责人：" + owner if owner else "，待分配"), "system", timestamp))
        return key, True

    def edit_project(self, key, data):
        allowed = {"title", "source", "region", "notice_type", "published_at", "deadline", "budget",
                   "purchaser", "agency", "project_no", "content", "industry", "category"}
        updates = {k: v for k, v in data.items() if k in allowed}
        updates.update(detail_status="ready" if data.get("content") else "pending", updated_at=now())
        with self.connection() as db:
            db.execute("UPDATE projects SET " + ",".join(k + "=?" for k in updates) + " WHERE id=?",
                       (*updates.values(), key))
        return self.project(key)

    def update_lead(self, key, data, version):
        allowed = {"owner", "stage", "priority", "next_followup", "contact_name", "contact_info"}
        updates = {k: v for k, v in data.items() if k in allowed}
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM leads WHERE id=?", (key,)).fetchone()
            if not old:
                raise KeyError(key)
            if old["version"] != version:
                raise ConflictError("此线索已被更新，请重新打开后再保存")
            owner = updates.get("owner")
            if owner and not db.execute("SELECT 1 FROM members WHERE name=?", (owner,)).fetchone():
                raise ValueError("请选择已添加的团队成员")
            changes = {k: v for k, v in updates.items() if old[k] != v}
            if changes:
                changes.update(version=version + 1, updated_at=now())
                db.execute("UPDATE leads SET " + ",".join(k + "=?" for k in changes) +
                           " WHERE id=?", (*changes.values(), key))
                labels = {"owner": "负责人", "stage": "阶段", "priority": "优先级",
                          "next_followup": "下次跟进", "contact_name": "联系人", "contact_info": "联系方式"}
                description = "；".join(labels[k] + "：" + str(old[k] or "未设置") + " → " +
                                        str(v or "未设置") for k, v in changes.items() if k in labels)
                db.execute("INSERT INTO lead_notes(lead_id,body,kind,created_at) VALUES (?,?,?,?)",
                           (key, description, "system", now()))
        return self.project(old["project_id"])

    def add_note(self, key, body):
        with self.connection() as db:
            if not db.execute("SELECT 1 FROM leads WHERE id=?", (key,)).fetchone():
                raise KeyError(key)
            db.execute("INSERT INTO lead_notes(lead_id,body,created_at) VALUES (?,?,?)", (key, body, now()))

    def leads(self, owner="", stage="", q="", due=False):
        clauses, args = [], []
        if owner:
            clauses.append("l.owner=?")
            args.append("" if owner == "__unassigned" else owner)
        if stage:
            clauses.append("l.stage=?")
            args.append(stage)
        if q:
            clauses.append("p.title LIKE ?")
            args.append("%" + q + "%")
        if due:
            clauses.append("l.next_followup<>'' AND l.next_followup<=? AND l.stage NOT IN ('成交','失标','放弃')")
            args.append(datetime.now().strftime("%Y-%m-%dT%H:%M"))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connection() as db:
            return [dict(r) for r in db.execute("""
                SELECT l.*,p.title,p.source,p.region,p.budget,p.deadline,p.purchaser
                FROM leads l JOIN projects p ON p.id=l.project_id
            """ + where + " ORDER BY l.updated_at DESC,l.id", args)]

    def meta(self):
        with self.connection() as db:
            total = db.execute("SELECT count(*) FROM projects").fetchone()[0]
            ready = db.execute("SELECT count(*) FROM projects WHERE detail_status='ready'").fetchone()[0]
            stages = {r[0]: r[1] for r in db.execute("SELECT stage,count(*) FROM leads GROUP BY stage")}
            return {
                "projects": total, "details_ready": ready, "leads": sum(stages.values()),
                "stages": stages, "due": len(self.leads(due=True)),
                "members": [r[0] for r in db.execute("SELECT name FROM members ORDER BY id")],
                "regions": [r[0] for r in db.execute("SELECT DISTINCT region FROM projects WHERE region<>'' ORDER BY region")],
                "sources": [r[0] for r in db.execute('''SELECT source FROM projects WHERE source<>''
                    UNION SELECT s.search_name FROM workbench_sources s JOIN project_sources ps ON ps.source_id=s.id
                    WHERE s.search_name<>'' ORDER BY 1''')],
                "notice_types": NOTICE_TYPES, "stage_options": STAGES,
                "industries": sorted(set(INDUSTRIES) | {r[0] for r in db.execute('SELECT DISTINCT industry FROM projects')}),
                "categories": CATEGORIES,
                "runs": [dict(r) for r in db.execute("SELECT * FROM collection_runs ORDER BY id DESC LIMIT 50")],
            }

    def add_member(self, name):
        with self.connection() as db:
            db.execute("INSERT OR IGNORE INTO members(name) VALUES (?)", (name,))

    def setting(self, key, default=None):
        with self.connection() as db:
            row = db.execute("SELECT value FROM workbench_settings WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.connection() as db:
            db.execute("INSERT INTO workbench_settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (key, json.dumps(value)))

    def record_run(self, source, status, count, message):
        with self.connection() as db:
            db.execute("INSERT INTO collection_runs(source,status,count,message,created_at) VALUES (?,?,?,?,?)",
                       (source, status, count, message[:500], now()))
