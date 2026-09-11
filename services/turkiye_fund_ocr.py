"""Last-resort OCR of official image-only KAP documents.

Not the universe default path. Callers must try KAP HTML / file text /
embedded PDF text first. OCR success does not upgrade confidence.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

from services.turkiye_fund_pdf_text import PDF_MAGIC, unwrap_kap_file_bytes

TEXT_ORIGIN_OCR = "OCR_FROM_OFFICIAL_DOCUMENT"
OCR_UNAVAILABLE = "OCR_ENGINE_UNAVAILABLE"
OCR_NO_TEXT = "OCR_NO_TEXT"


def extract_pdf_images(payload: bytes, *, max_images: int = 40) -> list[bytes]:
    from pypdf import PdfReader
    import io

    data = unwrap_kap_file_bytes(payload)
    if not data.startswith(PDF_MAGIC):
        return []
    reader = PdfReader(io.BytesIO(data))
    images: list[bytes] = []
    for page in reader.pages:
        for image in list(getattr(page, "images", []) or ()):
            images.append(bytes(image.data))
            if len(images) >= max_images:
                return images
    return images


def rasterize_pdf_pages(
    payload: bytes,
    *,
    max_pages: int = 24,
    dpi: int = 200,
) -> list[bytes]:
    """Render official PDF pages to PNG before OCR."""
    exe = shutil.which("pdftoppm")
    if not exe:
        return []

    try:
        data = unwrap_kap_file_bytes(payload)
    except ValueError:
        return []
    if not data.startswith(PDF_MAGIC):
        return []

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "source.pdf"
        prefix = root / "page"
        source.write_bytes(data)

        try:
            proc = subprocess.run(
                [
                    exe,
                    "-f", "1",
                    "-l", str(max_pages),
                    "-r", str(dpi),
                    "-png",
                    str(source),
                    str(prefix),
                ],
                capture_output=True,
                timeout=180,
                check=False,
            )
        except Exception:
            return []

        if proc.returncode != 0:
            return []

        pages = sorted(
            root.glob("page-*.png"),
            key=lambda path: int(path.stem.rsplit("-", 1)[-1]),
        )
        return [path.read_bytes() for path in pages[:max_pages]]


def _tesseract_ocr(image: bytes) -> str:
    exe = shutil.which("tesseract")
    if not exe:
        return ""

    proc = subprocess.run(
        [exe, "stdin", "stdout", "-l", "tur+eng"],
        input=image,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    return (proc.stdout or b"").decode("utf-8", "replace").strip()


def _vision_ocr(image: bytes) -> str:
    swift = shutil.which("swift")
    if not swift or os.uname().sysname != "Darwin":
        return ""
    source = r"""
import Foundation
import Vision
import AppKit
let path = CommandLine.arguments[1]
guard let img = NSImage(contentsOfFile: path),
      let tiff = img.tiffRepresentation,
      let bitmap = NSBitmapImageRep(data: tiff),
      let cg = bitmap.cgImage else { exit(1) }
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
request.recognitionLanguages = ["tr-TR", "en-US"]
try VNImageRequestHandler(cgImage: cg, options: [:]).perform([request])
let lines = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
print(lines.joined(separator: "\n"))
"""
    with tempfile.TemporaryDirectory() as tmp:
        img_path = Path(tmp) / "page.bin"
        src_path = Path(tmp) / "ocr.swift"
        img_path.write_bytes(image)
        src_path.write_text(source, encoding="utf-8")
        proc = subprocess.run(
            [swift, str(src_path), str(img_path)],
            capture_output=True,
            timeout=90,
            check=False,
        )
        return (proc.stdout or b"").decode("utf-8", "replace").strip()


def ocr_official_pdf(
    payload: bytes,
    *,
    ocr_fn: Optional[Callable[[bytes], str]] = None,
    max_images: int = 24,
) -> tuple[Optional[str], Optional[str]]:
    """Return (text, origin) or (None, reason). Never invents fields."""
    images = rasterize_pdf_pages(payload, max_pages=max_images)
    if not images:
        try:
            images = extract_pdf_images(payload, max_images=max_images)
        except Exception:
            return None, "pdf_unreadable"

    if not images:
        return None, "no_ocr_images"

    engine = ocr_fn or _tesseract_ocr
    parts: list[str] = []

    for image in images:
        text = ""
        try:
            text = engine(image)
        except Exception:
            text = ""

        if not text and ocr_fn is None:
            try:
                text = _vision_ocr(image)
            except Exception:
                text = ""

        if text:
            parts.append(text)

    joined = "\n".join(parts).strip()

    if not joined:
        if ocr_fn is None:
            tesseract_available = bool(shutil.which("tesseract"))
            vision_available = bool(
                shutil.which("swift") and os.uname().sysname == "Darwin"
            )
            if not tesseract_available and not vision_available:
                return None, OCR_UNAVAILABLE
        return None, OCR_NO_TEXT

    return joined, TEXT_ORIGIN_OCR
