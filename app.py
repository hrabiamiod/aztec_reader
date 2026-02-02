from __future__ import annotations

import io
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from redis import Redis
from rq import Queue
from rq.job import Job

from worker import process_pdf

APP_TITLE = "Aztec Reader"
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "30"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "120"))
JOB_TIMEOUT_SECONDS = int(os.getenv("JOB_TIMEOUT_SECONDS", "300"))

TMP_DIR = os.getenv("TMP_DIR", "/tmp")

app = FastAPI(title=APP_TITLE)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

redis_conn = Redis.from_url(REDIS_URL)
queue = Queue("pdf", connection=redis_conn)


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return FileResponse(STATIC_DIR / "index.html")


def _save_upload(file: UploadFile) -> str:
    suffix = os.path.splitext(file.filename or "upload.pdf")[1] or ".pdf"
    temp_name = f"{uuid.uuid4().hex}{suffix}"
    temp_path = os.path.join(TMP_DIR, temp_name)
    total = 0
    with open(temp_path, "wb") as handle:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_FILE_SIZE_MB * 1024 * 1024:
                handle.close()
                os.remove(temp_path)
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds max size of {MAX_FILE_SIZE_MB}MB",
                )
            handle.write(chunk)
    return temp_path


@app.post("/api/jobs")
def create_jobs(
    files: List[UploadFile] = File(...),
    only_aztec: bool = Form(True),
) -> Dict[str, Any]:
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    job_ids = []
    for upload in files:
        if not upload.filename or not upload.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are supported")

        temp_path = _save_upload(upload)
        job = queue.enqueue(
            process_pdf,
            temp_path,
            upload.filename,
            only_aztec,
            MAX_PAGES,
            job_timeout=JOB_TIMEOUT_SECONDS,
        )
        job_ids.append(job.id)

    return {"job_ids": job_ids}


def _serialize_job(job: Job) -> Dict[str, Any]:
    meta = job.meta or {}
    progress = meta.get("progress", {"done": 0, "total": 0, "note": ""})
    result = meta.get("result")
    status = job.get_status(refresh=True)

    if status == "failed":
        error = meta.get("error", "Job failed")
        return {
            "status": status,
            "progress": progress,
            "error": error,
        }

    payload: Dict[str, Any] = {
        "status": status,
        "progress": progress,
    }
    if status == "finished":
        payload["result"] = result or []
    return payload


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> Dict[str, Any]:
    try:
        job = Job.fetch(job_id, connection=redis_conn)
    except Exception as exc:  # pragma: no cover - rq raises generic exceptions
        raise HTTPException(status_code=404, detail="Job not found") from exc

    return _serialize_job(job)


@app.get("/api/jobs/{job_id}/download")
def download(job_id: str, fmt: str = "json") -> Response:
    try:
        job = Job.fetch(job_id, connection=redis_conn)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc

    if job.get_status(refresh=True) != "finished":
        raise HTTPException(status_code=409, detail="Job not finished")

    result = job.meta.get("result")
    if result is None:
        raise HTTPException(status_code=404, detail="No result available")

    if fmt == "json":
        return JSONResponse(result)

    if fmt == "csv":
        output = io.StringIO()
        output.write("file,page,format,text\n")
        for row in result:
            text = (row.get("text") or "").replace('"', '""')
            output.write(
                f"\"{row.get('file','')}\",{row.get('page','')},"
                f"\"{row.get('format','')}\",\"{text}\"\n"
            )
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={job_id}.csv"},
        )

    raise HTTPException(status_code=400, detail="Unknown format")


@app.get("/api/limits")
def limits() -> Dict[str, Any]:
    return {
        "max_file_size_mb": MAX_FILE_SIZE_MB,
        "max_pages": MAX_PAGES,
        "job_timeout_seconds": JOB_TIMEOUT_SECONDS,
    }
