# 人工回答质量评测

当前冻结技术问题集由已有对话改写和边界样例组成，不能称为独立生产留出集。先冻结待测版本、样例与输出；从未参与提示词调优的问题作为留出集单独报告，避免一边看答案改提示词、一边把同一批题算作独立效果。

真实输出采集沿用 `evaluation.delivery_quality collect --mode live`，会消耗模型额度；这次功能改造不自动执行付费采集。已有真实采集目录可以直接生成标注页面：

```sh
# python-agent 目录
python -m evaluation.review_workbench build --directory ../logs/delivery-quality-live --output ../logs/human-review.html
```

在浏览器打开生成的 HTML，逐题查看问题、冻结来源、候选回答与最终回答。页面完全离线，不请求外部服务，来源和模型文本只按纯文本展示。先填写独立判断，再展开自动核验记录，避免直接照抄核验模型意见。填写固定评审人代号；表单不默认通过，也不默认计数为零。

标注任务完成、上下文连贯、候选正确单元/误拦单元、最终具体事实/无依据事实，并记录判断理由。常识、条件性建议、示意代码与教学表格，不因来源没有逐字提及就判错。具体版本、数据、执行状态和来源事实需核对证据。未完成或采集失败样本仍在总分母内，不能只导出成功结果后宣称全量准确率。

页面按输出 Hash 隔离暂存，导入时拒绝未知、重复、过期标签；导出 `reviews.completed.jsonl` 后执行原有评分：

```sh
python -m evaluation.delivery_quality score --directory ../logs/delivery-quality-live --reviews ../logs/reviews.completed.jsonl
```

建议两名评审独立标注同一批问题；分别保存自己的文件，不先共享标签。对比分歧：

```sh
python -m evaluation.review_workbench compare --directory ../logs/delivery-quality-live --first ../logs/reviewer-a.jsonl --second ../logs/reviewer-b.jsonl --output ../logs/disagreements.json
```

分歧报告只列出需要复核的项目，不自动投票生成标签。复核者检查原始材料后保存最终标签。没有完成的人工标签时，人工任务完成率、误拦截率、连贯率和事实支持率仍为空，不能以离线回放或契约通过率代替。
