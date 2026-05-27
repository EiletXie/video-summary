# HuggingFace: use proxy for mainland China access
import os as _os
_os.environ["HF_ENDPOINT"] = "https://huggingface.co"
_os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:7892")
_os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:7892")
_os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

import uuid
import asyncio
import tempfile
import os
import logging
import time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse

from backend.models.schemas import ProcessRequest, ProcessResponse, HistoryList, HistoryItem, ErrorResponse
from backend.services import video_service, whisper_service, llm_service, html_renderer, history_service
from backend.utils.sse_manager import store as task_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")

app = FastAPI(title="Video Summary Tool")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_cleanup():
    """Clean yt-dlp cache and temp leftovers on startup."""
    _cleanup_ytdlp_cache()
    _cleanup_old_tmpdirs()


def _cleanup_ytdlp_cache():
    """Remove yt-dlp internal cache to avoid accumulation."""
    import shutil
    cache_dirs = []
    # yt-dlp cache locations
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        cache_dirs.append(os.path.join(appdata, "yt-dlp"))
    home = os.path.expanduser("~")
    cache_dirs.append(os.path.join(home, ".cache", "yt-dlp"))
    cache_dirs.append(os.path.join(home, ".yt-dlp-cache"))

    for cache_dir in cache_dirs:
        if os.path.isdir(cache_dir):
            try:
                shutil.rmtree(cache_dir, ignore_errors=True)
                logger.info("cleaned yt-dlp cache: %s", cache_dir)
            except Exception:
                pass


def _cleanup_old_tmpdirs():
    """Remove leftover temp dirs from previous crashed runs."""
    import shutil
    tmp_root = tempfile.gettempdir()
    prefix = "tmp"  # tempfile.mkdtemp prefix
    try:
        for name in os.listdir(tmp_root):
            if not name.startswith("tmp"):
                continue
            full = os.path.join(tmp_root, name)
            if not os.path.isdir(full):
                continue
            # Only clean temp dirs older than 1 hour (avoid touching active ones)
            try:
                mtime = os.path.getmtime(full)
                if time.time() - mtime > 3600:
                    shutil.rmtree(full, ignore_errors=True)
                    logger.info("cleaned old tmpdir: %s", full)
            except Exception:
                pass
    except Exception:
        pass


def _progress_cb(task_id: str, stage: str, progress: int, message: str):
    logger.info("[%s] stage=%s progress=%s msg=%s", task_id[:8], stage, progress, message)
    task_store.update(task_id, stage=stage, progress=progress, message=message)


def _run_pipeline(task_id: str, req: ProcessRequest):
    """Synchronous pipeline, meant to run in a thread."""
    t0 = time.time()
    logger.info("[%s] ========== pipeline START ==========", task_id[:8])
    logger.info("[%s] url=%s mode=%s granularity=%s llm=%s",
                task_id[:8], req.url, req.mode, req.granularity, req.llm_source)

    tmpdir = tempfile.mkdtemp()
    logger.info("[%s] tmpdir=%s", task_id[:8], tmpdir)
    try:
        # Step 1: Video info
        _progress_cb(task_id, "fetching", 10, "正在获取视频信息...")
        t1 = time.time()
        info = video_service.extract_video_info(req.url)
        title = info["title"]
        platform = info["platform"]
        logger.info("[%s] step1 extract_video_info done (%.1fs) title=%s platform=%s",
                    task_id[:8], time.time() - t1, title, platform)

        # Step 2: Try subtitles
        _progress_cb(task_id, "downloading", 20, "正在尝试获取字幕...")
        t2 = time.time()
        text = video_service.get_subtitle_text(
            req.url,
            progress=lambda s, p, m: _progress_cb(task_id, s, p, m),
        )

        if text:
            _progress_cb(task_id, "subtitle", 30, f"已获取字幕，共{len(text)}字符")
            logger.info("[%s] step2 subtitle OK (%.1fs) text_len=%s",
                        task_id[:8], time.time() - t2, len(text))
        else:
            logger.info("[%s] step2 no subtitle found (%.1fs), downloading audio...",
                        task_id[:8], time.time() - t2)
            # Step 3: Download audio & transcribe
            _progress_cb(task_id, "downloading", 25, "无字幕，正在下载音频...")
            t3 = time.time()
            audio_path = video_service.download_audio(
                req.url, tmpdir,
                progress=lambda s, p, m: _progress_cb(task_id, s, p, m),
            )
            logger.info("[%s] step3 download_audio done (%.1fs) path=%s",
                        task_id[:8], time.time() - t3, audio_path)

            _progress_cb(task_id, "transcribing", 40, "正在本地语音转写(Whisper)...")
            t4 = time.time()
            text = whisper_service.transcribe(
                audio_path,
                model_name=req.whisper_model.value,
                progress=lambda s, p, m: _progress_cb(task_id, s, p, m),
            )
            logger.info("[%s] step3 transcribe done (%.1fs) text_len=%s",
                        task_id[:8], time.time() - t4, len(text))
            _progress_cb(task_id, "transcribing", 60, "转写完成")

        if not text or len(text) < 30:
            logger.warning("[%s] text too short or empty, len=%s", task_id[:8], len(text) if text else 0)
            _progress_cb(task_id, "error", 0, "提取文本为空或过短")
            task_store.update(task_id, stage="error", progress=0, message="提取文本为空或过短", status="error")
            return

        # Step 4: Summarize or original
        if req.mode == "summary":
            logger.info("[%s] step4 calling LLM summarize...", task_id[:8])
            t5 = time.time()
            summary = llm_service.summarize(
                text, req.granularity.value, req.llm_source.value,
                progress=lambda s, p, m: _progress_cb(task_id, s, p, m),
            )
            logger.info("[%s] step4 summarize done (%.1fs)", task_id[:8], time.time() - t5)
            _progress_cb(task_id, "summarizing", 85, "总结完成，正在生成页面...")
            html = html_renderer.render_summary(
                title, platform, req.url, summary,
                req.granularity.value, req.llm_source.value,
            )
        else:
            logger.info("[%s] step4 original mode, calling LLM to format...", task_id[:8])
            t5 = time.time()
            formatted = llm_service.format_text(
                text, req.llm_source.value,
                progress=lambda s, p, m: _progress_cb(task_id, s, p, m),
            )
            logger.info("[%s] step4 format_text done (%.1fs)", task_id[:8], time.time() - t5)
            _progress_cb(task_id, "rendering", 85, "排版完成，正在生成页面...")
            html = html_renderer.render_original(title, platform, req.url, formatted)

        # Step 5: Save
        _progress_cb(task_id, "saving", 90, "正在保存...")
        result_id = history_service.save(
            title=title,
            url=req.url,
            platform=platform,
            mode=req.mode.value,
            html_content=html,
            granularity=req.granularity.value if req.mode == "summary" else None,
            llm_source=req.llm_source.value,
        )
        logger.info("[%s] step5 save done result_id=%s", task_id[:8], result_id)

        _progress_cb(task_id, "done", 100, "完成")
        task_store.update(task_id, stage="done", progress=100, message="完成",
                          result_id=result_id, status="done")
        logger.info("[%s] ========== pipeline DONE (%.1fs total) ==========",
                    task_id[:8], time.time() - t0)

    except Exception as e:
        logger.exception("[%s] ========== pipeline ERROR (%.1fs total) ==========",
                         task_id[:8], time.time() - t0)
        _progress_cb(task_id, "error", 0, str(e))
        task_store.update(task_id, stage="error", progress=0, message=str(e), status="error")
    finally:
        _rmtree(tmpdir)


def _rmtree(path: str):
    """Remove a directory tree with retries (Windows file-locking resistant)."""
    import shutil
    import time as _time
    max_retries = 3
    for attempt in range(max_retries):
        try:
            shutil.rmtree(path, ignore_errors=True)
            if not os.path.exists(path):
                logger.info("cleaned tmpdir: %s", path)
                return
            # Some files still remain — retry after a short wait
            if attempt < max_retries - 1:
                remaining = len(os.listdir(path)) if os.path.isdir(path) else 0
                logger.warning("tmpdir not fully removed (%d items remain), retry %d/3: %s",
                              remaining, attempt + 2, path)
                _time.sleep(0.5)
        except Exception as exc:
            logger.warning("rmtree attempt %d/3 failed for %s: %s", attempt + 1, path, exc)
            _time.sleep(0.5)
    if os.path.exists(path):
        logger.warning("tmpdir could not be fully removed after retries: %s", path)


@app.post("/api/process", response_model=ProcessResponse)
async def process_video(req: ProcessRequest):
    task_id = str(uuid.uuid4())
    logger.info("[%s] POST /api/process url=%s mode=%s", task_id[:8], req.url, req.mode)
    task_store.create(task_id)
    asyncio.get_event_loop().run_in_executor(None, _run_pipeline, task_id, req)
    return ProcessResponse(task_id=task_id)


@app.get("/api/progress/{task_id}")
async def task_progress(task_id: str):
    logger.info("[%s] GET /api/progress (SSE connect)", task_id[:8])
    if not task_store.get(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")

    async def event_generator():
        import json
        last_progress = -1
        while True:
            task = task_store.get(task_id)
            if not task:
                logger.warning("[%s] SSE: task not found in store, breaking", task_id[:8])
                break
            current = task.get("progress", 0)
            status = task.get("status", "")
            if current != last_progress or status in ("done", "error"):
                payload = json.dumps({
                    "stage": task.get("stage", ""),
                    "progress": current,
                    "message": task.get("message", ""),
                    "result_id": task.get("result_id"),
                }, ensure_ascii=False)
                logger.info("[%s] SSE yield: progress=%s status=%s", task_id[:8], current, status)
                yield f"event: progress\ndata: {payload}\n\n"
                last_progress = current
            if status in ("done", "error"):
                logger.info("[%s] SSE: status=%s, closing stream", task_id[:8], status)
                break
            await asyncio.sleep(0.3)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/history", response_model=HistoryList)
async def get_history():
    items = history_service.list_all()
    return HistoryList(items=[HistoryItem(**item) for item in items])


@app.get("/api/output/{item_id}")
async def get_output(item_id: str):
    item = history_service.get(item_id)
    if not item or "html" not in item:
        raise HTTPException(status_code=404, detail="未找到")
    return HTMLResponse(content=item["html"])


@app.delete("/api/output/{item_id}")
async def delete_output(item_id: str):
    if history_service.delete(item_id):
        return {"ok": True}
    raise HTTPException(status_code=404, detail="未找到")


@app.get("/api/view/{item_id}")
async def view_output(item_id: str):
    """Serve the raw HTML file for opening in a new tab."""
    item = history_service.get(item_id)
    if not item or "html" not in item:
        raise HTTPException(status_code=404, detail="未找到")
    return HTMLResponse(content=item["html"])


@app.get("/")
async def root():
    return FileResponse("frontend/index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
