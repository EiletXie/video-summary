import os
import logging
from typing import Callable, Optional

# Route HF through local proxy (mirror endpoint is unreliable for model files)
os.environ["HF_ENDPOINT"] = "https://huggingface.co"
os.environ["HTTPS_PROXY"] = os.environ.get("HTTPS_PROXY", "http://127.0.0.1:7892")
os.environ["HTTP_PROXY"] = os.environ.get("HTTP_PROXY", "http://127.0.0.1:7892")

from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

_models: dict[str, WhisperModel] = {}

MODELS = {
    "tiny":   ("tiny",   "int8"),
    "base":   ("base",   "int8"),
    "medium": ("medium", "int8"),
}


def _get_model(name: str) -> WhisperModel:
    """Get or load a Whisper model (thread-safe lazy singleton)."""
    if name not in _models:
        size, compute = MODELS.get(name, MODELS["base"])
        logger.info("loading Whisper model: %s (compute=%s)...", size, compute)
        _models[name] = WhisperModel(size, device="cpu", compute_type=compute)
        logger.info("Whisper model %s loaded", size)
    return _models[name]


def transcribe(audio_path: str, model_name: str = "base",
               progress: Optional[Callable] = None) -> str:
    """Transcribe audio to Chinese text using faster-whisper."""
    if progress:
        progress("transcribing", 40, f"正在本地语音转写(Whisper {model_name})...")

    logger.info("transcribe start audio=%s model=%s", audio_path, model_name)
    model = _get_model(model_name)
    segments, info = model.transcribe(audio_path, language="zh", beam_size=5)
    text = " ".join(s.text for s in segments).strip()
    logger.info("transcribe done model=%s duration=%.1fs text_len=%s",
                model_name, info.duration, len(text))
    return text
