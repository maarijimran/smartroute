"""Document upload. Parsing, OCR and chunking happen on this server; the raw file is not kept."""

import hashlib
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.documents import DocumentError, chunk_pages, extract_document
from ..core.ocr import OcrUnavailable, get_ocr
from ..db import get_db
from ..deps import get_current_user
from ..models import Document, DocumentChunk, User
from ..schemas import DocumentOut

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.get("", response_model=list[DocumentOut])
def list_documents(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.execute(
        select(Document).where(Document.user_id == user.id).order_by(Document.created_at.desc())
    ).scalars().all()


@router.post("", response_model=DocumentOut, status_code=201)
def upload_document(
    file: UploadFile = File(...),
    # Confidential is the default: a document must be explicitly declared public
    # before its text can be considered for cloud processing.
    label: Literal["public", "confidential"] = Form("confidential"),
    persist: bool = Form(False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    limit = settings.max_upload_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"The file is larger than {settings.max_upload_mb} MB")
    filename = (file.filename or "document").replace("\\", "/").split("/")[-1][:200]
    try:
        extracted = extract_document(filename, data, settings.max_pages, get_ocr(), settings.ocr_max_pages)
    except DocumentError as exc:
        raise HTTPException(422, str(exc)) from exc
    except OcrUnavailable as exc:
        raise HTTPException(503, "The OCR service is not available right now. Try again later.") from exc
    pages = extracted.pages
    chunks = chunk_pages(pages)
    if not chunks:
        raise HTTPException(422, "The document contains no usable text")
    doc = Document(
        user_id=user.id,
        filename=filename,
        label=label,
        pages=len(pages),
        n_chunks=len(chunks),
        sha256=hashlib.sha256(data).hexdigest(),
        ocr_pages=extracted.ocr_pages,
        persist=persist,
    )
    db.add(doc)
    db.flush()
    db.add_all(DocumentChunk(document_id=doc.id, idx=i, page=page, text=text) for i, (page, text) in enumerate(chunks))
    db.commit()
    return doc


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(404, "Document not found")
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
    db.delete(doc)
    db.commit()
