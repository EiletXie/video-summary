import os
import re
import logging
import tempfile
import requests
from urllib.parse import urlparse, parse_qs
from typing import Callable, Optional

import yt_dlp

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
}


def detect_platform(url: str) -> str:
    if "bilibili.com" in url or "b23.tv" in url:
        return "bilibili"
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    return "generic"


def extract_video_info(url: str) -> dict:
    """Extract title and other metadata without downloading."""
    platform = detect_platform(url)

    if platform == "bilibili":
        logger.info("bilibili URL, trying API for video info...")
        info = _bilibili_video_info_via_api(url)
        if info:
            logger.info("bilibili API OK: title=%s", info.get("title"))
            return info
        logger.warning("bilibili API failed, falling back to yt-dlp")

    logger.info("extract_video_info via yt-dlp...")
    ydl_opts = {"quiet": True, "no_warnings": True, "extract_flat": False, "cachedir": False}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return {
            "title": info.get("title", "未知标题"),
            "duration": info.get("duration", 0),
            "platform": platform,
        }


def _bilibili_video_info_via_api(url: str) -> Optional[dict]:
    """Get B站 video title via API (fast, no yt-dlp needed)."""
    bvid = _extract_bvid(url)
    if not bvid:
        return None
    try:
        resp = requests.get(
            f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}",
            headers=HEADERS, timeout=10,
        )
        if resp.json()["code"] != 0:
            return None
        data = resp.json()["data"]
        return {
            "title": data.get("title", "未知标题"),
            "duration": data.get("duration", 0),
            "platform": "bilibili",
        }
    except Exception:
        return None


def get_subtitle_text(url: str, progress: Optional[Callable] = None) -> Optional[str]:
    """Try to get subtitle text. Returns None if no usable subtitles."""
    platform = detect_platform(url)
    logger.info("get_subtitle_text platform=%s", platform)

    if platform == "bilibili":
        logger.info("trying bilibili subtitle API...")
        text = _bilibili_subtitle_via_api(url)
        if text:
            logger.info("bilibili subtitle API OK, len=%s", len(text))
            return text
        logger.info("bilibili subtitle API returned no usable subtitle")

    logger.info("trying yt-dlp subtitle download...")
    text = _ytdlp_subtitle(url, progress)
    if text:
        logger.info("yt-dlp subtitle OK, len=%s", len(text))
    else:
        logger.info("no subtitle found via yt-dlp")
    return text


def _bilibili_subtitle_via_api(url: str) -> Optional[str]:
    """Try B站 API to get Chinese subtitles."""
    bvid = _extract_bvid(url)
    if not bvid:
        logger.info("_bilibili_subtitle: cannot extract bvid")
        return None

    try:
        cid = _get_bilibili_cid(bvid)
        if not cid:
            logger.info("_bilibili_subtitle: cannot get cid")
            return None

        sub_resp = requests.get(
            f"https://api.bilibili.com/x/player/v2?bvid={bvid}&cid={cid}",
            headers=HEADERS, timeout=10,
        )
        sub_data = sub_resp.json()
        if sub_data["code"] != 0:
            logger.info("_bilibili_subtitle: player api returned code=%s", sub_data["code"])
            return None

        subtitle_info = sub_data["data"].get("subtitle")
        if not subtitle_info or not subtitle_info.get("subtitles"):
            logger.info("_bilibili_subtitle: no subtitles for this video")
            return None

        subtitles = subtitle_info["subtitles"]
        candidates = []
        for sub in subtitles:
            if sub["lan"] == "zh-CN":
                candidates.insert(0, sub)
            elif sub["lan"] == "ai-Zh":
                candidates.append(sub)
        logger.info("_bilibili_subtitle: found %d subtitle(s), %d zh candidate(s)",
                    len(subtitles), len(candidates))

        for sub in candidates:
            try:
                sub_url = "https:" + sub["subtitle_url"]
                content_resp = requests.get(sub_url, headers=HEADERS, timeout=10)
                body = content_resp.json()["body"]
                text = " ".join(item["content"] for item in body).strip()
                if len(text) >= 50:
                    return text
            except Exception as exc:
                logger.warning("_bilibili_subtitle: fetch subtitle content failed: %s", exc)
                continue
    except Exception as exc:
        logger.warning("_bilibili_subtitle: unexpected error: %s", exc)
        pass
    return None


def _get_bilibili_cid(bvid: str) -> Optional[int]:
    """Get CID for a B站 video."""
    try:
        resp = requests.get(
            f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}",
            headers=HEADERS, timeout=10,
        )
        if resp.json()["code"] != 0:
            return None
        return resp.json()["data"]["pages"][0]["cid"]
    except Exception as exc:
        logger.warning("_get_bilibili_cid failed: %s", exc)
        return None


def _extract_bvid(url: str) -> Optional[str]:
    parsed = urlparse(url)
    if "bvid=" in parsed.query:
        return parse_qs(parsed.query)["bvid"][0]
    match = re.search(r"BV[\w]+", parsed.path)
    if match:
        return match.group(0)
    return None


def _ytdlp_subtitle(url: str, progress: Optional[Callable] = None) -> Optional[str]:
    """Use yt-dlp to download subtitles."""
    tmpdir = tempfile.mkdtemp()
    try:
        ydl_opts = {
            "writesubtitles": True,
            "subtitleslangs": ["zh-Hans", "zh-CN", "zh", "en", "all"],
            "writeautomaticsub": True,
            "skip_download": True,
            "outtmpl": os.path.join(tmpdir, "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "cachedir": False,
        }
        if progress:
            progress("downloading", 15, "正在检查字幕...")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        for f in os.listdir(tmpdir):
            if f.endswith((".vtt", ".srt")):
                filepath = os.path.join(tmpdir, f)
                with open(filepath, "r", encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
                text = _clean_subtitle(content, f.endswith(".vtt"))
                if len(text) >= 50:
                    return text
    except Exception:
        pass
    finally:
        _rmtree(tmpdir)
    return None


def _clean_subtitle(content: str, is_vtt: bool) -> str:
    """Remove timestamp lines and HTML tags from subtitles."""
    lines = content.split("\n")
    cleaned = []
    for line in lines:
        line = line.strip()
        if not line or line.isdigit():
            continue
        if "-->" in line:
            continue
        if line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
            continue
        # Remove HTML tags like <c> <00:00:01.234>
        line = re.sub(r"<[^>]+>", "", line)
        line = re.sub(r"\{[^}]+\}", "", line)
        if line:
            cleaned.append(line)
    return " ".join(cleaned)


def download_audio(url: str, output_dir: str, progress: Optional[Callable] = None) -> str:
    """Download audio only, return path to audio file."""
    if progress:
        progress("downloading", 20, "正在下载音频...")

    logger.info("download_audio url=%s", url)
    platform = detect_platform(url)

    # B站: use official API — much faster and more reliable than yt-dlp
    if platform == "bilibili":
        audio_path = _bilibili_audio_via_api(url, output_dir)
        if audio_path:
            size_kb = os.path.getsize(audio_path) / 1024
            logger.info("downloaded audio (bilibili API): %s (%.0f KB)", os.path.basename(audio_path), size_kb)
            return audio_path
        logger.warning("bilibili audio API failed, falling back to yt-dlp")

    # yt-dlp for YouTube and other platforms
    output_template = os.path.join(output_dir, "%(id)s.%(ext)s")
    ydl_opts = {
        "format": "worstaudio/worst",
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 60,
        "retries": 3,
        "fragment_retries": 3,
        "cachedir": False,
        "proxy": "http://127.0.0.1:7892",
        "concurrent_fragment_downloads": 8,
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        "throttledratelimit": 0,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        video_id = info.get("id", "audio")

    for filename in os.listdir(output_dir):
        if os.path.splitext(filename)[0].startswith(video_id):
            filepath = os.path.join(output_dir, filename)
            size_kb = os.path.getsize(filepath) / 1024
            logger.info("downloaded audio: %s (%.0f KB)", filename, size_kb)
            return filepath

    raise FileNotFoundError("未找到下载的音频文件")


def _bilibili_audio_via_api(url: str, output_dir: str) -> Optional[str]:
    """Download B站 audio via official playurl API. Bypasses yt-dlp entirely."""
    bvid = _extract_bvid(url)
    if not bvid:
        return None
    cid = _get_bilibili_cid(bvid)
    if not cid:
        return None

    try:
        # Get DASH play URLs
        play_resp = requests.get(
            f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}"
            "&fnval=16&fnver=0&fourk=1",
            headers=HEADERS, timeout=10,
        )
        if play_resp.json()["code"] != 0:
            logger.warning("bilibili playurl API returned error code")
            return None

        dash = play_resp.json()["data"].get("dash")
        if not dash or not dash.get("audio"):
            logger.warning("bilibili playurl: no DASH audio streams")
            return None

        # Pick lowest-bitrate audio (smallest = fastest download, good enough for Whisper)
        audio_streams = sorted(dash["audio"], key=lambda a: a.get("bandwidth", 999999))
        best = audio_streams[0]
        audio_url = best["base_url"]
        logger.info("bilibili audio: bandwidth=%d kbps", best.get("bandwidth", 0) // 1000)

        # Download audio
        dl_headers = {**HEADERS, "Referer": "https://www.bilibili.com/"}
        resp = requests.get(audio_url, headers=dl_headers, timeout=120, stream=True)
        resp.raise_for_status()

        # Save to output_dir
        ext = "m4a" if "mp4" in best.get("mime_type", "") else "audio"
        filepath = os.path.join(output_dir, f"{bvid}.{ext}")
        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        return filepath
    except Exception as exc:
        logger.warning("bilibili audio API failed: %s", exc)
        return None


def _rmtree(path: str):
    try:
        import shutil
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass
