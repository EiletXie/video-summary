import json
import logging
import os
import uuid
from datetime import datetime

from backend.config import OUTPUT_DIR

logger = logging.getLogger(__name__)

INDEX_FILE = os.path.join(OUTPUT_DIR, "index.json")


def _load_index() -> list:
    if not os.path.exists(INDEX_FILE):
        return []
    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_index(items: list):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def save(title: str, url: str, platform: str, mode: str,
         html_content: str, granularity: str = None, llm_source: str = None) -> str:
    item_id = str(uuid.uuid4())
    date_str = datetime.now().strftime("%Y-%m-%d")
    safe_title = _safe_filename(title)[:50]
    filename = f"{date_str}_{safe_title}_{item_id[:8]}.html"
    filepath = os.path.join(OUTPUT_DIR, filename)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_content)

    items = _load_index()
    items.insert(0, {
        "id": item_id,
        "title": title,
        "url": url,
        "platform": platform,
        "mode": mode,
        "granularity": granularity,
        "llm_source": llm_source,
        "created_at": datetime.now().isoformat(),
        "filename": filename,
    })
    _save_index(items)
    logger.info("saved id=%s title=%s file=%s", item_id[:8], title, filename)
    return item_id


def list_all() -> list:
    return _load_index()


def get(item_id: str) -> dict | None:
    items = _load_index()
    for item in items:
        if item["id"] == item_id:
            filepath = os.path.join(OUTPUT_DIR, item["filename"])
            if os.path.exists(filepath):
                item["html"] = open(filepath, "r", encoding="utf-8").read()
                return item
    return None


def delete(item_id: str) -> bool:
    items = _load_index()
    for item in items:
        if item["id"] == item_id:
            filepath = os.path.join(OUTPUT_DIR, item["filename"])
            if os.path.exists(filepath):
                os.remove(filepath)
            items.remove(item)
            _save_index(items)
            return True
    return False


def _safe_filename(s: str) -> str:
    return "".join(c for c in s if c.isalnum() or c in "._- ").strip()
