# DeepSeek 原生图片输入

当前图片和文字由同一个 Main Agent 直接处理，模型默认使用 `deepseek-flash`（DeepSeek V4.1 Flash 的推荐 API 名称）。不再调用 GLM 生成图片描述再拼接到问题前面。

官方格式参考：[DeepSeek 图片输入](https://api-docs.deepseek.com/zh-cn/guides/vision/)。通过 `DEEPSEEK_MODEL` 可以调整模型；切换时应确认目标模型同时支持图片和工具调用。

## 请求流程

1. 图片通过原来的上传入口保存到当前用户的 `ai-chat/{userId}/` 目录。
2. Java 经现有 RPC 转交文字和图片相对路径，Python 检查所属用户、路径及实际图片内容。
3. Main 调用前才读取图片，构造用户消息中的 `text`、`image_url` 部分。图片使用实际格式的 Base64 Data URL，文字保持用户原话。
4. DeepSeek 在同一次调用中理解图片并返回 MainDecision；后续检索、审批、停止、流式交付继续使用原有流程。

数据库、Redis 和 Checkpoint 仅保存图片引用，不保存 Base64。图片中的文字不会直接成为长期画像，记忆仍以当前用户明确原话为依据。

## 图片和历史预算

- 本轮最多 4 张图片，单张最多 8 MiB，支持 JPEG、PNG、GIF、WebP。依据实际内容判断格式。
- 当前图片优先，最多再带最近 4 张历史图片；重复文件按实际发送次数计算。
- 原图尺寸不超过 8192 像素/边及 2000 万总像素。沿用上传端压缩能力。
- 所有图片的 Base64 URL 合计最多约 32 MiB，为提供方 48 MiB 请求上限预留文字和工具结构空间。
- 上下文预算按每张 1024 visual tokens 保守预留；Base64 不是普通文本，不按字符串长度计算文本 Token。
- 单次请求上下文和整次运行累计预算共用图片计数规则。累计预算为 524288 Token，包含本次运行多次模型调用的输入和输出；调用前预留输入、工具结构及输出上限，调用完成后用提供方实际 usage 结算。提供方 usage 缺失或调用失败时保守保留预留量，不把 Base64 按文本计费。
- 缺失、较早、超预算图片带有明确的未载入说明，模型不得推测原图；用户需要这些细节时可以重新上传。
- 查询改写等文本辅助调用只看到文字和图片数量提示，不收到图片路径或图片描述。历史摘要也是文字摘要，不能替代原图。

较早会话中的图片可以在页面继续预览；是否作为模型输入另受近期历史和上下文预算限制。当前上传图片无效时明确失败，并保留运行和问题定位信息。

## 配置和验证

Python 的 `.env.example` 已提供 `DEEPSEEK_MODEL=deepseek-flash`。Java 的 Spring AI 对话模型选择为 DeepSeek，保留智谱 Embedding；文章和查询向量化不在本次识图切换范围内。

`python-agent/tests/test_native_multimodal.py` 使用本地生成的测试图片和 HTTP MockTransport，验证真实 SDK 序列化、用户隔离、历史图片、请求大小和 Token 预算，全程不发送真实用户图片或调用付费模型。

可选真实验收使用 `scripts/native-vision-smoke.py`：仅发送脚本临时生成的四色图，同时检查原生图片、流式返回和结构化工具调用，会消耗少量模型额度。结果保存到 `logs/native-vision-live.json`；它是连通性和协议验收，不是识图准确率评测。
