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


def _tesseract_ocr(image: bytes) -> str:
    exe = shutil.which("tesseract")
    if not exe:
        return ""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "page.bin"
        path.write_bytes(image)
        proc = subprocess.run(
            [exe, str(path), "stdout", "-l", "tur+eng"],
            capture_output=True,
            timeout=60,
            check=False,
        )
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
    images = extract_pdf_images(payload, max_images=max_images)
    if not images:
        return None, "no_embedded_images"
    engine = ocr_fn or _tesseract_ocr
    parts: list[str] = []
    for image in images:
        text = ""
        try:
            text = engine(image)
        except Exception:  # noqa: BLE001 — OCR must fail closed
            text = ""
        if not text and ocr_fn is None:
            try:
                text = _vision_ocr(image)
            except Exception:  # noqa: BLE001
                text = ""
        if text:
            parts.append(text)
    joined = "\n".join(parts).strip()
    if not joined:
        return None, OCR_UNAVAILABLE
    return joined, TEXT_ORIGIN_OCR
