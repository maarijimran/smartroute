"""Shared helpers for scripts that push the benchmark workload through the pipeline."""

from __future__ import annotations

import hashlib
import json
import os
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import pipeline
from ..core.documents import chunk_pages
from ..models import ROLE_USER, Document, DocumentChunk, User
from ..security import hash_password

EVAL_EMAIL = "eval@smartroute.local"
PAGE_CHARS = 3000


def load_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def append_jsonl(path: str, row: dict) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def ensure_eval_user(db: Session) -> User:
    """A dedicated ordinary user that owns benchmark documents. It has no special
    privacy permission, so the benchmark runs under the default policy."""
    user = db.execute(select(User).where(User.email == EVAL_EMAIL)).scalars().first()
    if user is None:
        user = User(
            email=EVAL_EMAIL, name="Evaluation runner", role=ROLE_USER,
            password_hash=hash_password(secrets.token_urlsafe(24)),
        )
        db.add(user)
        db.commit()
    return user


def read_doc(docs_dir: str, doc_id: str) -> str:
    with open(os.path.join(docs_dir, f"{doc_id}.txt"), encoding="utf-8") as fh:
        return fh.read()


def ensure_documents(db: Session, user: User, doc_ids: set[str], docs_dir: str) -> dict[str, str]:
    """Ingests benchmark papers once (labelled public, kept). Returns doc_id -> Document.id."""
    mapping: dict[str, str] = {}
    for doc_id in sorted(doc_ids):
        text = read_doc(docs_dir, doc_id)
        digest = hashlib.sha256(text.encode()).hexdigest()
        doc = db.execute(
            select(Document).where(Document.user_id == user.id, Document.sha256 == digest)
        ).scalars().first()
        if doc is None:
            pages = [text[i : i + PAGE_CHARS] for i in range(0, len(text), PAGE_CHARS)]
            chunks = chunk_pages(pages)
            doc = Document(
                user_id=user.id, filename=f"{doc_id}.txt", label="public", pages=len(pages),
                n_chunks=len(chunks), sha256=digest, persist=True,
            )
            db.add(doc)
            db.flush()
            db.add_all(DocumentChunk(document_id=doc.id, idx=i, page=p, text=t) for i, (p, t) in enumerate(chunks))
        mapping[doc_id] = doc.id
    db.commit()
    return mapping


def request_for(item: dict, user: User, doc_map: dict[str, str], docs_dir: str, **kwargs) -> pipeline.RouteRequest:
    """Builds the pipeline request for one workload item. "full_text" items put the
    whole paper in the prompt (context-window stress); the rest use retrieval."""
    if item.get("mode") == "full_text":
        prompt = f"{read_doc(docs_dir, item['doc_id'])}\n\nQuestion: {item['prompt']}"
        document_ids: list[str] = []
    else:
        prompt = item["prompt"]
        document_ids = [doc_map[item["doc_id"]]] if item.get("doc_id") in doc_map else []
    return pipeline.RouteRequest.for_user(
        user,
        [{"role": "user", "content": prompt}],
        source="eval",
        task=item["task"],
        document_ids=document_ids,
        use_cache=False,
        **kwargs,
    )
