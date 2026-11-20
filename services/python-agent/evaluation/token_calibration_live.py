"""Opt-in synthetic text/schema/native-image calibration; no business writes."""
import argparse
import asyncio
import base64
from io import BytesIO
import json
from pathlib import Path
from typing import Literal

from langchain_core.messages import HumanMessage
from PIL import Image
from pydantic import BaseModel

from app.config import get_llm, settings
from app.services.run_metrics import RunMetrics
from evaluation.token_calibration import summarize


class Reply(BaseModel):
    status: Literal['ok']


async def run(output):
    output.mkdir(parents=True, exist_ok=False)
    image = Image.new('RGB', (256, 256), (60, 100, 180))
    buffer = BytesIO(); image.save(buffer, format='PNG')
    part = {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()}}
    samples = [('chinese', '这是合成的上下文预算测试资料，不修改任何任务。' * 300, False, False),
               ('english', 'This is synthetic context calibration, with no business operations. ' * 300, False, False),
               ('code', 'def f(value):\n    return {"result": value + 1, "ok": True}\n' * 300, False, False),
               ('mixed', '中文 note Java Redis checkpoint 2026 😀\n' * 300, False, False),
               ('schema', '仅做结构化输出预算校准。' * 100, True, False),
               ('image', '附图是本次测试生成的单色图，不涉及用户图片。', False, True)]
    report = {'real_provider_calls': True, 'synthetic_fixtures': True, 'model': settings.DEEPSEEK_MODEL, 'rows': []}
    for repeat in range(2):
        for name, text, schema, visual in samples:
            meter = RunMetrics()
            content = '以下是无须解释的测试资料，只回答' + ('status=ok。' if schema else 'OK。') + '\n' + text
            messages = [HumanMessage(content=[{'type': 'text', 'text': content}, part] if visual else content)]
            model = get_llm(temperature=0, max_tokens=64, max_retries=0)
            if schema: model = model.with_structured_output(Reply, method='function_calling')
            row = {'id': f'{name}_{repeat+1}'}
            try:
                await asyncio.wait_for(model.ainvoke(messages, config={'callbacks': [meter]}), 45)
                row['passed'] = meter.snapshot()['measured_llm_calls'] > 0
            except Exception as exc:
                row.update(passed=False, error_type=type(exc).__name__)
            row['metrics'] = meter.snapshot()
            report['rows'].append(row)
            report['calibration'] = summarize(pair for item in report['rows'] for pair in item['metrics']['token_calibration'])
            (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'cases': len(report['rows']), 'passed': sum(row['passed'] for row in report['rows']),
                      'calibration': report['calibration']}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.output.resolve()))
