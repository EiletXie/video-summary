import logging
from typing import Callable, Optional
from openai import OpenAI
import httpx

from backend.config import (
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL,
    OLLAMA_BASE_URL, OLLAMA_MODEL,
)

logger = logging.getLogger(__name__)


PROMPTS = {
    "brief": (
        "你是一个专业的视频内容总结助手。请用中文对以下视频文本进行简洁总结。\n"
        "要求：\n"
        "1. 一句话概括核心内容（不超过50字）\n"
        "2. 列出3-5个关键信息点\n"
        "3. 总字数控制在200字以内\n\n"
        "视频文本：\n{text}"
    ),
    "standard": (
        "你是一个专业的视频内容总结助手。请用中文对以下视频文本进行分段总结。\n"
        "要求：\n"
        "1. 主题概述（1-2句话）\n"
        "2. 核心内容分点总结（3-5个大点，每点2-3句话）\n"
        "3. 关键结论或要点\n"
        "4. 总字数控制在800字以内\n\n"
        "视频文本：\n{text}"
    ),
    "detailed": (
        "你是一个专业的视频内容总结助手。请用中文对以下视频文本进行详细总结。\n"
        "要求：\n"
        "1. 视频基本信息概述\n"
        "2. 按章节/主题分段总结\n"
        "3. 每段包含核心观点和关键论据\n"
        "4. 引用原文中的关键语句（标注时间戳如果可用）\n"
        "5. 总结与延伸思考\n"
        "6. 总字数控制在2000字左右\n\n"
        "视频文本：\n{text}"
    ),
}

FORMAT_PROMPT = (
    "你的任务是**原样整理**一段视频转录文本。你必须逐句保留原文，只做排版美化。\n\n"
    "【严格禁止】\n"
    "- 禁止总结、概括、缩写、提炼\n"
    "- 禁止删减任何句子或段落\n"
    "- 禁止改写原文的意思或语气\n"
    "- 禁止添加原文中没有的信息\n\n"
    "【你需要做的】\n"
    "1. 按话题变化插入 ## 二级标题\n"
    "2. 修正明显的错别字和错误标点（不要改专业术语）\n"
    "3. 合理分段：每3-5句话为一个自然段，话题切换必须另起一段\n"
    "4. 说话人切换、问答交替、举例、转折处都要分段\n"
    "5. 每个段落之间用空行分隔，绝不允许出现超过10句话的大段\n\n"
    "【输出要求】\n"
    "- 输出长度必须与原文接近，不能明显变短\n"
    "- 宁可少加标题，也绝不能删减内容\n"
    "- 全文必须有多处段落分隔，不能是一整块文字\n\n"
    "转录文本：\n{text}"
)


def summarize(text: str, granularity: str, llm_source: str,
              progress: Optional[Callable] = None) -> str:
    """Summarize text using local Ollama or remote DeepSeek API."""
    model_name = OLLAMA_MODEL if llm_source == "local" else DEEPSEEK_MODEL
    if progress:
        progress("summarizing", 70, f"正在调用大模型总结 ({model_name})...")

    prompt = PROMPTS.get(granularity, PROMPTS["standard"]).format(text=text)
    logger.info("summarize source=%s model=%s granularity=%s prompt_len=%s",
                llm_source, model_name, granularity, len(prompt))

    if llm_source == "local":
        return _ollama_call(prompt)
    else:
        return _deepseek_call(prompt)


def format_text(text: str, llm_source: str,
                progress: Optional[Callable] = None) -> str:
    """Format/beautify original transcript — keep content, improve layout."""
    model_name = OLLAMA_MODEL if llm_source == "local" else DEEPSEEK_MODEL
    if progress:
        progress("formatting", 70, f"正在调用大模型排版 ({model_name})...")

    prompt = FORMAT_PROMPT.format(text=text)
    logger.info("format_text source=%s model=%s prompt_len=%s text_len=%s",
                llm_source, model_name, len(prompt), len(text))

    if llm_source == "local":
        # High num_predict so output is NOT truncated (format should keep all content)
        return _ollama_call(prompt, num_predict=8192, num_ctx=16384)
    else:
        return _deepseek_call(prompt, max_tokens=8192)


def _ollama_call(prompt: str, num_predict: int = 2048, num_ctx: int = 4096) -> str:
    """Call Ollama local API."""
    logger.info("calling Ollama %s model=%s num_predict=%d ...",
                OLLAMA_BASE_URL, OLLAMA_MODEL, num_predict)
    resp = httpx.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": num_predict,
                "num_ctx": num_ctx,
            },
        },
        timeout=600,
    )
    resp.raise_for_status()
    data = resp.json()
    result_len = len(data.get("response", "").strip())
    logger.info("Ollama response OK, len=%s", result_len)
    return data.get("response", "").strip()


def _deepseek_call(prompt: str, max_tokens: int = 4096) -> str:
    """Call DeepSeek API via OpenAI-compatible SDK."""
    logger.info("calling DeepSeek API %s model=%s max_tokens=%d ...",
                DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, max_tokens)
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=max_tokens,
    )
    result_len = len(resp.choices[0].message.content.strip())
    logger.info("DeepSeek API response OK, len=%s", result_len)
    return resp.choices[0].message.content.strip()
