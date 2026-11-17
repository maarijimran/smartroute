"""Local OCR for photos and scanned PDF pages.

Model: baidu/Unlimited-OCR (3B, MIT licence), served by vLLM as an
OpenAI-compatible endpoint on our own GPU server. Request format follows the
model card and the vLLM recipe:
  https://huggingface.co/baidu/Unlimited-OCR
  https://recipes.vllm.ai/baidu/Unlimited-OCR

Privacy: OCR is part of the trusted boundary. In production the gateway refuses
to start with an OCR endpoint that is not on this host or the private network,
so an image of a document can never be sent to an outside service to be read.
The recognised text then goes through the normal privacy gate like any other
document text.

NOT YET RUN against the real model: written from the published documentation.
`clean_output` in particular should be checked against real responses.
"""

from __future__ import annotations

import base64
import io
import ipaddress
import logging
import re
from urllib.parse import urlparse

import httpx

from ..config import Settings, get_settings
from .documents import DocumentError

log = logging.getLogger(__name__)

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp")
MAX_IMAGE_SIDE = 2048  # longer side after downscaling; the model works on 1024 px views
MAX_IMAGE_PIXELS = 60_000_000  # refuse decompression bombs
PDF_RENDER_DPI = 200

_DET = re.compile(r"<\|det\|>.*?<\|/det\|>", re.S)
_REF = re.compile(r"<\|ref\|>(.*?)<\|/ref\|>", re.S)
_TOKEN = re.compile(r"<\|[^|<>]{1,40}\|>")
# Layout labels the model may put inside <|ref|> instead of real text.
_LAYOUT_LABELS = frozenset(
    "text title sub_title subtitle table image figure caption image_caption table_caption header footer "
    "page_header page_footer page_number list equation formula code abstract reference footnote".split()
)


class OcrUnavailable(RuntimeError):
    """The OCR service could not be reached or failed; not the user's fault."""


def clean_output(raw: str) -> str:
    """Removes grounding markup: <|det|>…<|/det|> boxes are dropped, <|ref|>…<|/ref|>
    keeps its text unless it is only a layout label, other special tokens go."""
    text = _DET.sub("", raw)
    text = _REF.sub(lambda m: "" if m.group(1).strip().lower() in _LAYOUT_LABELS else m.group(1), text)
    text = _TOKEN.sub("", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_local_endpoint(url: str) -> bool:
    """True for localhost, loopback and private addresses, and single-label hosts
    (Docker service names such as `ocr`). Hostnames are not resolved."""
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    if host == "localhost" or "." not in host:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback


def prepare_image(data: bytes) -> bytes:
    """Validates an uploaded image and re-encodes it as PNG: applies the EXIF
    rotation, downscales very large photos, and drops all metadata (camera,
    GPS location) as a side effect of re-encoding."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(data)) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            if max(im.size) > MAX_IMAGE_SIDE:
                im.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
            out = io.BytesIO()
            im.save(out, "PNG")
            return out.getvalue()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError) as exc:
        raise DocumentError("The image could not be read. Upload a PNG, JPG, WebP, TIFF or BMP file.") from exc


def render_pdf_pages(data: bytes, page_indexes: list[int]) -> list[bytes]:
    """Renders the given PDF pages to PNG for OCR."""
    import pypdfium2 as pdfium

    out = []
    pdf = pdfium.PdfDocument(data)
    try:
        for i in page_indexes:
            image = pdf[i].render(scale=PDF_RENDER_DPI / 72).to_pil().convert("RGB")
            if max(image.size) > MAX_IMAGE_SIDE:
                image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
            buf = io.BytesIO()
            image.save(buf, "PNG")
            out.append(buf.getvalue())
    finally:
        pdf.close()
    return out


class OcrClient:
    """Calls the vLLM server. One request per image or page, so every page keeps
    its own page number for citations."""

    name = "vllm"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.base_url = settings.ocr_base_url.rstrip("/")
        self.model = settings.ocr_model
        self.prompt = settings.ocr_prompt
        self.max_tokens = settings.ocr_max_tokens
        self.timeout = httpx.Timeout(settings.ocr_timeout_s, connect=10.0)
        self.transport = transport

    def recognise(self, png: bytes) -> str:
        data_url = "data:image/png;base64," + base64.b64encode(png).decode()
        body = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": self.prompt},
                    ],
                }
            ],
            "max_tokens": self.max_tokens,
            "temperature": 0.0,
            # Settings the model card requires: keep the grounding tokens so they can
            # be removed reliably, and block repetition loops with the n-gram processor.
            "skip_special_tokens": False,
            "vllm_xargs": {"ngram_size": 35, "window_size": 128},
        }
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                response = client.post(f"{self.base_url}/chat/completions", json=body)
        except httpx.HTTPError as exc:
            raise OcrUnavailable(f"OCR service unreachable ({type(exc).__name__})") from exc
        if response.status_code >= 400:
            raise OcrUnavailable(f"OCR service error {response.status_code}: {response.text[:200]}")
        try:
            raw = response.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, ValueError) as exc:
            raise OcrUnavailable("OCR service returned an unexpected response") from exc
        return clean_output(raw)


class MockOcr:
    """Development stand-in: returns fixed text for every image, clearly marked.
    Disabled in production."""

    name = "mock"
    TEXT = (
        "[Mock OCR, development only: this text is fixed and was not read from the image]\n"
        "IDENTITY CARD · DEMO SPECIMEN\n"
        "Name: Ayesha Demo\n"
        "Father Name: Demo Khan\n"
        "Gender: F    Country of Stay: Pakistan\n"
        "Identity Number: 42101-1234567-1\n"
        "Date of Birth: 01.01.2003\n"
        "Date of Issue: 15.03.2021    Date of Expiry: 15.03.2031"
    )

    def recognise(self, png: bytes) -> str:
        return self.TEXT


_ocr: OcrClient | MockOcr | None = None
_ocr_set = False


def get_ocr() -> OcrClient | MockOcr | None:
    """The configured OCR backend, or None when OCR is switched off."""
    global _ocr, _ocr_set
    if not _ocr_set:
        settings = get_settings()
        backend = settings.ocr_backend.lower()
        if backend == "vllm":
            _ocr = OcrClient(settings)
        elif backend == "mock" and not settings.is_production:
            _ocr = MockOcr()
        else:
            _ocr = None
        _ocr_set = True
    return _ocr


def set_ocr(client) -> None:
    """Swap the OCR backend (tests)."""
    global _ocr, _ocr_set
    _ocr, _ocr_set = client, True


def reset_ocr() -> None:
    global _ocr, _ocr_set
    _ocr, _ocr_set = None, False
