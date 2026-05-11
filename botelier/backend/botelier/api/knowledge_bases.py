"""Knowledge Bases API - CRUD operations for knowledge base collections and their entries.

Architecture:
- Knowledge Bases are named collections belonging to an account
- Each Knowledge Base contains multiple Q&A entries
- Knowledge Bases can be assigned to assistants

Endpoints:
Knowledge Bases:
- POST /api/knowledge-bases - Create new knowledge base
- GET /api/knowledge-bases - List all knowledge bases for account
- GET /api/knowledge-bases/{kb_id} - Get knowledge base details
- PUT /api/knowledge-bases/{kb_id} - Update knowledge base
- DELETE /api/knowledge-bases/{kb_id} - Delete knowledge base (and all entries)

Entries within a Knowledge Base:
- POST /api/knowledge-bases/{kb_id}/entries - Create entry
- GET /api/knowledge-bases/{kb_id}/entries - List entries
- GET /api/knowledge-bases/{kb_id}/entries/{entry_id} - Get entry
- PUT /api/knowledge-bases/{kb_id}/entries/{entry_id} - Update entry
- DELETE /api/knowledge-bases/{kb_id}/entries/{entry_id} - Delete entry
- DELETE /api/knowledge-bases/{kb_id}/entries/bulk - Bulk delete
- POST /api/knowledge-bases/{kb_id}/entries/import-csv - Import from CSV
- GET /api/knowledge-bases/{kb_id}/entries/export-csv - Export to CSV
"""

import csv
import io
import json
import logging
import os
import re
from datetime import date, datetime
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from botelier.auth.middleware import check_account_permission, get_current_user
from botelier.database import get_db
from botelier.models.knowledge_base import KnowledgeBase
from botelier.models.knowledge_entry import KnowledgeEntry
from botelier.models.user import User
from botelier.services.ssrf_safe_transport import SSRFSafeTransport

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge-bases", tags=["knowledge-bases"])


def _get_kb_and_check(kb_id: str, permission: str, user: User, db: Session) -> KnowledgeBase:
    """Fetch a knowledge base and verify the user has the given permission on its account."""
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    check_account_permission(user, str(kb.account_id), permission, db)
    return kb


# Pydantic Models - Knowledge Bases


class KnowledgeBaseCreate(BaseModel):
    """Request model for creating a knowledge base."""

    account_id: str
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


class KnowledgeBaseUpdate(BaseModel):
    """Request model for updating a knowledge base."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None


# Pydantic Models - Entries


class EntryCreate(BaseModel):
    """Request model for creating a Q&A entry."""

    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    category: Optional[str] = Field(None, max_length=100)
    expiration_date: Optional[str] = None


class EntryUpdate(BaseModel):
    """Request model for updating a Q&A entry."""

    question: Optional[str] = Field(None, min_length=1)
    answer: Optional[str] = Field(None, min_length=1)
    category: Optional[str] = Field(None, max_length=100)
    expiration_date: Optional[str] = None


class BulkDeleteRequest(BaseModel):
    """Request model for bulk delete."""

    entry_ids: List[str] = Field(..., min_length=1)


class ImportURLRequest(BaseModel):
    """Request model for importing knowledge entries from a website URL."""

    url: str = Field(..., min_length=1, max_length=2048)
    max_pages: int = Field(default=10, ge=1, le=20)
    category: Optional[str] = Field(None, max_length=100)


# ============================================================
# Website crawl + LLM Q&A generation helpers
# ============================================================

_CRAWL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Botelier-KB-Importer/1.0; +https://botelier.ai)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

_UNWANTED_TAGS = {
    "script", "style", "noscript", "header", "footer", "nav",
    "aside", "form", "button", "svg", "iframe", "img",
}

_QA_SYSTEM_PROMPT = """You are a knowledge-base assistant. Your job is to read a web page and produce
Q&A pairs that an AI phone agent can use to answer caller questions.

Rules:
- Generate between 3 and 8 Q&A pairs per page.
- Questions must be short, natural, spoken-language questions a caller might ask.
- Answers must be complete, spoken-language sentences — never bullet lists, markdown, or HTML.
- Focus on facts: products, services, prices, hours, ingredients, policies, locations, contacts.
- Ignore boilerplate (copyright notices, navigation labels, cookie banners, login prompts).
- If the page has no useful factual content, return {"pairs": []}.

Respond ONLY with a valid JSON object in this exact format:
{"pairs": [
  {"question": "What flavors do you offer?", "answer": "We offer chocolate chip, peanut butter, and snickerdoodle cookies."},
  {"question": "Do you ship nationwide?", "answer": "Yes, we ship to all 50 states with free shipping on orders over $30."}
]}"""


def _extract_text(html: str) -> str:
    """Strip HTML to clean readable text, removing nav/footer/script noise."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(_UNWANTED_TAGS):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    deduplicated = []
    seen = set()
    for ln in lines:
        if ln not in seen:
            seen.add(ln)
            deduplicated.append(ln)
    return "\n".join(deduplicated)


def _same_domain_links(html: str, base_url: str) -> List[str]:
    """Return same-domain absolute links found on the page (no fragments/queries)."""
    base = urlparse(base_url)
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        abs_url = urljoin(base_url, href)
        parsed = urlparse(abs_url)
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.netloc != base.netloc:
            continue
        clean = parsed._replace(fragment="", query="").geturl()
        links.append(clean)
    return links


async def _crawl_pages(start_url: str, max_pages: int) -> List[dict]:
    """BFS crawl of same-domain pages. Returns list of {url, text} dicts."""
    visited: set = set()
    queue: List[str] = [start_url]
    pages = []

    async with httpx.AsyncClient(
        headers=_CRAWL_HEADERS,
        follow_redirects=True,
        timeout=15.0,
        transport=SSRFSafeTransport(),
    ) as client:
        while queue and len(pages) < max_pages:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    continue
                ct = resp.headers.get("content-type", "")
                if "text/html" not in ct:
                    continue
                html = resp.text
            except Exception as exc:
                logger.warning("Crawl error for %s: %s", url, exc)
                continue

            text = _extract_text(html)
            if len(text) > 200:
                pages.append({"url": url, "text": text[:6000]})

            if len(pages) < max_pages:
                for link in _same_domain_links(html, url):
                    if link not in visited and link not in queue:
                        queue.append(link)

    return pages


_CHUNK_SIZE = 4000
_CHUNK_OVERLAP = 200


def _chunk_text(text: str) -> List[str]:
    """Split text into overlapping windows that fit within the LLM prompt budget.

    Splits on paragraph boundaries where possible to avoid cutting mid-sentence.
    """
    if len(text) <= _CHUNK_SIZE:
        return [text]

    chunks = []
    paragraphs = re.split(r"\n{2,}", text)
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 > _CHUNK_SIZE:
            if current:
                chunks.append(current.strip())
                tail = current[-_CHUNK_OVERLAP:] if len(current) > _CHUNK_OVERLAP else current
                current = tail + "\n\n" + para
            else:
                chunks.append(para[:_CHUNK_SIZE])
                current = para[-_CHUNK_OVERLAP:]
        else:
            current = (current + "\n\n" + para).lstrip() if current else para

    if current.strip():
        chunks.append(current.strip())

    return chunks or [text[:_CHUNK_SIZE]]


async def _call_llm_for_chunk(client: AsyncOpenAI, chunk: str, page_url: str) -> List[dict]:
    """Single LLM call for one text chunk. Returns validated {question, answer} dicts."""
    user_content = f"Page URL: {page_url}\n\n---\n\n{chunk}"
    try:
        resp = await client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": _QA_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=1500,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        logger.warning("OpenAI Q&A generation failed for %s: %s", page_url, exc)
        return []

    raw = resp.choices[0].message.content or ""
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            pairs = parsed
        elif isinstance(parsed, dict):
            pairs = next((v for v in parsed.values() if isinstance(v, list)), [])
        else:
            pairs = []
    except json.JSONDecodeError:
        logger.warning("Failed to parse Q&A JSON for %s: %s", page_url, raw[:200])
        return []

    valid = []
    for item in pairs:
        if isinstance(item, dict) and item.get("question") and item.get("answer"):
            valid.append({
                "question": str(item["question"]).strip(),
                "answer": str(item["answer"]).strip(),
            })
    return valid


async def _generate_qa_pairs(page_text: str, page_url: str, openai_key: str) -> List[dict]:
    """Chunk page text and ask the LLM to produce Q&A pairs from each chunk.

    Deduplicates by normalised question text before returning.
    """
    client = AsyncOpenAI(api_key=openai_key)
    chunks = _chunk_text(page_text)

    seen_questions: set = set()
    all_pairs: List[dict] = []
    for chunk in chunks:
        pairs = await _call_llm_for_chunk(client, chunk, page_url)
        for pair in pairs:
            norm = pair["question"].lower().strip()
            if norm not in seen_questions:
                seen_questions.add(norm)
                all_pairs.append(pair)

    return all_pairs


# ============================================================
# Knowledge Base Endpoints
# ============================================================


@router.post("/{kb_id}/import-url", status_code=202)
async def import_from_url(
    kb_id: str,
    data: ImportURLRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Crawl a website and generate Q&A knowledge entries via LLM."""
    kb = _get_kb_and_check(kb_id, "knowledge_base.import", user, db)

    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if not openai_key:
        raise HTTPException(status_code=503, detail="OpenAI API key is not configured")

    pages = await _crawl_pages(str(data.url), data.max_pages)
    if not pages:
        raise HTTPException(
            status_code=422,
            detail="No readable content could be extracted from the URL. "
            "The site may require JavaScript or block automated access.",
        )

    start_url_clean = str(data.url).rstrip("/")
    if data.category:
        raw_category = f"{data.category} [{start_url_clean}]"
    else:
        raw_category = start_url_clean
    entry_category = raw_category[:100]

    total_created = 0
    for page in pages:
        pairs = await _generate_qa_pairs(page["text"], page["url"], openai_key)
        for pair in pairs:
            entry = KnowledgeEntry(
                knowledge_base_id=kb_id,
                question=pair["question"],
                answer=pair["answer"],
                category=entry_category,
            )
            db.add(entry)
            total_created += 1

    if total_created > 0:
        db.commit()

    return {
        "success": True,
        "pages_crawled": len(pages),
        "entries_created": total_created,
        "category_tag": entry_category,
    }


@router.post("", status_code=201)
async def create_knowledge_base(
    data: KnowledgeBaseCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new knowledge base."""
    check_account_permission(user, data.account_id, "knowledge_base.create", db)
    kb = KnowledgeBase(account_id=data.account_id, name=data.name, description=data.description)

    db.add(kb)
    db.commit()
    db.refresh(kb)

    return kb.to_dict()


@router.get("")
async def list_knowledge_bases(
    account_id: str = Query(..., description="Account UUID"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all knowledge bases for an account with entry counts."""
    check_account_permission(user, account_id, "knowledge_base.view", db)
    kbs = (
        db.query(KnowledgeBase)
        .filter(KnowledgeBase.account_id == account_id)
        .order_by(KnowledgeBase.created_at.desc())
        .all()
    )

    return {"knowledge_bases": [kb.to_dict() for kb in kbs], "total": len(kbs)}


@router.get("/{kb_id}")
async def get_knowledge_base(
    kb_id: str,
    include_entries: bool = Query(False, description="Include all entries"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a specific knowledge base by ID."""
    kb = _get_kb_and_check(kb_id, "knowledge_base.view", user, db)
    return kb.to_dict(include_entries=include_entries)


@router.put("/{kb_id}")
async def update_knowledge_base(
    kb_id: str,
    data: KnowledgeBaseUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update a knowledge base."""
    kb = _get_kb_and_check(kb_id, "knowledge_base.edit", user, db)

    if data.name is not None:
        kb.name = data.name
    if data.description is not None:
        kb.description = data.description

    db.commit()
    db.refresh(kb)

    return kb.to_dict()


@router.delete("/{kb_id}", status_code=204)
async def delete_knowledge_base(
    kb_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a knowledge base and all its entries."""
    kb = _get_kb_and_check(kb_id, "knowledge_base.delete", user, db)
    db.delete(kb)
    db.commit()


# ============================================================
# Entry Endpoints (within a Knowledge Base)
# ============================================================


@router.post("/{kb_id}/entries", status_code=201)
async def create_entry(
    kb_id: str,
    data: EntryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a Q&A entry in a knowledge base."""
    kb = _get_kb_and_check(kb_id, "knowledge_base.create", user, db)

    exp_date = None
    if data.expiration_date:
        try:
            exp_date = datetime.fromisoformat(data.expiration_date).date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    entry = KnowledgeEntry(
        knowledge_base_id=kb_id,
        question=data.question,
        answer=data.answer,
        category=data.category,
        expiration_date=exp_date,
    )

    db.add(entry)
    db.commit()
    db.refresh(entry)

    return entry.to_dict()


@router.get("/{kb_id}/entries")
async def list_entries(
    kb_id: str,
    include_expired: bool = Query(False, description="Include expired entries"),
    category: Optional[str] = Query(None, description="Filter by category"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all entries in a knowledge base."""
    kb = _get_kb_and_check(kb_id, "knowledge_base.view", user, db)

    query = db.query(KnowledgeEntry).filter(KnowledgeEntry.knowledge_base_id == kb_id)

    if category:
        query = query.filter(KnowledgeEntry.category == category)

    if not include_expired:
        today = date.today()
        query = query.filter(
            (KnowledgeEntry.expiration_date.is_(None)) | (KnowledgeEntry.expiration_date >= today)
        )

    entries = query.order_by(KnowledgeEntry.created_at.desc()).all()

    return {"entries": [entry.to_dict() for entry in entries], "total": len(entries)}


@router.get("/{kb_id}/entries/export-csv")
async def export_entries_csv(
    kb_id: str,
    include_expired: bool = Query(True, description="Include expired entries"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Export all entries to CSV file."""
    kb = _get_kb_and_check(kb_id, "knowledge_base.view", user, db)

    query = db.query(KnowledgeEntry).filter(KnowledgeEntry.knowledge_base_id == kb_id)

    if not include_expired:
        today = date.today()
        query = query.filter(
            (KnowledgeEntry.expiration_date.is_(None)) | (KnowledgeEntry.expiration_date >= today)
        )

    entries = query.order_by(KnowledgeEntry.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["question", "answer", "category", "expiration_date", "created_at"])

    for entry in entries:
        writer.writerow(
            [
                entry.question,
                entry.answer,
                entry.category or "",
                entry.expiration_date.isoformat() if entry.expiration_date else "",
                entry.created_at.isoformat() if entry.created_at else "",
            ]
        )

    output.seek(0)
    filename = f"{kb.name.replace(' ', '_')}_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.delete("/{kb_id}/entries/bulk", status_code=200)
async def bulk_delete_entries(
    kb_id: str,
    data: BulkDeleteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Bulk delete entries."""
    _get_kb_and_check(kb_id, "knowledge_base.delete", user, db)
    deleted_count = (
        db.query(KnowledgeEntry)
        .filter(KnowledgeEntry.knowledge_base_id == kb_id, KnowledgeEntry.id.in_(data.entry_ids))
        .delete(synchronize_session=False)
    )

    db.commit()

    return {"success": True, "deleted": deleted_count}


@router.get("/{kb_id}/entries/{entry_id}")
async def get_entry(
    kb_id: str,
    entry_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a specific entry."""
    _get_kb_and_check(kb_id, "knowledge_base.view", user, db)
    entry = (
        db.query(KnowledgeEntry)
        .filter(KnowledgeEntry.id == entry_id, KnowledgeEntry.knowledge_base_id == kb_id)
        .first()
    )

    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    return entry.to_dict()


@router.put("/{kb_id}/entries/{entry_id}")
async def update_entry(
    kb_id: str,
    entry_id: str,
    data: EntryUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update a Q&A entry."""
    _get_kb_and_check(kb_id, "knowledge_base.edit", user, db)
    entry = (
        db.query(KnowledgeEntry)
        .filter(KnowledgeEntry.id == entry_id, KnowledgeEntry.knowledge_base_id == kb_id)
        .first()
    )

    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    if data.question is not None:
        entry.question = data.question
    if data.answer is not None:
        entry.answer = data.answer
    if data.category is not None:
        entry.category = data.category
    if data.expiration_date is not None:
        try:
            entry.expiration_date = datetime.fromisoformat(data.expiration_date).date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    db.commit()
    db.refresh(entry)

    return entry.to_dict()


@router.delete("/{kb_id}/entries/{entry_id}", status_code=204)
async def delete_entry(
    kb_id: str,
    entry_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a Q&A entry."""
    _get_kb_and_check(kb_id, "knowledge_base.delete", user, db)
    entry = (
        db.query(KnowledgeEntry)
        .filter(KnowledgeEntry.id == entry_id, KnowledgeEntry.knowledge_base_id == kb_id)
        .first()
    )

    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    db.delete(entry)
    db.commit()


@router.post("/{kb_id}/entries/import-csv", status_code=201)
async def import_csv(
    kb_id: str,
    file: UploadFile = File(...),
    replace_duplicates: bool = Query(
        False,
        description="When true, update existing entries whose question matches instead of skipping them",
    ),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Bulk import Q&A entries from CSV file."""
    kb = _get_kb_and_check(kb_id, "knowledge_base.import", user, db)

    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a CSV")

    content = await file.read()
    csv_text = content.decode("utf-8")
    csv_reader = csv.DictReader(io.StringIO(csv_text))

    if (
        not csv_reader.fieldnames
        or "question" not in csv_reader.fieldnames
        or "answer" not in csv_reader.fieldnames
    ):
        raise HTTPException(
            status_code=400, detail="CSV must contain 'question' and 'answer' columns"
        )

    existing_by_question = {
        e.question.strip().lower(): e
        for e in db.query(KnowledgeEntry).filter(KnowledgeEntry.knowledge_base_id == kb_id).all()
    }

    created_count = 0
    replaced_count = 0
    skipped_count = 0
    error_count = 0
    errors = []

    for row_num, row in enumerate(csv_reader, start=2):
        try:
            question = row.get("question", "").strip()
            answer = row.get("answer", "").strip()

            if not question or not answer:
                error_count += 1
                errors.append(f"Row {row_num}: Missing question or answer")
                continue

            category = row.get("category", "").strip() or None

            exp_date = None
            exp_date_str = row.get("expiration_date", "").strip()
            if exp_date_str:
                try:
                    exp_date = datetime.fromisoformat(exp_date_str).date()
                except ValueError:
                    error_count += 1
                    errors.append(f"Row {row_num}: Invalid date format '{exp_date_str}'")
                    continue

            existing = existing_by_question.get(question.lower())
            if existing:
                if replace_duplicates:
                    existing.answer = answer
                    existing.category = category
                    existing.expiration_date = exp_date
                    existing.updated_at = datetime.utcnow()
                    replaced_count += 1
                else:
                    skipped_count += 1
                continue

            entry = KnowledgeEntry(
                knowledge_base_id=kb_id,
                question=question,
                answer=answer,
                category=category,
                expiration_date=exp_date,
            )

            db.add(entry)
            created_count += 1

        except Exception as e:
            error_count += 1
            errors.append(f"Row {row_num}: {str(e)}")

    if created_count > 0 or replaced_count > 0:
        db.commit()

    return {
        "success": True,
        "created": created_count,
        "replaced": replaced_count,
        "skipped": skipped_count,
        "errors": error_count,
        "error_details": errors[:10],
    }


# ============================================================
# Legacy Endpoints (for backward compatibility during migration)
# TODO: Remove after frontend migration complete
# ============================================================

legacy_router = APIRouter(prefix="/api/entries", tags=["entries-legacy"])


@legacy_router.get("")
async def legacy_list_entries(
    account_id: str = Query(None, description="Account UUID (legacy)"),
    knowledge_base_id: str = Query(None, description="Knowledge Base UUID"),
    include_expired: bool = Query(False),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Legacy endpoint - list entries by account_id or knowledge_base_id."""
    if knowledge_base_id:
        query = db.query(KnowledgeEntry).filter(
            KnowledgeEntry.knowledge_base_id == knowledge_base_id
        )
    elif account_id:
        query = db.query(KnowledgeEntry).filter(KnowledgeEntry.account_id == account_id)
    else:
        raise HTTPException(
            status_code=400, detail="Either account_id or knowledge_base_id required"
        )

    if category:
        query = query.filter(KnowledgeEntry.category == category)

    if not include_expired:
        today = date.today()
        query = query.filter(
            (KnowledgeEntry.expiration_date.is_(None)) | (KnowledgeEntry.expiration_date >= today)
        )

    entries = query.order_by(KnowledgeEntry.created_at.desc()).all()

    return {"entries": [entry.to_dict() for entry in entries], "total": len(entries)}
