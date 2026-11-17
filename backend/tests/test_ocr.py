"""OCR: output clean-up, endpoint locality, image handling, the vLLM request,
scanned PDFs, and a CNIC photo travelling through the privacy gate."""

import io
import json

import httpx
import pytest
from PIL import Image
from pypdf import PdfWriter

from app.config import Settings
from app.core import ocr
from app.core.documents import DocumentError, extract_document
from app.core.providers.mock import MockProvider

from .conftest import make_user


class FakeOcr:
    def __init__(self, text="Identity Number: 42101-1234567-1\nName: Ayesha Demo"):
        self.text, self.calls = text, 0

    def recognise(self, png: bytes) -> str:
        assert png.startswith(b"\x89PNG"), "OCR must always receive a re-encoded PNG"
        self.calls += 1
        return self.text


def png_bytes(size=(320, 200), exif_gps=False) -> bytes:
    im = Image.new("RGB", size, "white")
    buf = io.BytesIO()
    if exif_gps:
        exif = Image.Exif()
        exif[0x010F] = "PhoneMaker"  # camera make, stands in for any metadata
        im.save(buf, "JPEG", exif=exif.tobytes())
    else:
        im.save(buf, "PNG")
    return buf.getvalue()


def blank_pdf(pages=1) -> bytes:
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=300, height=200)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_clean_output_removes_grounding_markup():
    raw = (
        "<|ref|>title<|/ref|><|det|>[[10, 20, 300, 60]]<|/det|>\nIDENTITY CARD\n"
        "<|ref|>text<|/ref|><|det|>[[10, 80, 500, 120]]<|/det|>\nIdentity Number: 42101-1234567-1\n\n\n\n"
        "<|det|>text [12, 130, 400, 160]<|/det|>Name: <|ref|>Ayesha Demo<|/ref|><|end▁of▁sentence|>"
    )
    clean = ocr.clean_output(raw)
    assert "<|" not in clean and "[[" not in clean
    assert "IDENTITY CARD" in clean and "42101-1234567-1" in clean and "Name: Ayesha Demo" in clean
    assert "title" not in clean.split("\n")[0]  # bare layout labels are dropped
    assert "\n\n\n" not in clean


@pytest.mark.parametrize(
    "url,local",
    [
        ("http://localhost:8001/v1", True), ("http://127.0.0.1:8001/v1", True), ("http://ocr:8000/v1", True),
        ("http://10.0.0.5:8000/v1", True), ("http://192.168.1.20/v1", True),
        ("https://api.example.com/v1", False), ("http://8.8.8.8/v1", False), ("", False),
    ],
)
def test_ocr_endpoint_must_be_local(url, local):
    assert ocr.is_local_endpoint(url) is local


def test_production_refuses_an_outside_ocr_endpoint():
    base = dict(env="production", secret_key="x" * 40, encryption_key="k", bootstrap_admin_password="p",
                database_url="postgresql+psycopg://u:p@db/x")
    Settings(**base, ocr_backend="vllm", ocr_base_url="http://ocr:8000/v1").validate_for_startup()
    with pytest.raises(RuntimeError, match="trusted boundary"):
        Settings(**base, ocr_backend="vllm", ocr_base_url="https://ocr.some-cloud.example/v1").validate_for_startup()
    with pytest.raises(RuntimeError, match="development only"):
        Settings(**base, ocr_backend="mock").validate_for_startup()


def test_prepare_image_reencodes_strips_metadata_and_downscales():
    out = ocr.prepare_image(png_bytes(exif_gps=True))
    im = Image.open(io.BytesIO(out))
    assert im.format == "PNG" and not im.getexif()
    big = Image.open(io.BytesIO(ocr.prepare_image(png_bytes(size=(5000, 3000)))))
    assert max(big.size) == ocr.MAX_IMAGE_SIDE
    with pytest.raises(DocumentError):
        ocr.prepare_image(b"not an image at all")


def test_vllm_request_follows_the_model_card():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        content = "<|ref|>text<|/ref|><|det|>[[1,2,3,4]]<|/det|>\nIdentity Number: 42101-1234567-1"
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})

    client = ocr.OcrClient(Settings(ocr_base_url="http://ocr:8000/v1"), transport=httpx.MockTransport(handler))
    text = client.recognise(png_bytes())
    body = seen["body"]
    assert seen["url"] == "http://ocr:8000/v1/chat/completions"
    assert body["model"] == "baidu/Unlimited-OCR" and body["temperature"] == 0.0
    assert body["skip_special_tokens"] is False and body["vllm_xargs"] == {"ngram_size": 35, "window_size": 128}
    parts = body["messages"][0]["content"]
    assert parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert parts[1] == {"type": "text", "text": "<image>document parsing."}
    assert text == "Identity Number: 42101-1234567-1"


def test_ocr_service_errors_are_reported_as_unavailable():
    client = ocr.OcrClient(Settings(), transport=httpx.MockTransport(lambda r: httpx.Response(500, text="boom")))
    with pytest.raises(ocr.OcrUnavailable):
        client.recognise(png_bytes())


def test_images_need_ocr_and_scanned_pdf_pages_are_ocrd():
    with pytest.raises(DocumentError, match="not enabled"):
        extract_document("card.png", png_bytes(), 100, ocr=None)
    fake = FakeOcr()
    result = extract_document("card.jpg", png_bytes(), 100, ocr=fake)
    assert result.ocr_pages == 1 and "42101-1234567-1" in result.pages[0]

    long_text = "Scanned minutes of the examination committee. " * 10
    scanned = extract_document("scan.pdf", blank_pdf(2), 100, ocr=FakeOcr(long_text))
    assert scanned.ocr_pages == 2 and scanned.pages[1].startswith("Scanned minutes")
    with pytest.raises(DocumentError, match="need OCR"):
        extract_document("scan.pdf", blank_pdf(2), 100, ocr=None)
    with pytest.raises(DocumentError, match="limited to 1"):
        extract_document("scan.pdf", blank_pdf(2), 100, ocr=FakeOcr(long_text), ocr_max_pages=1)


def test_cnic_photo_is_read_locally_and_keeps_the_answer_local(client, root):
    user = make_user(client, root)
    files = {"file": ("cnic_photo.png", png_bytes(), "image/png")}
    assert client.post("/api/documents", files=files, headers=user).status_code == 422  # OCR off

    fake = FakeOcr()
    ocr.set_ocr(fake)
    assert client.get("/api/auth/permissions", headers=user).json()["ocr_enabled"] is True
    doc = client.post("/api/documents", files=files, data={"label": "public"}, headers=user)
    assert doc.status_code == 201 and doc.json()["ocr_pages"] == 1 and fake.calls == 1

    session = client.post("/api/chat/sessions", json={"document_ids": [doc.json()["id"]]}, headers=user).json()
    question = "Compare the identity number on the attached card with the form and justify any mismatch step by step"
    response = client.post(f"/api/chat/sessions/{session['id']}/messages", json={"content": question}, headers=user)
    done = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")][-1]["meta"]
    # Even labelled public, the CNIC read from the photo is detected, so a hard
    # question that would normally go to the strong cloud model stays local.
    assert done["sensitive"] and "NATIONAL_ID" in done["entity_types"]
    assert done["model"] == "mock-local" and MockProvider.dispatched == []
    log = client.get("/api/audit/confidential", headers=root).json()
    assert log[0]["entity_types"] == ["NATIONAL_ID"] and not log[0]["left_trusted_boundary"]


def test_ocr_unavailable_returns_503(client, root):
    class Down:
        def recognise(self, png):
            raise ocr.OcrUnavailable("down")

    ocr.set_ocr(Down())
    user = make_user(client, root)
    r = client.post("/api/documents", files={"file": ("a.png", png_bytes(), "image/png")}, headers=user)
    assert r.status_code == 503
