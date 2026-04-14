import json
import hashlib
import logging
import os
import asyncio
import io
import importlib
import re
import time
from pathlib import Path
from datetime import datetime, timezone
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Literal, Optional

from dotenv import load_dotenv
import httpx
from bs4 import BeautifulSoup

from app.agents.regulation_workflow import run_regulation_workflow
from app.agents.adu_chat_workflow import run_adu_chat_workflow
from app.rag_langchain import LangChainRagIndex

try:
    from openai import AsyncAzureOpenAI, AsyncOpenAI
except Exception:  # pragma: no cover - optional dependency
    AsyncOpenAI = None
    AsyncAzureOpenAI = None

load_dotenv()

log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=log_level, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("adu_backend")

app = FastAPI()

DEFAULT_LEGINFO_SEARCH_URL = os.getenv(
    "REGULATIONS_SEARCH_URL",
    "https://leginfo.legislature.ca.gov/faces/billSearchClient.xhtml?author=All&lawCode=All&session_year=20252026&keyword=ADU&house=Both",
)
DEFAULT_HANDBOOK_SOURCE_URL = os.getenv(
    "HANDBOOK_SOURCE_URL",
    "https://www.hcd.ca.gov/sites/default/files/docs/policy-and-research/adu-handbook-update.pdf",
)
ENABLE_WEEKLY_REGULATION_SYNC = os.getenv("ENABLE_WEEKLY_REGULATION_SYNC", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
WEEKLY_REGULATION_SYNC_INTERVAL_HOURS = int(os.getenv("WEEKLY_REGULATION_SYNC_INTERVAL_HOURS", "168"))
WEEKLY_REGULATION_SYNC_MAX_BILLS = int(os.getenv("WEEKLY_REGULATION_SYNC_MAX_BILLS", "50"))
WEEKLY_REGULATION_SYNC_URL = os.getenv("WEEKLY_REGULATION_SYNC_URL", DEFAULT_LEGINFO_SEARCH_URL)
ENABLE_WEEKLY_HANDBOOK_SYNC = os.getenv("ENABLE_WEEKLY_HANDBOOK_SYNC", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
WEEKLY_HANDBOOK_SYNC_INTERVAL_HOURS = int(os.getenv("WEEKLY_HANDBOOK_SYNC_INTERVAL_HOURS", "168"))
WEEKLY_HANDBOOK_SYNC_URL = os.getenv("WEEKLY_HANDBOOK_SYNC_URL", DEFAULT_HANDBOOK_SOURCE_URL)
CHAT_CONTEXT_BILL_LIMIT = int(os.getenv("CHAT_CONTEXT_BILL_LIMIT", "3"))
CHAT_CONTEXT_HANDBOOK_MAX_CHARS = int(os.getenv("CHAT_CONTEXT_HANDBOOK_MAX_CHARS", "1500"))
CHAT_CONTEXT_BILL_EXCERPT_MAX_CHARS = int(os.getenv("CHAT_CONTEXT_BILL_EXCERPT_MAX_CHARS", "350"))
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "5"))
ENABLE_CHAT_AGENT_PIPELINE = os.getenv("ENABLE_CHAT_AGENT_PIPELINE", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ENABLE_RAG_BOOTSTRAP_ON_STARTUP = os.getenv("ENABLE_RAG_BOOTSTRAP_ON_STARTUP", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ENABLE_HTTP_REQUEST_LOGS = os.getenv("ENABLE_HTTP_REQUEST_LOGS", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
RAG_INDEX_BILLS = LangChainRagIndex(DATA_DIR, index_name="bills")
RAG_INDEX_HANDBOOK = LangChainRagIndex(DATA_DIR, index_name="handbook")
REGULATION_SOURCES_PATH = DATA_DIR / "regulation_sources.json"

DEFAULT_REGULATION_SOURCES = [
    {
        "id": "bills",
        "name": "California ADU Bills",
        "source_type": "bills",
        "enabled": True,
        "search_url": DEFAULT_LEGINFO_SEARCH_URL,
        "max_bills": 50,
    },
    {
        "id": "handbook",
        "name": "California ADU Handbook",
        "source_type": "handbook",
        "enabled": True,
        "source_url": DEFAULT_HANDBOOK_SOURCE_URL,
    },
]

frontend_origins = os.getenv("FRONTEND_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in frontend_origins if origin.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    if not ENABLE_HTTP_REQUEST_LOGS:
        return await call_next(request)

    request_id = uuid.uuid4().hex[:12]
    started = time.perf_counter()
    logger.info("http_request start id=%s method=%s path=%s", request_id, request.method, request.url.path)

    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "http_request failed id=%s method=%s path=%s duration_ms=%.1f",
            request_id,
            request.method,
            request.url.path,
            (time.perf_counter() - started) * 1000,
        )
        raise

    duration_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "http_request end id=%s method=%s path=%s status=%d duration_ms=%.1f",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    response.headers["x-request-id"] = request_id
    return response

SYSTEM_PROMPT = """You are an expert California ADU (Accessory Dwelling Unit) regulation assistant for city planners.
You have comprehensive knowledge of California ADU laws, including recent updates effective January 1, 2024.

KEY REGULATIONS YOU KNOW:

HEIGHT REGULATIONS (v3.2):
- Detached ADUs: Maximum 16 feet in height
- Attached ADUs: Maximum 25 feet or the height of the primary dwelling, whichever is lower
- Two-story ADUs are permitted in most zones
- ADUs within 1/2 mile of transit: May be up to 18 feet

SETBACK REQUIREMENTS (v2.8):
- Side and rear setbacks: 4 feet minimum
- No setback required for: conversions of existing structures, new construction in same location/dimensions as existing structure
- Front setback: Must comply with underlying zone requirements
- Fire safety setbacks may apply in high fire hazard zones

FLOOR AREA LIMITS (v4.0):
- Detached ADU: Up to 1,200 sq ft regardless of primary dwelling size
- Attached ADU: Up to 1,000 sq ft or 50% of primary dwelling floor area, whichever is less
- Junior ADU (JADU): Maximum 500 sq ft, must be within primary dwelling
- Minimum ADU size: No state minimum, local minimums may apply (typically 150-200 sq ft)

DESIGN STANDARDS (v1.5):
- Garage doors: Single-car max 9 feet height, double-car max 8 feet
- Must be compatible with primary dwelling architectural style
- Separate entrance required for ADU
- Parking: Generally 1 space per ADU, but NO parking required if within 1/2 mile of transit

RECENT CHANGES (effective 2024):
- AB 1033: ADUs may be sold separately as condominiums (with local opt-in)
- SB 897: Increased height limits for ADUs near transit
- Local impact fees limited for ADUs under 750 sq ft

When answering:
1. Always cite the specific regulation version (e.g., "Per Height Regulations v3.2...")
2. Provide clear, actionable guidance
3. Note when a question requires project-specific details
4. Mention if local ordinances may have additional requirements
5. Be concise but thorough

Format your responses clearly with the relevant regulation version referenced."""


class MessagePart(BaseModel):
    type: str
    text: Optional[str] = None


class UIMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: Optional[str] = None
    parts: Optional[List[MessagePart]] = None
    data: Optional[dict] = None


class ChatRequest(BaseModel):
    messages: List[UIMessage]
    data: Optional[dict] = None
    use_live_updates: bool = False
    use_agent_pipeline: bool = False
    search_url: Optional[str] = None
    max_bills: Optional[int] = None


class RegulationIngestRequest(BaseModel):
    source_url: str
    raw_text: Optional[str] = None


class RegulationSearchIngestRequest(BaseModel):
    search_url: str
    max_bills: int = 50


class RegulationHandbookIngestRequest(BaseModel):
    source_url: str = DEFAULT_HANDBOOK_SOURCE_URL


class RegulationWorkflowRequest(BaseModel):
    search_url: str
    max_bills: int = 50


class RagReindexRequest(BaseModel):
    include_handbook: bool = True
    include_bills: bool = True


class RegulationSource(BaseModel):
    id: str
    name: str
    source_type: Literal["bills", "handbook"]
    enabled: bool = True
    search_url: Optional[str] = None
    max_bills: Optional[int] = None
    source_url: Optional[str] = None


class RegulationSourceListUpsertRequest(BaseModel):
    sources: List[RegulationSource]


class RegulationSyncSelectedRequest(BaseModel):
    source_ids: List[str]


class RegulationSnapshot(BaseModel):
    id: str
    source_url: str
    fetched_at: str
    version: int
    content_hash: str
    content_text: str
    bill_id: Optional[str] = None
    bill_title: Optional[str] = None
    bill_url: Optional[str] = None
    is_passed: Optional[bool] = None
    change_summary: Optional[str] = None


class RegulationSnapshotMeta(BaseModel):
    id: str
    source_url: str
    fetched_at: str
    version: int
    content_hash: str
    bill_id: Optional[str] = None
    bill_title: Optional[str] = None
    bill_url: Optional[str] = None
    is_passed: Optional[bool] = None
    change_summary: Optional[str] = None


class RegulationView(BaseModel):
    id: str
    title: str
    category: Literal["height", "setback", "design", "general"]
    content: str
    effectiveDate: str
    version: str
    source: str
    sourceUrl: Optional[str] = None
    lastUpdated: str


class RegulationSyncStatus(BaseModel):
    lastRunAt: Optional[str] = None
    lastSuccessAt: Optional[str] = None
    lastError: Optional[str] = None
    searchUrl: Optional[str] = None
    maxBills: Optional[int] = None
    stats: Optional[dict] = None
    schedulerEnabled: Optional[bool] = None
    schedulerIntervalHours: Optional[int] = None


class RegulationChangeView(BaseModel):
    id: str
    regulationId: str
    title: str
    changeType: Literal["new", "amended", "repealed"]
    summary: str
    previousVersion: str
    newVersion: str
    effectiveDate: str
    impactLevel: Literal["high", "medium", "low"]
    affectedApplications: int
    createdAt: str
    isRead: bool


class AuditEntryView(BaseModel):
    id: str
    action: str
    regulationId: str
    regulationTitle: str
    previousVersion: str
    newVersion: str
    timestamp: str
    user: str
    details: str


weekly_sync_task: Optional[asyncio.Task] = None
weekly_handbook_sync_task: Optional[asyncio.Task] = None
rag_bootstrap_task: Optional[asyncio.Task] = None


def _extract_text(message: UIMessage) -> str:
    if message.content:
        return message.content
    if not message.parts:
        return ""
    return "".join(part.text or "" for part in message.parts if part.type == "text")


def _format_sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=True)}\n\n"


def _format_sse_done() -> str:
    return "data: [DONE]\n\n"


def _snapshot_file_path(source_url: str) -> Path:
    digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:16]
    return DATA_DIR / f"regulations_{digest}.jsonl"


def _sync_status_path() -> Path:
    return DATA_DIR / "sync_status.json"


def _handbook_sync_status_path() -> Path:
    return DATA_DIR / "handbook_sync_status.json"


def _read_sync_status() -> RegulationSyncStatus:
    path = _sync_status_path()
    if not path.exists():
        return RegulationSyncStatus()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return RegulationSyncStatus(**raw)
    except Exception:
        return RegulationSyncStatus()


def _write_sync_status(status: RegulationSyncStatus) -> None:
    path = _sync_status_path()
    path.write_text(json.dumps(status.model_dump(), ensure_ascii=True), encoding="utf-8")


def _read_handbook_sync_status() -> RegulationSyncStatus:
    path = _handbook_sync_status_path()
    if not path.exists():
        return RegulationSyncStatus()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return RegulationSyncStatus(**raw)
    except Exception:
        return RegulationSyncStatus()


def _write_handbook_sync_status(status: RegulationSyncStatus) -> None:
    path = _handbook_sync_status_path()
    path.write_text(json.dumps(status.model_dump(), ensure_ascii=True), encoding="utf-8")


def _ensure_regulation_sources() -> List[RegulationSource]:
    if not REGULATION_SOURCES_PATH.exists():
        defaults = [RegulationSource(**item) for item in DEFAULT_REGULATION_SOURCES]
        REGULATION_SOURCES_PATH.write_text(
            json.dumps([item.model_dump() for item in defaults], ensure_ascii=True),
            encoding="utf-8",
        )
        return defaults

    try:
        raw = json.loads(REGULATION_SOURCES_PATH.read_text(encoding="utf-8"))
        sources = [RegulationSource(**item) for item in raw]
        if not sources:
            raise ValueError("empty sources")

        by_id = {source.id: source for source in sources}
        updated = False
        for default_item in DEFAULT_REGULATION_SOURCES:
            default_source = RegulationSource(**default_item)
            if default_source.id not in by_id:
                sources.append(default_source)
                updated = True

        if updated:
            _write_regulation_sources(sources)
            return _ensure_regulation_sources()

        return sources
    except Exception:
        defaults = [RegulationSource(**item) for item in DEFAULT_REGULATION_SOURCES]
        REGULATION_SOURCES_PATH.write_text(
            json.dumps([item.model_dump() for item in defaults], ensure_ascii=True),
            encoding="utf-8",
        )
        return defaults


def _write_regulation_sources(sources: List[RegulationSource]) -> None:
    deduped: dict[str, RegulationSource] = {}
    for source in sources:
        deduped[source.id] = source
    REGULATION_SOURCES_PATH.write_text(
        json.dumps([item.model_dump() for item in deduped.values()], ensure_ascii=True),
        encoding="utf-8",
    )


async def _sync_selected_sources(source_ids: List[str]) -> dict:
    configured_sources = _ensure_regulation_sources()
    configured_map = {source.id: source for source in configured_sources}
    selected = [configured_map[source_id] for source_id in source_ids if source_id in configured_map]

    if not selected:
        raise HTTPException(status_code=400, detail="No valid source ids selected")

    results: List[dict] = []
    for source in selected:
        if not source.enabled:
            results.append({"source_id": source.id, "source_type": source.source_type, "status": "skipped", "reason": "disabled"})
            continue

        if source.source_type == "bills":
            search_url = source.search_url or DEFAULT_LEGINFO_SEARCH_URL
            max_bills = source.max_bills or 50
            bill_result = await _run_regulations_workflow(search_url, max_bills)
            results.append(
                {
                    "source_id": source.id,
                    "source_type": "bills",
                    "status": "ok",
                    "result": bill_result,
                }
            )
            continue

        if source.source_type == "handbook":
            source_url = source.source_url or DEFAULT_HANDBOOK_SOURCE_URL
            handbook_result = await _run_handbook_ingest(source_url)
            results.append(
                {
                    "source_id": source.id,
                    "source_type": "handbook",
                    "status": "ok",
                    "result": handbook_result,
                }
            )
            continue

        results.append({"source_id": source.id, "source_type": source.source_type, "status": "skipped", "reason": "unknown_source_type"})

    return {
        "selected": [source.id for source in selected],
        "results": results,
    }


def _infer_impact_level(text: str) -> Literal["high", "medium", "low"]:
    lower = text.lower()
    high_tokens = ["mandatory", "required", "prohibited", "ban", "must"]
    medium_tokens = ["updated", "changed", "amended", "clarified", "new"]
    if any(token in lower for token in high_tokens):
        return "high"
    if any(token in lower for token in medium_tokens):
        return "medium"
    return "low"


def _bill_snapshot_file_path(bill_id: str) -> Path:
    digest = hashlib.sha256(bill_id.encode("utf-8")).hexdigest()[:16]
    return DATA_DIR / f"bill_{digest}.jsonl"


def _read_snapshots(source_url: str) -> List[RegulationSnapshot]:
    path = _snapshot_file_path(source_url)
    if not path.exists():
        return []
    snapshots: List[RegulationSnapshot] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        snapshots.append(RegulationSnapshot(**json.loads(line)))
    return snapshots


def _read_bill_snapshots(bill_id: str) -> List[RegulationSnapshot]:
    path = _bill_snapshot_file_path(bill_id)
    if not path.exists():
        return []
    snapshots: List[RegulationSnapshot] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        snapshots.append(RegulationSnapshot(**json.loads(line)))
    return snapshots


def _read_latest_bill_snapshots() -> List[RegulationSnapshot]:
    snapshots: List[RegulationSnapshot] = []
    for path in DATA_DIR.glob("bill_*.jsonl"):
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            if not line.strip():
                continue
            snapshots.append(RegulationSnapshot(**json.loads(line)))
            break
    return snapshots


def _append_snapshot(snapshot: RegulationSnapshot) -> None:
    path = _snapshot_file_path(snapshot.source_url)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(snapshot.model_dump(), ensure_ascii=True))
        file.write("\n")


def _append_bill_snapshot(snapshot: RegulationSnapshot) -> None:
    if not snapshot.bill_id:
        raise ValueError("bill_id is required for bill snapshots")
    path = _bill_snapshot_file_path(snapshot.bill_id)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(snapshot.model_dump(), ensure_ascii=True))
        file.write("\n")


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _truncate_text(text: str, max_chars: int = 12000) -> str:
    if len(text) <= max_chars:
        return text
    head = text[: max_chars // 2]
    tail = text[-max_chars // 2 :]
    return f"{head}\n\n[...truncated...]\n\n{tail}"


def _build_source_fetch_headers(source_url: str) -> dict:
    user_agent = os.getenv(
        "SOURCE_FETCH_USER_AGENT",
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
    )
    return {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": source_url,
        "Connection": "keep-alive",
    }


async def _fetch_source_text(source_url: str) -> str:
    headers = _build_source_fetch_headers(source_url)
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(source_url, headers=headers)
        response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()

    if source_url.lower().endswith(".pdf") or "application/pdf" in content_type:
        pypdf_module = importlib.util.find_spec("pypdf")
        if pypdf_module is None:
            raise HTTPException(status_code=500, detail="pypdf package is not installed")
        PdfReader = importlib.import_module("pypdf").PdfReader
        reader = PdfReader(io.BytesIO(response.content))
        pages = [page.extract_text() or "" for page in reader.pages]
        page_blocks: List[str] = []
        for index, page_text in enumerate(pages, start=1):
            normalized = page_text.strip()
            if not normalized:
                continue
            page_blocks.append(f"[PAGE {index}]\n{normalized}")
        return "\n\n".join(page_blocks)

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return " ".join(soup.stripped_strings)


async def _fetch_html(source_url: str) -> str:
    headers = _build_source_fetch_headers(source_url)
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(source_url, headers=headers)
        response.raise_for_status()
        return response.text


def _absolute_url(href: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return f"https://leginfo.legislature.ca.gov{href}"


def _parse_bill_search_results(html: str, max_bills: int) -> List[dict]:
    soup = BeautifulSoup(html, "html.parser")
    bills: List[dict] = []
    for link in soup.select('a[href*="billTextClient.xhtml?bill_id="]'):
        href = link.get("href")
        if not href:
            continue
        bill_url = _absolute_url(href)
        bill_id = None
        if "bill_id=" in href:
            bill_id = href.split("bill_id=")[-1].split("&")[0]
        bill_title = " ".join(link.stripped_strings)
        bills.append(
            {
                "bill_id": bill_id,
                "bill_url": bill_url,
                "bill_title": bill_title,
            }
        )
        if len(bills) >= max_bills:
            break
    return bills


def _parse_bill_text(html: str) -> tuple[str, bool]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = " ".join(soup.stripped_strings)
    normalized = " ".join(text.lower().split())
    is_passed = "approved by governor" in normalized
    return text, is_passed


def _infer_category(text: str) -> Literal["height", "setback", "design", "general"]:
    normalized = text.lower()
    if "height" in normalized or "story" in normalized or "feet" in normalized:
        return "height"
    if "setback" in normalized or "rear" in normalized or "side" in normalized:
        return "setback"
    if "design" in normalized or "architect" in normalized or "garage" in normalized:
        return "design"
    return "general"


def _write_debug_bill_text(bill_id: str, bill_text: str) -> None:
    safe_id = "".join(ch for ch in bill_id if ch.isalnum() or ch in ("-", "_"))
    if not safe_id:
        safe_id = "unknown"
    path = LOG_DIR / f"bill_{safe_id}.txt"
    path.write_text(bill_text, encoding="utf-8")


def _extract_handbook_pages_from_text(content_text: str) -> List[dict]:
    pattern = re.compile(r"\[PAGE\s+(\d+)\]\s*", re.IGNORECASE)
    matches = list(pattern.finditer(content_text or ""))
    if not matches:
        return []

    pages: List[dict] = []
    for index, match in enumerate(matches):
        page_number = int(match.group(1))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content_text)
        text = (content_text[start:end] or "").strip()
        if not text:
            continue
        pages.append({"page_number": page_number, "text": text})
    return pages


def _index_snapshot(snapshot: RegulationSnapshot) -> None:
    source_type = "bill" if snapshot.bill_id and snapshot.bill_id != "CA-ADU-HANDBOOK" else "handbook"
    doc_id = snapshot.bill_id or f"source::{snapshot.source_url}"
    source_title = snapshot.bill_title or ("California ADU Handbook" if source_type == "handbook" else "ADU Regulation")
    source_url = snapshot.bill_url or snapshot.source_url
    text = snapshot.change_summary or snapshot.content_text

    target_index = RAG_INDEX_HANDBOOK if source_type == "handbook" else RAG_INDEX_BILLS
    if source_type == "handbook":
        page_segments = _extract_handbook_pages_from_text(snapshot.content_text)
        if page_segments:
            target_index.upsert_document_segments(
                doc_id=doc_id,
                source_type=source_type,
                source_title=source_title,
                source_url=source_url,
                version=str(snapshot.version),
                fetched_at=snapshot.fetched_at,
                segments=page_segments,
            )
            return

    target_index.upsert_document(
        doc_id=doc_id,
        source_type=source_type,
        source_title=source_title,
        source_url=source_url,
        version=str(snapshot.version),
        fetched_at=snapshot.fetched_at,
        text=text,
    )


def _bootstrap_rag_index(include_handbook: bool = True, include_bills: bool = True) -> dict:
    indexed_docs = 0

    if include_handbook:
        handbook_status = RAG_INDEX_HANDBOOK.status()
        if handbook_status.get("total_chunks", 0) > 0:
            RAG_INDEX_HANDBOOK.rebuild_from_manifest()

    if include_bills:
        bills_status = RAG_INDEX_BILLS.status()
        if bills_status.get("total_chunks", 0) > 0:
            RAG_INDEX_BILLS.rebuild_from_manifest()

    if include_handbook:
        handbook_source_url = _read_handbook_sync_status().searchUrl or DEFAULT_HANDBOOK_SOURCE_URL
        handbook_snapshots = _read_snapshots(handbook_source_url)
        if handbook_snapshots:
            _index_snapshot(handbook_snapshots[-1])
            indexed_docs += 1

    if include_bills:
        bill_snapshots = [snapshot for snapshot in _read_latest_bill_snapshots() if snapshot.is_passed]
        for snapshot in bill_snapshots:
            _index_snapshot(snapshot)
            indexed_docs += 1

    return {
        "indexed_docs": indexed_docs,
        "index_status": _rag_status_payload(),
    }


async def _bootstrap_rag_index_background() -> None:
    try:
        logger.info("RAG bootstrap started")
        bootstrap = await asyncio.to_thread(_bootstrap_rag_index, True, True)
        logger.info(
            "RAG bootstrap completed indexed_docs=%d total_chunks=%d ready=%s",
            bootstrap["indexed_docs"],
            bootstrap["index_status"].get("total_chunks", 0),
            bootstrap["index_status"].get("is_ready", False),
        )
    except Exception:
        logger.exception("RAG bootstrap failed")


def _rag_status_payload() -> dict:
    bills_status = RAG_INDEX_BILLS.status()
    handbook_status = RAG_INDEX_HANDBOOK.status()

    source_type_counts: dict[str, int] = {}
    for status in (bills_status, handbook_status):
        for key, value in status.get("source_type_counts", {}).items():
            source_type_counts[key] = source_type_counts.get(key, 0) + int(value)

    last_errors = [status.get("last_error") for status in (bills_status, handbook_status) if status.get("last_error")]

    return {
        "total_chunks": int(bills_status.get("total_chunks", 0)) + int(handbook_status.get("total_chunks", 0)),
        "source_type_counts": source_type_counts,
        "is_ready": bool(bills_status.get("is_ready") or handbook_status.get("is_ready")),
        "embedding_provider": {
            "bills": bills_status.get("embedding_provider"),
            "handbook": handbook_status.get("embedding_provider"),
        },
        "last_error": " | ".join(last_errors) if last_errors else None,
        "indexes": {
            "bills": bills_status,
            "handbook": handbook_status,
        },
    }


def _build_rag_context(query_text: str, top_k: int = RAG_TOP_K) -> str:
    bill_results = RAG_INDEX_BILLS.search(query_text, top_k=top_k)
    handbook_results = RAG_INDEX_HANDBOOK.search(query_text, top_k=top_k)
    results = sorted(
        [*bill_results, *handbook_results],
        key=lambda item: item.get("score", 0.0),
        reverse=True,
    )[:top_k]
    if not results:
        return "No relevant indexed regulation chunks found."

    lines: List[str] = ["Retrieved regulation context (RAG):"]
    for idx, item in enumerate(results, start=1):
        lines.append(
            f"{idx}. [{item['source_type']}] {item['source_title']} | v{item['version']} | fetched {item['fetched_at']} | score {item['score']:.3f}"
        )
        source_url = item.get("source_url") or "N/A"
        page_number = item.get("page_number")
        if page_number:
            lines.append(f"   Source: {source_url} (page {page_number})")
        else:
            lines.append(f"   Source: {source_url}")
        lines.append(f"   Excerpt: {item['text']}")

    lines.append("")
    lines.append("Citation requirements for final answer:")
    lines.append("- Label Primary source with direct URL; include page number when available.")
    lines.append("- Label Applied updates with bill IDs/titles and direct URL references.")
    return "\n".join(lines)


def _get_llm_client():
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    azure_key = os.getenv("AZURE_OPENAI_API_KEY")
    azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    azure_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

    if azure_endpoint and azure_key and azure_deployment and AsyncAzureOpenAI is not None:
        model = azure_deployment
        client = AsyncAzureOpenAI(
            azure_endpoint=azure_endpoint,
            api_key=azure_key,
            api_version=azure_api_version,
        )
        logger.info("Using Azure OpenAI deployment=%s", azure_deployment)
        return client, model

    model = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    client = AsyncOpenAI(
        base_url=os.getenv("OPENAI_API_BASE_URL"),
        api_key=os.getenv("OPENAI_API_KEY"),
    )
    logger.info("Using OpenAI-compatible model=%s", model)
    return client, model


async def _run_regulation_search_ingest(search_url: str, max_bills: int) -> dict:
    logger.info("Regulation search ingest url=%s", search_url)
    run_started_at = datetime.now(timezone.utc).isoformat()

    try:
        search_html = await _fetch_html(search_url)
        bills = _parse_bill_search_results(search_html, max_bills)

        results: List[dict] = []
        parsed_count = 0
        skipped_count = 0
        saved_count = 0
        error_count = 0
        for bill in bills:
            bill_id = bill.get("bill_id")
            bill_url = bill.get("bill_url")
            bill_title = bill.get("bill_title")
            if not bill_id or not bill_url:
                continue

            try:
                bill_html = await _fetch_html(bill_url)
                bill_text, is_passed = _parse_bill_text(bill_html)
                parsed_count += 1
                _write_debug_bill_text(bill_id, bill_text)
            except Exception as exc:
                logger.exception("Failed to fetch bill id=%s", bill_id)
                error_count += 1
                results.append({"bill_id": bill_id, "status": "error", "error": str(exc)})
                continue

            if not is_passed:
                skipped_count += 1
                results.append({"bill_id": bill_id, "status": "skipped", "reason": "not_passed"})
                continue

            content_hash = _hash_text(bill_text)
            snapshots = _read_bill_snapshots(bill_id)
            latest = snapshots[-1] if snapshots else None
            if latest and latest.content_hash == content_hash:
                results.append({"bill_id": bill_id, "status": "no_change"})
                continue

            change_summary: Optional[str] = None
            if latest:
                client, model = _get_llm_client()
                prompt = (
                    "Compare the previous and current ADU regulation bill text. "
                    "Summarize only the substantive changes in 3-6 bullet points. "
                    "If changes are unclear, say so."
                )
                previous_text = _truncate_text(latest.content_text)
                current_text = _truncate_text(bill_text)
                completion = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": f"PREVIOUS:\n{previous_text}\n\nCURRENT:\n{current_text}"},
                    ],
                )
                change_summary = completion.choices[0].message.content or None

            snapshot = RegulationSnapshot(
                id=uuid.uuid4().hex,
                source_url=search_url,
                fetched_at=datetime.now(timezone.utc).isoformat(),
                version=(latest.version + 1) if latest else 1,
                content_hash=content_hash,
                content_text=bill_text,
                bill_id=bill_id,
                bill_title=bill_title,
                bill_url=bill_url,
                is_passed=is_passed,
                change_summary=change_summary,
            )
            _append_bill_snapshot(snapshot)
            _index_snapshot(snapshot)
            saved_count += 1
            results.append({"bill_id": bill_id, "status": "updated"})

        logger.info(
            "Search ingest stats parsed=%d saved=%d skipped=%d errors=%d",
            parsed_count,
            saved_count,
            skipped_count,
            error_count,
        )
        result = {
            "search_url": search_url,
            "count": len(results),
            "results": results,
            "stats": {
                "parsed": parsed_count,
                "saved": saved_count,
                "skipped": skipped_count,
                "errors": error_count,
            },
        }
        _write_sync_status(
            RegulationSyncStatus(
                lastRunAt=run_started_at,
                lastSuccessAt=datetime.now(timezone.utc).isoformat(),
                lastError=None,
                searchUrl=search_url,
                maxBills=max_bills,
                stats=result["stats"],
            )
        )
        return result
    except Exception as exc:
        _write_sync_status(
            RegulationSyncStatus(
                lastRunAt=run_started_at,
                lastSuccessAt=_read_sync_status().lastSuccessAt,
                lastError=str(exc),
                searchUrl=search_url,
                maxBills=max_bills,
            )
        )
        raise


async def _run_handbook_ingest(source_url: str) -> dict:
    logger.info("Handbook ingest source=%s", source_url)
    run_started_at = datetime.now(timezone.utc).isoformat()
    try:
        content_text = await _fetch_source_text(source_url)
        content_text = content_text.strip()
        if not content_text:
            raise HTTPException(status_code=400, detail="No content extracted from handbook source")

        content_hash = _hash_text(content_text)
        snapshots = _read_snapshots(source_url)
        latest = snapshots[-1] if snapshots else None
        if latest and latest.content_hash == content_hash:
            _write_handbook_sync_status(
                RegulationSyncStatus(
                    lastRunAt=run_started_at,
                    lastSuccessAt=datetime.now(timezone.utc).isoformat(),
                    lastError=None,
                    searchUrl=source_url,
                    stats={"saved": 0, "no_change": 1},
                )
            )
            return {"status": "no_change", "latest": RegulationSnapshotMeta(**latest.model_dump())}

        change_summary: Optional[str] = None
        if latest:
            client, model = _get_llm_client()
            prompt = (
                "Compare the previous and current California ADU handbook text. "
                "Summarize substantive changes in 4-8 bullet points for planners."
            )
            previous_text = _truncate_text(latest.content_text)
            current_text = _truncate_text(content_text)
            completion = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": f"PREVIOUS:\n{previous_text}\n\nCURRENT:\n{current_text}"},
                ],
            )
            change_summary = completion.choices[0].message.content or None

        snapshot = RegulationSnapshot(
            id=uuid.uuid4().hex,
            source_url=source_url,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            version=(latest.version + 1) if latest else 1,
            content_hash=content_hash,
            content_text=content_text,
            bill_id="CA-ADU-HANDBOOK",
            bill_title="California ADU Handbook",
            bill_url=source_url,
            is_passed=True,
            change_summary=change_summary,
        )
        _append_snapshot(snapshot)
        _index_snapshot(snapshot)

        _write_handbook_sync_status(
            RegulationSyncStatus(
                lastRunAt=run_started_at,
                lastSuccessAt=datetime.now(timezone.utc).isoformat(),
                lastError=None,
                searchUrl=source_url,
                stats={"saved": 1, "no_change": 0},
            )
        )
        return {"status": "updated", "snapshot": RegulationSnapshotMeta(**snapshot.model_dump())}
    except Exception as exc:
        _write_handbook_sync_status(
            RegulationSyncStatus(
                lastRunAt=run_started_at,
                lastSuccessAt=_read_handbook_sync_status().lastSuccessAt,
                lastError=str(exc),
                searchUrl=source_url,
            )
        )
        raise


async def _run_regulations_workflow(search_url: str, max_bills: int) -> dict:
    if AsyncOpenAI is None and AsyncAzureOpenAI is None:
        raise HTTPException(status_code=500, detail="openai package is not installed")

    workflow_result = await run_regulation_workflow(
        _run_regulation_search_ingest,
        search_url,
        max_bills,
    )

    result_payload = workflow_result.get("result") if isinstance(workflow_result, dict) else None
    if isinstance(result_payload, dict):
        sync_result = result_payload.get("sync_result")
        if isinstance(sync_result, dict):
            return sync_result

    return workflow_result


async def _weekly_regulation_sync_loop() -> None:
    interval_seconds = max(1, WEEKLY_REGULATION_SYNC_INTERVAL_HOURS) * 3600
    logger.info(
        "Weekly regulation sync loop started interval_hours=%d max_bills=%d",
        WEEKLY_REGULATION_SYNC_INTERVAL_HOURS,
        WEEKLY_REGULATION_SYNC_MAX_BILLS,
    )
    while True:
        try:
            await _run_regulation_search_ingest(
                WEEKLY_REGULATION_SYNC_URL,
                WEEKLY_REGULATION_SYNC_MAX_BILLS,
            )
            logger.info("Weekly regulation sync run completed")
        except Exception:
            logger.exception("Weekly regulation sync run failed")

        await asyncio.sleep(interval_seconds)


async def _weekly_handbook_sync_loop() -> None:
    interval_seconds = max(1, WEEKLY_HANDBOOK_SYNC_INTERVAL_HOURS) * 3600
    logger.info(
        "Weekly handbook sync loop started interval_hours=%d",
        WEEKLY_HANDBOOK_SYNC_INTERVAL_HOURS,
    )
    while True:
        try:
            await _run_handbook_ingest(WEEKLY_HANDBOOK_SYNC_URL)
            logger.info("Weekly handbook sync run completed")
        except Exception:
            logger.exception("Weekly handbook sync run failed")

        await asyncio.sleep(interval_seconds)


@app.on_event("startup")
async def on_startup() -> None:
    global weekly_sync_task, weekly_handbook_sync_task, rag_bootstrap_task

    _ensure_regulation_sources()

    if ENABLE_RAG_BOOTSTRAP_ON_STARTUP:
        if not _rag_status_payload().get("is_ready"):
            if rag_bootstrap_task is None or rag_bootstrap_task.done():
                rag_bootstrap_task = asyncio.create_task(_bootstrap_rag_index_background())
    else:
        logger.info("RAG bootstrap on startup is disabled")

    if ENABLE_WEEKLY_REGULATION_SYNC:
        if weekly_sync_task is None or weekly_sync_task.done():
            weekly_sync_task = asyncio.create_task(_weekly_regulation_sync_loop())
            logger.info("Weekly regulation sync task created")
    else:
        logger.info("Weekly regulation sync is disabled")

    if ENABLE_WEEKLY_HANDBOOK_SYNC:
        if weekly_handbook_sync_task is None or weekly_handbook_sync_task.done():
            weekly_handbook_sync_task = asyncio.create_task(_weekly_handbook_sync_loop())
            logger.info("Weekly handbook sync task created")
    else:
        logger.info("Weekly handbook sync is disabled")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    global weekly_sync_task, weekly_handbook_sync_task, rag_bootstrap_task
    if weekly_sync_task and not weekly_sync_task.done():
        weekly_sync_task.cancel()
        try:
            await weekly_sync_task
        except asyncio.CancelledError:
            pass
        logger.info("Weekly regulation sync task cancelled")

    if weekly_handbook_sync_task and not weekly_handbook_sync_task.done():
        weekly_handbook_sync_task.cancel()
        try:
            await weekly_handbook_sync_task
        except asyncio.CancelledError:
            pass
        logger.info("Weekly handbook sync task cancelled")

    if rag_bootstrap_task and not rag_bootstrap_task.done():
        rag_bootstrap_task.cancel()
        try:
            await rag_bootstrap_task
        except asyncio.CancelledError:
            pass
        logger.info("RAG bootstrap task cancelled")


def _build_database_context(limit: int = CHAT_CONTEXT_BILL_LIMIT) -> str:
    handbook_source_url = _read_handbook_sync_status().searchUrl or DEFAULT_HANDBOOK_SOURCE_URL
    handbook_snapshots = _read_snapshots(handbook_source_url)
    latest_handbook = handbook_snapshots[-1] if handbook_snapshots else None

    snapshots = _read_latest_bill_snapshots()
    passed = [s for s in snapshots if s.is_passed]
    passed.sort(key=lambda item: item.fetched_at, reverse=True)
    selected = passed[:limit]

    lines: List[str] = []
    lines.append("Knowledge merge strategy:")
    lines.append("1) Use California ADU Handbook as the primary base source.")
    lines.append("2) Append recent enacted bill deltas as updates.")
    lines.append("3) If handbook and bill deltas conflict, enacted bill deltas override handbook text.")
    lines.append("")

    if latest_handbook:
        lines.append("Primary source (Handbook):")
        lines.append(
            f"- California ADU Handbook | fetched {latest_handbook.fetched_at} | v{latest_handbook.version} | source {latest_handbook.source_url}"
        )
        handbook_summary = latest_handbook.change_summary or _truncate_text(
            latest_handbook.content_text, max_chars=CHAT_CONTEXT_HANDBOOK_MAX_CHARS
        )
        lines.append(f"  Handbook content: {handbook_summary}")
    else:
        lines.append("Primary source (Handbook): unavailable. Use bill deltas and available ADU baseline context.")

    lines.append("")
    lines.append("Appended legislative deltas (recent bills):")
    if not selected:
        lines.append("- No saved passed-bill snapshots are available.")
    else:
        for snapshot in selected:
            title = snapshot.bill_title or snapshot.bill_id or "Unknown bill"
            lines.append(
                f"- {title} ({snapshot.bill_id or 'unknown'}) | fetched {snapshot.fetched_at} | v{snapshot.version} | source {snapshot.bill_url or 'N/A'}"
            )
            if snapshot.change_summary:
                lines.append(f"  Delta summary: {snapshot.change_summary}")
            else:
                excerpt = _truncate_text(snapshot.content_text, max_chars=CHAT_CONTEXT_BILL_EXCERPT_MAX_CHARS)
                lines.append(f"  Delta excerpt: {excerpt}")

    lines.append("")
    lines.append("Citation requirements for final answer:")
    lines.append("- Label Primary source: California ADU Handbook (version/date).")
    lines.append("- Label Applied updates: bill IDs used for overrides.")
    lines.append("- If context is insufficient, explicitly state uncertainty.")
    return "\n".join(lines)


async def _build_live_context(search_url: str, max_bills: int, limit: int = CHAT_CONTEXT_BILL_LIMIT) -> str:
    try:
        search_html = await _fetch_html(search_url)
        bills = _parse_bill_search_results(search_html, max_bills)
    except Exception as exc:
        logger.exception("Live context search failed")
        return f"Live search failed: {exc}"

    handbook_source_url = _read_handbook_sync_status().searchUrl or DEFAULT_HANDBOOK_SOURCE_URL
    handbook_snapshots = _read_snapshots(handbook_source_url)
    latest_handbook = handbook_snapshots[-1] if handbook_snapshots else None

    lines: List[str] = []
    lines.append("Knowledge merge strategy:")
    lines.append("1) Handbook is primary base source.")
    lines.append("2) Live passed bills are appended as deltas.")
    lines.append("3) Bill deltas override handbook when conflicting.")
    lines.append("")

    if latest_handbook:
        lines.append("Primary source (Handbook):")
        lines.append(
            f"- California ADU Handbook | fetched {latest_handbook.fetched_at} | v{latest_handbook.version} | source {latest_handbook.source_url}"
        )
        handbook_summary = latest_handbook.change_summary or _truncate_text(
            latest_handbook.content_text, max_chars=CHAT_CONTEXT_HANDBOOK_MAX_CHARS
        )
        lines.append(f"  Handbook content: {handbook_summary}")
        lines.append("")

    lines.append("Live appended legislative deltas:")
    added = 0
    for bill in bills:
        if added >= limit:
            break
        bill_id = bill.get("bill_id")
        bill_url = bill.get("bill_url")
        bill_title = bill.get("bill_title") or bill_id or "Unknown bill"
        if not bill_id or not bill_url:
            continue
        try:
            bill_html = await _fetch_html(bill_url)
            bill_text, is_passed = _parse_bill_text(bill_html)
        except Exception as exc:
            logger.exception("Live bill fetch failed bill_id=%s", bill_id)
            lines.append(f"- {bill_title} ({bill_id}) | fetch error: {exc}")
            added += 1
            continue

        if not is_passed:
            continue

        excerpt = _truncate_text(bill_text, max_chars=CHAT_CONTEXT_BILL_EXCERPT_MAX_CHARS)
        lines.append(f"- {bill_title} ({bill_id}) | passed | source {bill_url}")
        lines.append(f"  Delta excerpt: {excerpt}")
        added += 1

    if added == 0:
        lines.append("- No passed ADU bills found from the live search results.")

    lines.append("")
    lines.append("Citation requirements for final answer:")
    lines.append("- Label Primary source: California ADU Handbook (version/date).")
    lines.append("- Label Applied updates: bill IDs used for overrides.")

    return "\n".join(lines)


@app.post("/api/chat")
async def chat(req: ChatRequest):
    if AsyncOpenAI is None and AsyncAzureOpenAI is None:
        raise HTTPException(status_code=500, detail="openai package is not installed")

    client, model = _get_llm_client()
    request_started = time.perf_counter()
    

    data = req.data or {}
    if not data:
        for message in reversed(req.messages):
            if message.role != "user":
                continue
            if isinstance(message.data, dict) and message.data:
                data = message.data
                break
    use_live_updates = bool(data.get("use_live_updates", req.use_live_updates))
    use_agent_pipeline = bool(data.get("use_agent_pipeline", req.use_agent_pipeline or ENABLE_CHAT_AGENT_PIPELINE))
    search_url = data.get("search_url") or req.search_url or DEFAULT_LEGINFO_SEARCH_URL
    max_bills = data.get("max_bills") or req.max_bills or 25
    try:
        max_bills = int(max_bills)
    except (TypeError, ValueError):
        max_bills = 25

    logger.info(
        "Chat toggle raw use_live_updates=%s use_agent_pipeline=%s data=%s",
        req.use_live_updates,
        use_agent_pipeline,
        data,
    )

    query_text = ""
    for message in reversed(req.messages):
        if message.role != "user":
            continue
        text = _extract_text(message)
        if text:
            query_text = text
            break

    if use_live_updates:
        context_text = await _build_live_context(search_url, max_bills, limit=CHAT_CONTEXT_BILL_LIMIT)
        context_header = "Live regulation context (internet sources)"
    else:
        context_text = _build_rag_context(query_text, top_k=RAG_TOP_K)
        context_header = "Retrieved regulation context (local vector index)"

    context_ready_at = time.perf_counter()
    logger.info(
        "Chat context built mode=%s chars=%d duration_ms=%.1f",
        "live" if use_live_updates else "database",
        len(context_text),
        (context_ready_at - request_started) * 1000,
    )

    model_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "system",
            "content": (
                f"{context_header}:\n{context_text}\n\n"
                "Use the context above when answering. Always reason in handbook-first order and apply bill-delta overrides when conflicts exist. "
                "Do not include internal dataset/process commentary unless strictly needed for correctness. "
                "Use this exact response structure:\n"
                "Short answer:\n- ...\n"
                "Short reasoning:\n- ...\n"
                "Primary source: ...\n"
                "Applied updates: ...\n"
                "Actionable guidance:\n1. ...\n"
                "For Primary source and Applied updates, include clickable source URLs. Include page numbers when available from context. "
                "Keep the short answer concise and directly responsive. If uncertain, add at most one brief uncertainty sentence in Short answer."
            ),
        },
    ]
    for message in req.messages:
        text = _extract_text(message)
        if text:
            model_messages.append({"role": message.role, "content": text})

    logger.info(
        "Chat request messages=%d user_chars=%d live_updates=%s",
        len(req.messages),
        sum(len(_extract_text(m)) for m in req.messages if m.role == "user"),
        use_live_updates,
    )

    if use_agent_pipeline and query_text:
        pipeline_trace_id = uuid.uuid4().hex[:12]
        logger.info(
            "chat_agent_pipeline trace=%s start messages=%d query_chars=%d",
            pipeline_trace_id,
            len(req.messages),
            len(query_text),
        )

        conversation_lines: List[str] = []
        for message in req.messages[-8:]:
            text = _extract_text(message).strip()
            if not text:
                continue
            conversation_lines.append(f"{message.role.upper()}: {text}")
        conversation_text = "\n".join(conversation_lines)

        try:
            workflow_result = await run_adu_chat_workflow(
                system_prompt=SYSTEM_PROMPT,
                context_header=context_header,
                context_text=context_text,
                conversation_text=conversation_text,
                query_text=query_text,
                trace_id=pipeline_trace_id,
            )
            response_text = (workflow_result.get("response_text") or "").strip()

            logger.info(
                "chat_agent_pipeline trace=%s completed response_chars=%d",
                pipeline_trace_id,
                len(response_text),
            )

            if response_text:
                message_id = uuid.uuid4().hex
                text_part_id = "text-1"

                async def workflow_event_stream():
                    yield _format_sse_event({"type": "start", "messageId": message_id})
                    yield _format_sse_event({"type": "text-start", "id": text_part_id})
                    yield _format_sse_event(
                        {"type": "text-delta", "id": text_part_id, "delta": response_text}
                    )
                    yield _format_sse_event({"type": "text-end", "id": text_part_id})
                    yield _format_sse_event({"type": "finish", "finishReason": "stop"})
                    yield _format_sse_done()

                headers = {
                    "cache-control": "no-cache",
                    "connection": "keep-alive",
                    "x-vercel-ai-ui-message-stream": "v1",
                    "x-accel-buffering": "no",
                }
                logger.info("Chat served via agent workflow pipeline")
                return StreamingResponse(
                    workflow_event_stream(),
                    media_type="text/event-stream",
                    headers=headers,
                )
        except Exception:
            logger.exception(
                "Agent chat workflow failed trace=%s, falling back to standard chat completion",
                pipeline_trace_id,
            )

    stream = await client.chat.completions.create(
        model=model,
        messages=model_messages,
        stream=True,
    )

    model_stream_opened_at = time.perf_counter()
    logger.info(
        "Chat stream opened model=%s duration_ms=%.1f",
        model,
        (model_stream_opened_at - context_ready_at) * 1000,
    )

    message_id = uuid.uuid4().hex
    text_part_id = "text-1"

    async def event_stream():
        first_delta_logged = False
        try:
            yield _format_sse_event({"type": "start", "messageId": message_id})
            yield _format_sse_event({"type": "text-start", "id": text_part_id})
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    if not first_delta_logged:
                        first_delta_logged = True
                        logger.info(
                            "Chat first token latency_ms=%.1f total_elapsed_ms=%.1f",
                            (time.perf_counter() - model_stream_opened_at) * 1000,
                            (time.perf_counter() - request_started) * 1000,
                        )
                    logger.debug("Stream delta chars=%d", len(delta))
                    yield _format_sse_event(
                        {"type": "text-delta", "id": text_part_id, "delta": delta}
                    )
            yield _format_sse_event({"type": "text-end", "id": text_part_id})
            yield _format_sse_event({"type": "finish", "finishReason": "stop"})
            yield _format_sse_done()
            logger.info(
                "Chat stream finished total_elapsed_ms=%.1f",
                (time.perf_counter() - request_started) * 1000,
            )
            logger.info("Stream finished messageId=%s", message_id)
        except Exception:
            logger.exception("Stream failed messageId=%s", message_id)
            raise

    headers = {
        "cache-control": "no-cache",
        "connection": "keep-alive",
        "x-vercel-ai-ui-message-stream": "v1",
        "x-accel-buffering": "no",
    }
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=headers,
    )


@app.post("/api/regulations/ingest")
async def ingest_regulation(req: RegulationIngestRequest):
    if AsyncOpenAI is None and AsyncAzureOpenAI is None:
        raise HTTPException(status_code=500, detail="openai package is not installed")

    logger.info("Regulation ingest source=%s", req.source_url)
    content_text = req.raw_text or await _fetch_source_text(req.source_url)
    content_text = content_text.strip()
    if not content_text:
        raise HTTPException(status_code=400, detail="No content extracted from source")

    content_hash = _hash_text(content_text)
    snapshots = _read_snapshots(req.source_url)
    latest = snapshots[-1] if snapshots else None
    if latest and latest.content_hash == content_hash:
        return {"status": "no_change", "latest": RegulationSnapshotMeta(**latest.model_dump())}

    change_summary: Optional[str] = None
    if latest:
        client, model = _get_llm_client()
        prompt = (
            "Compare the previous and current ADU regulation text. "
            "Summarize only the substantive changes in 3-6 bullet points. "
            "If changes are unclear, say so."
        )
        previous_text = _truncate_text(latest.content_text)
        current_text = _truncate_text(content_text)
        completion = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"PREVIOUS:\n{previous_text}\n\nCURRENT:\n{current_text}"},
            ],
        )
        change_summary = completion.choices[0].message.content or None

    snapshot = RegulationSnapshot(
        id=uuid.uuid4().hex,
        source_url=req.source_url,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        version=(latest.version + 1) if latest else 1,
        content_hash=content_hash,
        content_text=content_text,
        change_summary=change_summary,
    )
    _append_snapshot(snapshot)

    return {"status": "updated", "snapshot": RegulationSnapshotMeta(**snapshot.model_dump())}


@app.post("/api/regulations/search-ingest")
async def ingest_regulation_search(req: RegulationSearchIngestRequest):
    if AsyncOpenAI is None and AsyncAzureOpenAI is None:
        raise HTTPException(status_code=500, detail="openai package is not installed")

    return await _run_regulation_search_ingest(req.search_url, req.max_bills)


@app.post("/api/regulations/workflow")
async def run_regulation_workflow_standard_endpoint(req: RegulationWorkflowRequest):
    return await _run_regulations_workflow(req.search_url, req.max_bills)


@app.get("/api/regulations/sources")
async def list_regulation_sources():
    return _ensure_regulation_sources()


@app.post("/api/regulations/sources")
async def upsert_regulation_sources(req: RegulationSourceListUpsertRequest):
    _write_regulation_sources(req.sources)
    return {"status": "updated", "count": len(req.sources), "sources": _ensure_regulation_sources()}


@app.post("/api/regulations/sync-selected")
async def sync_selected_regulation_sources(req: RegulationSyncSelectedRequest):
    return await _sync_selected_sources(req.source_ids)


@app.post("/api/regulations/handbook-sync")
async def ingest_regulation_handbook(req: RegulationHandbookIngestRequest):
    if AsyncOpenAI is None and AsyncAzureOpenAI is None:
        raise HTTPException(status_code=500, detail="openai package is not installed")

    return await _run_handbook_ingest(req.source_url)


@app.get("/api/regulations/latest")
async def get_latest_regulation(source_url: str, include_content: bool = False):
    snapshots = _read_snapshots(source_url)
    if not snapshots:
        raise HTTPException(status_code=404, detail="No snapshots found")
    latest = snapshots[-1]
    if include_content:
        return latest
    return RegulationSnapshotMeta(**latest.model_dump())


@app.get("/api/regulations/snapshots")
async def list_regulation_snapshots(source_url: str):
    snapshots = _read_snapshots(source_url)
    return [RegulationSnapshotMeta(**s.model_dump()) for s in snapshots]


@app.get("/api/regulations/passed-bills")
async def list_passed_bills(limit: int = 50):
    snapshots = _read_latest_bill_snapshots()
    passed = [s for s in snapshots if s.is_passed]
    passed.sort(key=lambda item: item.fetched_at, reverse=True)
    return [RegulationSnapshotMeta(**s.model_dump()) for s in passed[:limit]]


@app.get("/api/regulations/knowledge-base")
async def list_regulations_knowledge_base(limit: int = 50):
    snapshots = _read_latest_bill_snapshots()
    passed = [s for s in snapshots if s.is_passed]
    passed.sort(key=lambda item: item.fetched_at, reverse=True)

    regulations: List[RegulationView] = []
    for snapshot in passed[:limit]:
        source = snapshot.bill_id or "LegInfo"
        if snapshot.bill_title and snapshot.bill_id:
            source = f"{snapshot.bill_title} ({snapshot.bill_id})"
        elif snapshot.bill_title:
            source = snapshot.bill_title

        content = snapshot.change_summary or _truncate_text(snapshot.content_text, max_chars=900)
        title = snapshot.bill_title or snapshot.bill_id or "ADU Regulation Update"
        category = _infer_category(f"{title}\n{content}")

        regulations.append(
            RegulationView(
                id=snapshot.id,
                title=title,
                category=category,
                content=content,
                effectiveDate=snapshot.fetched_at,
                version=str(snapshot.version),
                source=source,
                sourceUrl=snapshot.bill_url,
                lastUpdated=snapshot.fetched_at,
            )
        )

    handbook_source_url = _read_handbook_sync_status().searchUrl or DEFAULT_HANDBOOK_SOURCE_URL
    handbook_snapshots = _read_snapshots(handbook_source_url)
    if handbook_snapshots:
        latest_handbook = handbook_snapshots[-1]
        handbook_content = latest_handbook.change_summary or _truncate_text(latest_handbook.content_text, max_chars=900)
        regulations.append(
            RegulationView(
                id=latest_handbook.id,
                title="California ADU Handbook",
                category=_infer_category(f"handbook\n{handbook_content}"),
                content=handbook_content,
                effectiveDate=latest_handbook.fetched_at,
                version=str(latest_handbook.version),
                source="California HCD Handbook",
                sourceUrl=latest_handbook.source_url,
                lastUpdated=latest_handbook.fetched_at,
            )
        )

    regulations.sort(key=lambda item: item.lastUpdated, reverse=True)

    return regulations[:limit]


@app.get("/api/regulations/alerts")
async def list_regulation_alerts(limit: int = 50):
    snapshots = _read_latest_bill_snapshots()
    passed = [s for s in snapshots if s.is_passed]
    passed.sort(key=lambda item: item.fetched_at, reverse=True)

    alerts: List[RegulationChangeView] = []
    for snapshot in passed[:limit]:
        title = snapshot.bill_title or snapshot.bill_id or "ADU Regulation Update"
        summary = snapshot.change_summary or _truncate_text(snapshot.content_text, max_chars=350)

        alerts.append(
            RegulationChangeView(
                id=snapshot.id,
                regulationId=snapshot.bill_id or snapshot.id,
                title=title,
                changeType="new" if snapshot.version <= 1 else "amended",
                summary=summary,
                previousVersion=str(snapshot.version - 1 if snapshot.version > 1 else 0),
                newVersion=str(snapshot.version),
                effectiveDate=snapshot.fetched_at,
                impactLevel=_infer_impact_level(summary),
                affectedApplications=0,
                createdAt=snapshot.fetched_at,
                isRead=False,
            )
        )

    return alerts


@app.get("/api/regulations/audit")
async def list_regulation_audit(limit: int = 100):
    snapshots = _read_latest_bill_snapshots()
    passed = [s for s in snapshots if s.is_passed]
    passed.sort(key=lambda item: item.fetched_at, reverse=True)

    entries: List[AuditEntryView] = []
    for snapshot in passed[:limit]:
        title = snapshot.bill_title or snapshot.bill_id or "ADU Regulation Update"
        details = snapshot.change_summary or "Regulation content synchronized from source."

        entries.append(
            AuditEntryView(
                id=snapshot.id,
                action="Regulation Added" if snapshot.version <= 1 else "Regulation Updated",
                regulationId=snapshot.bill_id or snapshot.id,
                regulationTitle=title,
                previousVersion=str(snapshot.version - 1 if snapshot.version > 1 else 0),
                newVersion=str(snapshot.version),
                timestamp=snapshot.fetched_at,
                user="System Sync",
                details=details,
            )
        )

    return entries


@app.get("/api/regulations/sync-status")
async def get_regulation_sync_status():
    status = _read_sync_status()
    status.schedulerEnabled = ENABLE_WEEKLY_REGULATION_SYNC
    status.schedulerIntervalHours = WEEKLY_REGULATION_SYNC_INTERVAL_HOURS
    return status


@app.get("/api/regulations/handbook-sync-status")
async def get_regulation_handbook_sync_status():
    status = _read_handbook_sync_status()
    status.schedulerEnabled = ENABLE_WEEKLY_HANDBOOK_SYNC
    status.schedulerIntervalHours = WEEKLY_HANDBOOK_SYNC_INTERVAL_HOURS
    return status


@app.get("/api/regulations/rag/status")
async def get_rag_status():
    return _rag_status_payload()


@app.post("/api/regulations/rag/reindex")
async def reindex_rag(req: RagReindexRequest):
    return _bootstrap_rag_index(include_handbook=req.include_handbook, include_bills=req.include_bills)


@app.post("/api/agents/regulations/workflow")
async def run_regulation_workflow_endpoint(req: RegulationWorkflowRequest):
    return await _run_regulations_workflow(req.search_url, req.max_bills)
