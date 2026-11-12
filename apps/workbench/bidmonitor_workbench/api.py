"""Local team workbench. Run through run_workbench.py on the loopback interface."""
import csv
import io
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .storage.workbench import WorkbenchStore, ConflictError, STAGES, NOTICE_TYPES
from .collectors.detail import fetch_page, fetch_detail
from .collectors.ceec import parse_announcements
from .collectors.government import SOURCE as GOVERNMENT_SOURCE, parse_announcements as parse_government
from .storage.taxonomy import INDUSTRIES, CATEGORIES
from .collectors.collection import CollectionService
from .collectors.feeds import collect_source

from .paths import database_path

WEB = Path(__file__).resolve().parent / "web"
SOURCE = {"name": "中国能建电子采购平台", "url": "https://ec.ceec.net.cn/"}


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProjectInput(Input):
    title: str = Field(min_length=4, max_length=500)
    url: str = Field(default="", max_length=2000)
    source: str = Field(default="手动录入", max_length=100)
    region: str = Field(default="", max_length=100)
    industry: str = Field(default="待分类", max_length=60)
    category: Literal["工程", "货物", "服务", "待分类"] = "待分类"
    notice_type: str = "其他"
    published_at: str = ""
    deadline: str = ""
    budget: str = Field(default="", max_length=100)
    purchaser: str = Field(default="", max_length=200)
    agency: str = Field(default="", max_length=200)
    project_no: str = Field(default="", max_length=150)
    content: str = Field(default="", max_length=200000)

    @field_validator("url")
    @classmethod
    def valid_url(cls, value):
        if value:
            parsed = urlsplit(value)
            if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("请输入 HTTP/HTTPS 原文链接")
        return value

    @field_validator("notice_type")
    @classmethod
    def valid_type(cls, value):
        if value not in NOTICE_TYPES:
            raise ValueError("未知公告类型")
        return value

    @field_validator("published_at", "deadline")
    @classmethod
    def valid_date(cls, value):
        if value:
            datetime.fromisoformat(value)
        return value


class OwnerInput(Input):
    owner: str = Field(default="", max_length=50)


class MemberInput(Input):
    name: str = Field(min_length=1, max_length=50)


class LeadInput(OwnerInput):
    version: int = Field(ge=1)
    stage: str
    priority: Literal["普通", "重要", "紧急"] = "普通"
    next_followup: str = ""
    contact_name: str = Field(default="", max_length=100)
    contact_info: str = Field(default="", max_length=300)

    @field_validator("stage")
    @classmethod
    def valid_stage(cls, value):
        if value not in STAGES:
            raise ValueError("未知跟进阶段")
        return value

    @field_validator("next_followup")
    @classmethod
    def valid_followup(cls, value):
        if value:
            parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M")
            return parsed.strftime("%Y-%m-%dT%H:%M")
        return value


class NoteInput(Input):
    body: str = Field(min_length=1, max_length=10000)


class ScheduleInput(Input):
    enabled: bool
    interval_minutes: int = Field(ge=15, le=1440)
    pages_per_source: int = Field(ge=1, le=20)


class SourceInput(Input):
    enabled: bool


def create_app(db_path=None):
    @asynccontextmanager
    async def lifespan(app):
        collector.open()
        try:
            yield
        finally:
            collector.close()

    app = FastAPI(title="BidMonitor 团队工作台", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    store = WorkbenchStore(db_path or database_path())
    store.import_legacy()
    app.state.store = store
    collector = CollectionService(store, runner=lambda source, stop, pages: collect_source(source, stop, pages, html_fetch=fetch_page))
    app.state.collector = collector

    @app.middleware("http")
    async def same_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        expected = str(request.base_url).rstrip("/")
        if request.method not in ("GET", "HEAD", "OPTIONS") and (
            (origin and origin != expected) or request.headers.get("sec-fetch-site") == "cross-site"
        ):
            return JSONResponse({"detail": "请在工作台页面内操作"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(KeyError)
    async def not_found(request, error):
        return JSONResponse({"detail": "记录不存在"}, status_code=404)

    @app.exception_handler(ConflictError)
    async def conflict(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    @app.get("/api/health")
    def health():
        return {"app": "bidmonitor-workbench", "version": 1}

    @app.get("/api/meta")
    def meta():
        return store.meta() | {"collection": collector.snapshot(), "schedule": collector.schedule_snapshot(), "source_config": SOURCE,
                               "source_configs": collector.sources(), "scope": "all_industries",
                               "timezone": str(datetime.now().astimezone().tzinfo)}

    def get_project(key):
        item = store.project(key)
        if not item:
            raise KeyError(key)
        return item

    @app.get("/api/projects")
    def search(q: str = Query("", max_length=300), region: str = "", notice_type: list[str] | None = Query(None, max_length=100),
               source: str = "", date_from: date | None = None, date_to: date | None = None,
               scope: Literal["all", "title"] = "all", limit: int = Query(20, ge=1, le=100),
               offset: int = Query(0, ge=0), tracked: bool = False, industry: str = "", category: str = "",
               availability: Literal["active", "open", "unknown", "closed", "all"] = "active",
               refine: str = Query("", max_length=300)):
        if date_from and date_to and date_from > date_to:
            raise ValueError("开始日期不能晚于结束日期")
        return store.search(q, region, notice_type, source, str(date_from or ""), str(date_to or ""),
                            scope, limit, offset, tracked, industry, category, availability, refine)

    @app.get("/api/export")
    def export(q: str = "", region: str = "", notice_type: list[str] | None = Query(None, max_length=100), source: str = "",
               date_from: date | None = None, date_to: date | None = None,
               scope: Literal["all", "title"] = "all", tracked: bool = False, industry: str = "", category: str = "",
               availability: Literal["active", "open", "unknown", "closed", "all"] = "active",
               refine: str = Query("", max_length=300)):
        if date_from and date_to and date_from > date_to:
            raise ValueError("开始日期不能晚于结束日期")
        rows = store.search(q, region, notice_type, source, str(date_from or ""), str(date_to or ""),
                            scope, 10000, 0, tracked, industry, category, availability, refine)["items"]
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(["标题", "地区", "行业（可人工校正）", "采购类别", "类型", "来源", "发布日期", "预算", "采购人", "阶段", "负责人", "原文", "截止时间（无时区按北京时间）", "截止状态"])
        for row in rows:
            values = [str(row.get(k) or "") for k in ("title", "region", "industry", "category", "notice_type", "source",
                      "published_at", "budget", "purchaser", "stage", "owner", "url", "deadline", "availability_label")]
            writer.writerow(["'" + v if v.lstrip().startswith(("=", "+", "-", "@")) else v for v in values])
        return Response("\ufeff" + stream.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": "attachment; filename=bidmonitor-projects.csv"})

    @app.post("/api/projects", status_code=201)
    def add_project(body: ProjectInput):
        key, created = store.upsert_project(body.model_dump())
        return {"project": get_project(key), "created": created}

    @app.get("/api/projects/{key}")
    def detail(key: str):
        return get_project(key)

    @app.patch("/api/projects/{key}")
    def edit_project(key: str, body: ProjectInput):
        get_project(key)
        return {"project": store.edit_project(key, body.model_dump()), "created": False}

    @app.post("/api/projects/{key}/detail")
    def refresh_detail(key: str):
        project = get_project(key)
        if not project["url"]:
            raise ValueError("此项目未填写原文链接")
        try:
            data = fetch_detail(project["url"])
            store.set_detail(key, data)
        except Exception as error:
            message = str(error) if isinstance(error, ValueError) else "详情采集失败，请稍后重试或打开原文"
            store.set_detail(key, error=message)
            raise HTTPException(502, message) from error
        return get_project(key)

    @app.post("/api/projects/{key}/lead")
    def convert(key: str, body: OwnerInput):
        lead, created = store.create_lead(key, body.owner)
        return {"id": lead, "created": created, "project": get_project(key)}

    @app.get("/api/leads")
    def leads(owner: str = "", stage: str = "", q: str = "", due: bool = False):
        rows = store.leads(owner, stage, q, due)
        return {"items": rows, "total": len(rows)}

    @app.patch("/api/leads/{key}")
    def edit_lead(key: str, body: LeadInput):
        return store.update_lead(key, body.model_dump(exclude={"version"}), body.version)

    @app.post("/api/leads/{key}/notes", status_code=201)
    def add_note(key: str, body: NoteInput):
        store.add_note(key, body.body)
        return {"saved": True}

    @app.post("/api/members", status_code=201)
    def add_member(body: MemberInput):
        store.add_member(body.name)
        return {"members": store.meta()["members"]}

    @app.get("/api/sources")
    def sources():
        return {"items": collector.sources()}

    @app.patch("/api/sources/{key}")
    def configure_source(key: str, body: SourceInput):
        return collector.enable(key, body.enabled)

    @app.post("/api/sources/{key}/collect")
    def collect_one(key: str):
        return collector.start(key)

    @app.get("/api/schedule")
    def schedule():
        return collector.schedule_snapshot()

    @app.put("/api/schedule")
    def configure_schedule(body: ScheduleInput):
        return collector.configure(**body.model_dump())

    @app.post("/api/collect")
    def start_collection():
        return collector.start()

    @app.post("/api/collect/provincial")
    def collect_provincial():
        return collector.start(provincial=True)

    @app.post("/api/collect/stop")
    def stop_collection():
        collector.stop.set()
        return {"message": "已请求停止，当前网页请求结束后生效"}

    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")
    return app


app = create_app()
