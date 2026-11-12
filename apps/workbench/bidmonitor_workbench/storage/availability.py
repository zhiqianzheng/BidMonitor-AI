"""Time-sensitive announcement visibility, independent of the computer timezone."""
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache


CHINA_TIME = timezone(timedelta(hours=8))
ENDED_TYPES = frozenset({"中标候选", "中标候选人公示", "中标结果", "结果公告",
                         "废标终止", "合同公告", "验收公告", "开标记录"})
ENDED_TITLE = re.compile(
    r"(?:中标|成交)(?:候选|结果|公告|公示|通知)|(?:废标|流标|终止|取消采购)(?:公告|公示|通知)"
    r"|结果(?:公告|公示)|交易证明书|合同(?:公告|公示|签订)|合同$|的合同[-－].*公告"
    r"|履约验收|验收(?:公告|结果)|开标(?:记录|情况)")
LABELS = {"open": "未截止", "unknown": "截止待核实", "expired": "已截止", "ended": "已结束"}


@lru_cache(maxsize=8192)
def deadline_boundary(value):
    """Return an aware cutoff; date-only deadlines expire at next China midnight."""
    value = (value or "").strip()
    if not value:
        return None
    value = re.sub(r"[（(]北京时间[）)]", "", value).strip().replace("：", ":")
    value = value.replace("年", "-").replace("月", "-").replace("日", " ")
    value = value.replace("/", "-").replace(".", "-", 2) if re.match(r"^\d{4}[/.]", value) else value
    value = re.sub(r"(\d{1,2})时(\d{1,2})分(?:(\d{1,2})秒)?",
                   lambda m: f"{int(m[1]):02d}:{int(m[2]):02d}" + (f":{int(m[3]):02d}" if m[3] else ""), value).strip()
    try:
        if re.fullmatch(r"\d{14}", value):
            parsed = datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=CHINA_TIME)
        elif re.fullmatch(r"\d{8}", value):
            parsed = datetime.strptime(value, "%Y%m%d").replace(tzinfo=CHINA_TIME) + timedelta(days=1)
        else:
            value = re.sub(r"^(\d{4})-(\d{1,2})-(\d{1,2})",
                           lambda m: f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}", value)
            date_only = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value))
            value = re.sub(r"\s+", " ", value)
            value = re.sub(r" (\d):", r" 0\1:", value)
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=CHINA_TIME)
            if date_only:
                parsed += timedelta(days=1)
        # Some feeds use epoch placeholders when the source omitted a deadline.
        return parsed if parsed.year >= 2000 else None
    except (ValueError, OverflowError):
        return None


def availability_state(deadline, notice_type, title, checked_at):
    if notice_type in ENDED_TYPES or ENDED_TITLE.search(title or ""):
        return "ended"
    boundary = deadline_boundary(deadline)
    if boundary is None:
        return "unknown"
    return "expired" if boundary <= checked_at else "open"


def availability_fields(project, checked_at):
    state = availability_state(project.get("deadline"), project.get("notice_type"), project.get("title"), checked_at)
    return {"availability": state, "availability_label": LABELS[state]}
