from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Any, Dict, List

import pypdfium2 as pdfium
from PIL import Image
from redis import Redis
from rq import get_current_job

try:
    import zxingcpp
except Exception:  # pragma: no cover - fallback path
    zxingcpp = None

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

DEFAULT_TIMEOUT = int(os.getenv("JOB_TIMEOUT_SECONDS", "300"))
ZXING_JAR_PATH = os.getenv("ZXING_JAR_PATH", "")

redis_conn = Redis.from_url(REDIS_URL)


def _update_progress(done: int, total: int, note: str = "") -> None:
    job = get_current_job()
    if not job:
        return
    job.meta["progress"] = {"done": done, "total": total, "note": note}
    job.save_meta()


def _decode_with_zxingcpp(image: Image.Image) -> List[Dict[str, Any]]:
    if zxingcpp is None:
        return []
    results = []
    for barcode in zxingcpp.read_barcodes(image):
        results.append(
            {
                "format": barcode.format.name,
                "text": barcode.text,
            }
        )
    return results


def _decode_with_zxingcli(image_path: str) -> List[Dict[str, Any]]:
    if not ZXING_JAR_PATH:
        return []

    cmd = [
        "java",
        "-jar",
        ZXING_JAR_PATH,
        "--try_harder",
        "--input",
        image_path,
        "--output",
        "stdout",
    ]
    try:
        completed = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT,
        )
    except Exception:
        return []

    results = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        fmt = parts[0].strip()
        text = "\t".join(parts[1:]).strip()
        results.append({"format": fmt, "text": text})
    return results


def _decode_image(image: Image.Image) -> List[Dict[str, Any]]:
    results = _decode_with_zxingcpp(image)
    if results:
        return results

    if not ZXING_JAR_PATH:
        return []

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        temp_path = tmp.name
        image.save(tmp, format="PNG")

    try:
        return _decode_with_zxingcli(temp_path)
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


def process_pdf(
    pdf_path: str,
    original_name: str,
    only_aztec: bool,
    max_pages: int,
) -> Dict[str, Any]:
    job = get_current_job()
    if job:
        job.meta["result"] = []
        job.meta["progress"] = {"done": 0, "total": 0, "note": "Starting"}
        job.save_meta()

    results: List[Dict[str, Any]] = []
    pdf = None
    try:
        try:
            pdf = pdfium.PdfDocument(pdf_path)
        except Exception as exc:
            if job:
                job.meta["error"] = "Failed to open PDF"
                job.save_meta()
            raise exc

        total_pages = len(pdf)
        if total_pages > max_pages:
            if job:
                job.meta["error"] = f"PDF exceeds max pages of {max_pages}"
                job.save_meta()
            raise ValueError("PDF exceeds max pages")

        if job:
            job.meta["progress"] = {"done": 0, "total": total_pages, "note": "Rendering"}
            job.save_meta()

        for index in range(total_pages):
            page_number = index + 1
            _update_progress(index, total_pages, note=f"Page {page_number}/{total_pages}")

            page = pdf.get_page(index)
            matched = False
            for dpi in (300, 400):
                scale = dpi / 72
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil().convert("L")
                decoded = _decode_image(image)

                if decoded:
                    for item in decoded:
                        fmt = item.get("format")
                        fmt_label = fmt or ""
                        if only_aztec and fmt_label.upper() != "AZTEC":
                            continue
                        results.append(
                            {
                                "file": original_name,
                                "page": page_number,
                                "format": fmt_label,
                                "text": item.get("text"),
                            }
                        )
                    matched = True
                if matched:
                    break
    finally:
        if pdf is not None:
            pdf.close()
        try:
            os.remove(pdf_path)
        except OSError:
            pass

    if job:
        job.meta["result"] = results
        job.meta["progress"] = {"done": total_pages, "total": total_pages, "note": "Done"}
        job.save_meta()

    return {"results": results}
