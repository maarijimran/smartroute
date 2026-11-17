"""Local document ingestion and lexical retrieval.

Parsing, chunking and BM25 retrieval all run inside the trusted host and are the
same for every routing policy, so no policy gains an advantage from its evidence.
"""

from __future__ import annotations

import io
import math
import re
from collections import Counter
from dataclasses import dataclass

CHUNK_WORDS, CHUNK_OVERLAP = 200, 40
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "a an and are as at be by for from has have in is it its of on or that the this to was were will with".split()
)


class DocumentError(ValueError):
    """Unreadable or unsupported input; the message is safe to show to the user."""


SCANNED_PAGE_CHARS = 30  # a PDF page with less text than this is treated as scanned


@dataclass
class Extracted:
    pages: list[str]
    ocr_pages: int = 0  # pages whose text came from OCR


def extract_document(filename: str, data: bytes, max_pages: int, ocr=None, ocr_max_pages: int = 20) -> Extracted:
    """Text per page. `ocr` is an OCR backend (see core.ocr) or None when OCR is off:
    photos are read entirely by OCR, and PDF pages without a text layer are OCR'd
    page by page."""
    name = filename.lower()
    if name.endswith(".pdf"):
        return _pdf_pages(data, max_pages, ocr, ocr_max_pages)
    if name.endswith(".txt"):
        return Extracted(_txt_pages(data, max_pages))
    from .ocr import IMAGE_EXTENSIONS, prepare_image

    if name.endswith(IMAGE_EXTENSIONS):
        if ocr is None:
            raise DocumentError("Reading images needs OCR, which is not enabled on this server. Upload a PDF or TXT file.")
        text = ocr.recognise(prepare_image(data))
        if len(text.strip()) < 5:
            raise DocumentError("No text was found in the image.")
        return Extracted([text], ocr_pages=1)
    kinds = "a PDF, a TXT file or an image (PNG, JPG, WebP, TIFF, BMP)" if ocr else "a digitally generated PDF or a TXT file"
    raise DocumentError(f"Unsupported file type. Upload {kinds}.")


def extract_pages(filename: str, data: bytes, max_pages: int) -> list[str]:
    """Text-only extraction (no OCR)."""
    return extract_document(filename, data, max_pages).pages


def _pdf_pages(data: bytes, max_pages: int, ocr=None, ocr_max_pages: int = 20) -> Extracted:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise DocumentError("The PDF is password protected and cannot be read.")
        if len(reader.pages) > max_pages:
            raise DocumentError(f"The PDF has {len(reader.pages)} pages; the limit is {max_pages}.")
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except DocumentError:
        raise
    except Exception as exc:
        raise DocumentError(f"The PDF could not be parsed ({type(exc).__name__}).") from exc
    scanned = [i for i, p in enumerate(pages) if len(p) < SCANNED_PAGE_CHARS]
    ocr_count = 0
    if scanned and ocr is not None:
        if len(scanned) > ocr_max_pages:
            raise DocumentError(
                f"The PDF has {len(scanned)} scanned pages; OCR is limited to {ocr_max_pages} pages per upload."
            )
        from .ocr import render_pdf_pages

        for i, png in zip(scanned, render_pdf_pages(data, scanned)):
            pages[i] = ocr.recognise(png).strip()
        ocr_count = len(scanned)
    if sum(len(p) for p in pages) < 200:
        if ocr is None:
            raise DocumentError("No text could be extracted. Scanned PDFs need OCR, which is not enabled on this server.")
        raise DocumentError("No text could be extracted, even with OCR.")
    return Extracted(pages, ocr_pages=ocr_count)


def _txt_pages(data: bytes, max_pages: int) -> list[str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    text = text.strip()
    if not text:
        raise DocumentError("The text file is empty.")
    pages = [text[i : i + 3000] for i in range(0, len(text), 3000)]
    if len(pages) > max_pages:
        raise DocumentError(f"The text file is too long (limit about {max_pages * 3000:,} characters).")
    return pages


def chunk_pages(pages: list[str]) -> list[tuple[int, str]]:
    """Returns (page_number, chunk_text) with overlapping word windows per page."""
    chunks: list[tuple[int, str]] = []
    step = CHUNK_WORDS - CHUNK_OVERLAP
    for page_no, page in enumerate(pages, start=1):
        words = page.split()
        for start in range(0, len(words), step):
            window = words[start : start + CHUNK_WORDS]
            if len(window) >= 5 or start == 0 and window:
                chunks.append((page_no, " ".join(window)))
            if start + CHUNK_WORDS >= len(words):
                break
    return chunks


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


@dataclass
class Scored:
    index: int
    score: float


def query_weights(query: str | dict[str, float]) -> dict[str, float]:
    if isinstance(query, dict):
        return query
    return {term: 1.0 for term in set(tokenize(query))}


def bm25_scores(query: str | dict[str, float], texts: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    """Okapi BM25 score of every text. `query` is a string or a {term: weight}
    mapping; weights let follow-up questions borrow terms from earlier turns at
    reduced strength."""
    docs = [tokenize(t) for t in texts]
    n = len(docs)
    if n == 0:
        return []
    avg_len = sum(len(d) for d in docs) / n or 1.0
    df: Counter[str] = Counter()
    for d in docs:
        df.update(set(d))
    weights = query_weights(query)
    scores = []
    for d in docs:
        tf = Counter(d)
        score = 0.0
        for term, weight in weights.items():
            f = tf.get(term, 0)
            if not f:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += weight * idf * f * (k1 + 1) / (f + k1 * (1 - b + b * len(d) / avg_len))
        scores.append(score)
    return scores


def bm25_rank(query: str | dict[str, float], texts: list[str], top_k: int, k1: float = 1.5, b: float = 0.75) -> list[Scored]:
    """Up to top_k results with a positive score, best first."""
    scored = [Scored(i, s) for i, s in enumerate(bm25_scores(query, texts, k1, b)) if s > 0]
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:top_k]
