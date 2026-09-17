"""
图片理解服务
对应 Java: ImageUnderstandingService.java
使用智谱 GLM-4V 将图片转为文本描述
"""
import base64
import logging
from io import BytesIO
from pathlib import Path

from PIL import Image
from langchain_core.messages import HumanMessage

from app.config import settings, get_vision_llm

log = logging.getLogger(__name__)

MAX_IMAGE_DIMENSION = 1920
MAX_IMAGE_BYTES = 2 * 1024 * 1024  # 2MB


def _compress_image(image_bytes: bytes) -> bytes:
    """等比缩放 + JPEG 降质量，控制在 2MB 以内"""
    img = Image.open(BytesIO(image_bytes))
    # 等比缩放
    w, h = img.size
    if max(w, h) > MAX_IMAGE_DIMENSION:
        ratio = MAX_IMAGE_DIMENSION / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
    # 转 RGB（去除 alpha 通道）
    if img.mode != "RGB":
        img = img.convert("RGB")
    # 逐步降质量直到 < 2MB
    for quality in (85, 70, 50, 30):
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        if buf.tell() <= MAX_IMAGE_BYTES:
            return buf.getvalue()
    return buf.getvalue()


async def understand_image(image_path: str) -> str:
    """
    图片理解：调用 GLM-4V 返回图片描述

    image_path: 相对于上传目录的路径，如 "ai_chat/xxx.jpg"
    """
    llm = get_vision_llm()

    if settings.FILE_BASE_URL:
        # 生产环境：URL 方式
        image_url = f"{settings.FILE_BASE_URL}/{image_path}"
        log.info("使用URL方式: %s", image_url)
        content = [
            {"type": "text", "text": "请用中文解释图片内容，并给出图片的描述。"},
            {"type": "image_url", "image_url": {"url": image_url}},
        ]
    else:
        # 本地：读文件 → 压缩 → base64
        full_path = Path(settings.FILE_UPLOAD_PATH) / image_path
        image_bytes = full_path.read_bytes()
        log.info("原始图片大小: %d KB", len(image_bytes) // 1024)
        image_bytes = _compress_image(image_bytes)
        log.info("压缩后图片大小: %d KB", len(image_bytes) // 1024)
        b64 = base64.b64encode(image_bytes).decode()
        content = [
            {"type": "text", "text": "请用中文解释图片内容，并给出图片的描述。"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]

    resp = await llm.ainvoke([HumanMessage(content=content)])
    log.info("图片理解完成，描述长度: %d 字符", len(resp.content))
    return resp.content


async def preprocess_message(user_message: str, image_paths: list[str] | None) -> str:
    """
    预处理用户消息：将图片转为文字描述，拼接到消息前面
    对应 Java: AgentService.preprocessMessage()
    """
    if not image_paths:
        return user_message

    parts = []
    for i, path in enumerate(image_paths):
        try:
            description = await understand_image(path)
            parts.append(f"[图片{i + 1}内容：{description}]")
        except Exception as e:
            log.error("图片%d理解失败: %s", i + 1, e)
            parts.append(f"[图片{i + 1}：处理失败]")

    if user_message:
        parts.append(f"用户的问题：{user_message}")

    return "\n".join(parts)
