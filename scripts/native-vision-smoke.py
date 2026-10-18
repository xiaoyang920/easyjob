"""One optional live call with a disposable generated image, never user uploads.

Run explicitly: python-agent/.venv/Scripts/python.exe scripts/native-vision-smoke.py
Uses the configured DeepSeek credentials and consumes a small model allowance.
"""
import asyncio
import json
import random
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from urllib.parse import urlparse
from unittest.mock import patch
from typing import Literal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field
from app.config import settings, get_llm
from app.services.multimodal import image_part
from langchain_core.messages import HumanMessage


class VisualCheck(BaseModel):
    """Identify the colors of two squares, not their pixel coordinates."""
    top_left: Literal['red', 'blue', 'yellow', 'green'] = Field(description='Color of the top-left square, in English; never coordinates.')
    bottom_right: Literal['red', 'blue', 'yellow', 'green'] = Field(description='Color of the bottom-right square, in English; never coordinates.')


async def main():
    if urlparse(settings.DEEPSEEK_BASE_URL).hostname != 'api.deepseek.com':
        raise RuntimeError('This live test only sends its generated image to the official DeepSeek endpoint.')
    colors = [('red', '#ff0000'), ('blue', '#0000ff'), ('yellow', '#ffff00'), ('green', '#00aa00')]
    random.SystemRandom().shuffle(colors)
    with TemporaryDirectory(dir=ROOT / 'temp') as directory:
        relative = 'ai-chat/1/generated-probe.png'
        target = Path(directory) / relative
        target.parent.mkdir(parents=True)
        canvas = Image.new('RGB', (128, 128))
        draw = ImageDraw.Draw(canvas)
        for index, (_, color) in enumerate(colors):
            left, top = index % 2 * 64, index // 2 * 64
            draw.rectangle((left, top, left+63, top+63), fill=color)
        canvas.save(target)
        with patch.object(settings, 'FILE_UPLOAD_PATH', directory):
            part = image_part(relative, 1)
        model = get_llm(temperature=0, max_tokens=200, max_retries=0, timeout=45)
        structured = model.with_structured_output(VisualCheck, method='function_calling')
        messages = [HumanMessage(content=[{'type':'text','text':
            'Read this 2 by 2 color grid. Return the top-left and bottom-right colors as English color names, from red, blue, yellow, green.'}, part])]
        started = perf_counter()
        result = None
        async for parsed in structured.astream(messages):
            result = parsed
        if result is None:
            raise RuntimeError('No structured vision response.')
        expected = {'top_left': colors[0][0], 'bottom_right': colors[3][0]}
        actual = result.model_dump()
        report = {'model': settings.DEEPSEEK_MODEL, 'synthetic_image_only': True,
            'streaming': True, 'structured_tool_call': True, 'expected': expected,
            'actual': actual, 'passed': actual == expected, 'elapsed_seconds': round(perf_counter()-started, 2)}
        (ROOT / 'logs/native-vision-live.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2))
        if not report['passed']:
            raise RuntimeError('The visual response did not match the generated fixture.')


if __name__ == '__main__':
    asyncio.run(main())
