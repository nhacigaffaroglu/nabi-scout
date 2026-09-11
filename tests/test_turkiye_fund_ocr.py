from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services import turkiye_fund_ocr as mod


def test_rasterize_pdf_pages_uses_pdftoppm_and_preserves_page_order():
    def fake_run(cmd, **kwargs):
        prefix = Path(str(cmd[-1]))
        Path(f"{prefix}-2.png").write_bytes(b"PAGE-2")
        Path(f"{prefix}-1.png").write_bytes(b"PAGE-1")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    with (
        patch.object(mod.shutil, "which", return_value="/usr/bin/pdftoppm"),
        patch.object(mod.subprocess, "run", side_effect=fake_run),
    ):
        pages = mod.rasterize_pdf_pages(b"%PDF-1.4\nfake", max_pages=2)

    assert pages == [b"PAGE-1", b"PAGE-2"]


def test_tesseract_reads_raster_from_stdin():
    result = SimpleNamespace(
        returncode=0,
        stdout="Katılım fonu statüsündedir.".encode("utf-8"),
        stderr=b"",
    )

    with (
        patch.object(mod.shutil, "which", return_value="/usr/bin/tesseract"),
        patch.object(mod.subprocess, "run", return_value=result) as run,
    ):
        text = mod._tesseract_ocr(b"PNG-BYTES")

    assert text == "Katılım fonu statüsündedir."
    args, kwargs = run.call_args
    assert args[0][:3] == ["/usr/bin/tesseract", "stdin", "stdout"]
    assert kwargs["input"] == b"PNG-BYTES"


def test_ocr_prefers_rendered_pdf_pages():
    with (
        patch.object(mod, "rasterize_pdf_pages", return_value=[b"PAGE-1", b"PAGE-2"]),
        patch.object(mod, "extract_pdf_images") as embedded,
    ):
        text, origin = mod.ocr_official_pdf(
            b"%PDF-1.4\nfake",
            ocr_fn=lambda image: (
                "Danışma Komitesi icazet belgesi"
                if image == b"PAGE-2"
                else ""
            ),
        )

    assert text == "Danışma Komitesi icazet belgesi"
    assert origin == mod.TEXT_ORIGIN_OCR
    embedded.assert_not_called()


def test_ocr_falls_back_to_embedded_images_without_rasterizer():
    with (
        patch.object(mod, "rasterize_pdf_pages", return_value=[]),
        patch.object(mod, "extract_pdf_images", return_value=[b"EMBEDDED"]),
    ):
        text, origin = mod.ocr_official_pdf(
            b"%PDF-1.4\nfake",
            ocr_fn=lambda image: "katılım prensiplerine uygun",
        )

    assert text == "katılım prensiplerine uygun"
    assert origin == mod.TEXT_ORIGIN_OCR


def test_installed_engine_with_no_text_is_not_reported_as_unavailable():
    with (
        patch.object(mod, "rasterize_pdf_pages", return_value=[b"PAGE"]),
        patch.object(mod, "_tesseract_ocr", return_value=""),
        patch.object(mod, "_vision_ocr", return_value=""),
        patch.object(
            mod.shutil,
            "which",
            side_effect=lambda name: (
                "/usr/bin/tesseract" if name == "tesseract" else None
            ),
        ),
    ):
        text, reason = mod.ocr_official_pdf(b"%PDF-1.4\nfake")

    assert text is None
    assert reason == mod.OCR_NO_TEXT
