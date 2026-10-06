"""python -m evaluation.run score|live-route|live-rag. Live modes are explicit and read-only."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
import random
import time

from evaluation.metrics import summarize, validate_cases


def read_jsonl(path):
    with Path(path).open(encoding="utf-8-sig") as file:
        return [json.loads(line) for line in file if line.strip()]


def write_report(output, cases, predictions, repeats, manifest):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    result = summarize(cases, predictions, repeats)
    result["manifest"] = manifest
    (output / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 评测结果", "", f"模式：{manifest['mode']}；样本文件 SHA256：`{manifest['dataset_sha256']}`", "",
             "| Variant | 标注问题数 | 请求成功/预期次数 | Hit@5 / 路由准确率 | Recall@5 | MRR@5 | 成功耗时 P50/P95(ms) | 平均 LLM 调用 |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    def display(value):
        return "—" if value is None else f"{value:.4f}"
    for report in result["reports"]:
        quality = report["quality"]
        latency = report["latency_ms"]["successful"]
        success = report["recorded_trials"] - report["error_trials"]
        lines.append(f"| {report['variant']} | {report['labelled_cases']} | {success}/{report['expected_trials']} | "
                     f"{display(quality.get('hit@5', quality.get('route_accuracy')))} | {display(quality.get('recall@5'))} | "
                     f"{display(quality.get('mrr@5'))} | {display(latency['p50'])}/{display(latency['p95'])} | "
                     f"{display(report['usage']['llm_calls']['mean'])} |")
    if 'synthetic_authored' in manifest.get('annotation_sources', []):
        lines += ["", "本次使用合成文章与模型编写的相关性标签，属于受控样例评测；不代表真实用户查询或独立人工标注效果。"]
    for report in result["reports"]:
        if report["kind"] != "route":
            continue
        lines += ["", "首轮路由分类：", "", "| 类别 | 不同问题 | 正确/预期试验 | 路由准确率 |", "|---|---:|---:|---:|"]
        for category in report["categories"]:
            lines.append(f"| {category['category']} | {category['labelled_cases']} | {category['correct_trials']}/{category['expected_trials']} | {category['route_accuracy']:.2%} |")
        for assessor, review in report["behavior_reviews"].items():
            lines += ["", f"语义复核（{assessor}）：需复核 {review['required_trials']} 次，已复核 {review['reviewed_trials']} 次，待复核 {review['pending_trials']} 次。"]
        if report["mismatches"]:
            lines += ["", "路由不匹配：", ""]
            for item in report["mismatches"]:
                lines.append(f"- {item['case_id']} 第 {item['repetition'] + 1} 次：{item['query']}；期望 `{json.dumps(item['expected'], ensure_ascii=False)}`；实际 `{json.dumps(item['actual'], ensure_ascii=False)}`")
    if 'product_rules' in manifest.get('annotation_sources', []):
        lines += ["", "路由样例按产品规则预先编写并冻结，不是真实用户独立留出集；复杂题允许多个合法首轮动作。"]
    reviews = [{"case_id": item["case_id"], "variant": item["variant"], "repetition": item["repetition"],
        "query": case["query"], "category": case.get("category"), "expected_behavior": case.get("expected_behavior"),
        "status": item["status"], "reply": item.get("reply"), "decision": item.get("decision"),
        "behavior_review": item.get("behavior_review")}
        for item in predictions if (case := next(case for case in cases if case["id"] == item["case_id"])).get("requires_behavior_review")]
    if reviews:
        (output / "behavior-review.jsonl").write_text(''.join(json.dumps(item, ensure_ascii=False) + '\n' for item in reviews), encoding="utf-8")
    lines += ["", "指标说明：", ""] + [f"- {note}" for note in result["notes"]]
    lines += ["- 未执行的真实测试不会由单元测试或模拟响应填充；未获取到的 Token 用量记为 null。",
              "- 原始记录保留错误类型、降级状态、调用计数与耗时。重复试验不是独立问题数量。",
              "- live-route 只测首次结构化决策；live-rag 只测平台检索流水线，不包含答案生成、联网与前端传输。"]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def manifest_for(args):
    root = Path(__file__).resolve().parents[1]
    tracked = ["app/graph/main_agent.py", "app/services/retrieval_service.py", "app/services/reranker.py",
               "app/graph/nodes/search_worker.py", "evaluation/metrics.py", "evaluation/run.py"]
    versions = {}
    for name in ("langchain-core", "langchain-openai", "langgraph", "elasticsearch"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return {"mode": args.command, "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "dataset_sha256": hashlib.sha256(Path(args.cases).read_bytes()).hexdigest(), "repeats": args.repeats,
            "warmup_per_variant": getattr(args, "warmup", 0), "seed": getattr(args, "seed", None),
            "versions": versions, "source_hashes": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in tracked}}


class Usage:
    def __init__(self):
        self.llm_calls = self.embedding_calls = self.rerank_calls = 0
        self.input_tokens = self.output_tokens = 0
        self.usage_samples = 0

    def capture(self, raw):
        usage = getattr(raw, "usage_metadata", None)
        if usage and "input_tokens" in usage and "output_tokens" in usage:
            self.input_tokens += usage["input_tokens"]
            self.output_tokens += usage["output_tokens"]
            self.usage_samples += 1

    def fields(self):
        complete = self.llm_calls > 0 and self.usage_samples == self.llm_calls
        return {"llm_calls": self.llm_calls, "embedding_calls": self.embedding_calls, "rerank_calls": self.rerank_calls,
                "input_tokens": self.input_tokens if complete or not self.llm_calls else None,
                "output_tokens": self.output_tokens if complete or not self.llm_calls else None}


class CountedModel:
    def __init__(self, model, usage):
        self.model, self.usage = model, usage

    async def ainvoke(self, *args, **kwargs):
        self.usage.llm_calls += 1
        result = await self.model.ainvoke(*args, **kwargs)
        self.usage.capture(result)
        return result


async def live(args, cases, record, manifest):
    # No approval/save/memory-write path is invoked by either benchmark.
    from app.config import get_llm, settings
    if not settings.DEEPSEEK_API_KEY:
        raise ValueError("未配置 DEEPSEEK_API_KEY；可先运行 score 和离线测试")
    model = get_llm(temperature=0, max_retries=0, max_tokens=settings.MAIN_OUTPUT_MAX_TOKENS)
    manifest.update(model=model.model_name, sdk_retries=0, whole_sample_timeout_seconds=args.timeout,
                    latency_scope="first_main_decision" if args.command == "live-route" else
                        "rewrite_resolve_retrieve_verify_rerank" if args.rewrite else "resolve_retrieve_verify_rerank")
    variants = ["main_decision"] if args.command == "live-route" else args.variants
    prepared = None
    if args.command == "live-route":
        from app.graph.main_agent import MainDecision, build_main_messages, main_message_renderer
        from app.services.main_context import prepare_context
        from app.utils.context_budget import ensure_request_budget
        from types import SimpleNamespace
        from app.graph.state_factory import create_initial_state
        prepared = model.with_structured_output(MainDecision, method="function_calling", include_raw=True)
        manifest.update(context_max_tokens=settings.MAIN_CONTEXT_MAX_TOKENS,
                        output_max_tokens=settings.MAIN_OUTPUT_MAX_TOKENS,
                        context_safety_tokens=settings.CONTEXT_SAFETY_TOKENS,
                        compact_trigger_tokens=settings.CONTEXT_COMPACT_TRIGGER_TOKENS,
                        compact_target_tokens=settings.CONTEXT_COMPACT_TARGET_TOKENS,
                        compact_min_saving_tokens=settings.CONTEXT_COMPACT_MIN_SAVING_TOKENS,
                        auxiliary_history_max_tokens=settings.AUXILIARY_HISTORY_MAX_TOKENS,
                        history_recent_tokens=settings.HISTORY_RECENT_TOKENS,
                        summary_max_tokens=settings.SUMMARY_MAX_TOKENS,
                        context_max_chars=settings.MAIN_CONTEXT_MAX_CHARS,
                        output_max_chars=settings.MAIN_OUTPUT_MAX_CHARS,
                        task_result_max_chars=settings.TASK_RESULT_MAX_CHARS,
                        dependency_max_chars=settings.DEPENDENCY_MAX_CHARS,
                        token_estimator="cl100k_base_with_request_overhead")

        async def execute(case, variant, usage):
            state = create_initial_state(1, case["query"], case.get("history", []))
            state.update(user_profile=case.get("user_profile", {}), active_constraints=case.get("active_constraints", []))
            state, _ = await prepare_context(state, main_message_renderer(state), [MainDecision])
            compaction = state.get('context_compaction', {})
            usage.llm_calls += compaction.get('summary_calls', 0)
            for metadata in compaction.get('summary_usage', []):
                usage.capture(SimpleNamespace(usage_metadata=metadata))
            ensure_request_budget(main_message_renderer(state)(state['history_messages']), [MainDecision])
            messages = build_main_messages(state)
            usage.llm_calls += 1
            response = await prepared.ainvoke(messages)
            usage.capture(response.get("raw"))
            if response.get("parsing_error") or response.get("parsed") is None:
                raise ValueError("结构化决策解析失败")
            decision = response["parsed"]
            return {"action": decision.action, "target": decision.retrieval.target if decision.retrieval else None,
                    "allow_web": decision.retrieval.allow_web if decision.retrieval else None,
                    "reply": decision.reply, "decision": decision.model_dump(mode="json")}
    else:
        if not settings.ZHIPUAI_API_KEY:
            raise ValueError("未配置 ZHIPUAI_API_KEY；KNN 基线需要真实 Embedding")
        from app.clients.mysql_client import db
        from app.graph.nodes import search_worker
        from app.services.query_rewrite import QueryRewriteService, QueryFilters
        from app.services.filter_resolver import FilterResolver
        from app.services.retrieval_service import RetrievalService
        from app.services.reranker import RerankerService
        await db.connect()
        rewrite, resolver = QueryRewriteService(), FilterResolver()
        retriever, ranker = RetrievalService(), RerankerService()
        coarse_k = settings.COARSE_TOP_K
        manifest.update(coarse_k=coarse_k, rerank_k=settings.RERANK_TOP_K, identity="article_id",
                        max_chunks_per_article=ranker.MAX_CHUNKS_PER_ARTICLE, web_search=False,
                        embedding_model=settings.ZHIPU_EMBEDDING_MODEL, embedding_dimensions=settings.ZHIPU_EMBEDDING_DIMENSIONS,
                        rerank_model=ranker.MODEL, concurrency=1, platform=platform.platform(),
                        query_rewrite=args.rewrite,
                        comparison="same versioned corpus; original query by default; not an old-release baseline")
        manifest.update(public_articles=None, indexed_current_version_chunks=None)
        try:
            from app.clients.es_client import ARTICLE_CHUNK_VERSION
            corpus_filter = {"term": {"chunker_version": ARTICLE_CHUNK_VERSION}}
            authors = {case.get("filters", {}).get("author_name") for case in cases}
            if len(authors) == 1 and None not in authors:
                scope = await resolver.resolve(QueryFilters(author_name=next(iter(authors))))
                if len(scope.author_ids) != 1:
                    raise ValueError("评测作者必须唯一命中，不能降级成全库检索")
                manifest["corpus_author_ids"] = scope.author_ids
                corpus_filter = {"bool": {"filter": [corpus_filter, {"terms": {"user_id": scope.author_ids}}]}}
                count_row = await db.fetch_one("SELECT COUNT(*) AS total FROM article_info WHERE status=1 AND deleted=0 AND user_id=:uid",
                                               {"uid": scope.author_ids[0]})
            else:
                count_row = await db.fetch_one("SELECT COUNT(*) AS total FROM article_info WHERE status=1 AND deleted=0")
            manifest["indexed_current_version_chunks"] = (await retriever._vector_store.client.count(
                index=retriever._vector_store.INDEX, query=corpus_filter))["count"]
            manifest["public_articles"] = int(count_row._mapping["total"])
        except ValueError:
            raise
        except Exception as error:
            manifest["corpus_count_error_type"] = type(error).__name__
        original_embedding = retriever._vector_store.embedding_service.aembed
        original_post = ranker.client.post

        async def execute(case, variant, usage):
            rewrite.llm = CountedModel(model, usage)
            async def embed(text):
                usage.embedding_calls += 1
                return await original_embedding(text)
            async def rerank_post(*args, **kwargs):
                usage.rerank_calls += 1
                return await original_post(*args, **kwargs)
            retriever._vector_store.embedding_service.aembed = embed
            ranker.client.post = rerank_post
            query = await rewrite.rewrite(case["query"], case.get("history", [])) if args.rewrite else {
                "semantic_queries": [case["query"]], "keywords": [case["query"]], "filters": QueryFilters(**case.get("filters", {}))}
            query["filters"] = QueryFilters(**{**query["filters"].model_dump(), **case.get("filters", {})})
            filters = await resolver.resolve(query["filters"])
            if manifest.get("corpus_author_ids") and filters.author_ids != manifest["corpus_author_ids"]:
                raise ValueError("执行过滤条件偏离冻结评测语料")
            if variant == "knn":
                filters = filters.model_copy(update={"soft_terms": []})
            candidates = await retriever.hybrid_search(
                query["semantic_queries"] if variant != "bm25" else [],
                query["keywords"] if variant != "knn" else [], filters, search_mode="platform", top_k=coarse_k)
            verified = await search_worker._verify_candidates_from_mysql(candidates)
            ranked = await ranker.rerank(case["query"], verified) if variant == "rrf_rerank" else verified
            return {"ranked_ids": list(dict.fromkeys(str(item["article_id"]) for item in ranked)),
                    "chunk_ids": [item["chunk_id"] for item in ranked], "verified_chunks": len(verified),
                    "semantic_queries": query["semantic_queries"], "keywords": query["keywords"], "resolved_filters": filters.model_dump(),
                    "rewrite_degraded": query.get("status") == "degraded",
                    "rerank_degraded": any(item.get("rerank_status") == "degraded" for item in ranked)}
    try:
        rng = random.Random(args.seed)
        for variant in variants:
            for _ in range(args.warmup):
                # Warmups are not measurements; failure aborts, avoiding a false healthy preflight.
                await asyncio.wait_for(execute(cases[0], variant, Usage()), args.timeout)
        schedule = [(case, variant, repetition) for repetition in range(args.repeats) for case in cases for variant in variants]
        rng.shuffle(schedule)
        for case, variant, repetition in schedule:
            usage = Usage()
            started = time.perf_counter()
            try:
                output = await asyncio.wait_for(execute(case, variant, usage), args.timeout)
                result = {"status": "ok", **output}
            except Exception as error:
                # Preserve failures in the denominator without exposing credentials or URLs from exception messages.
                result = {"status": "error", "error_type": type(error).__name__}
            result.update(case_id=case["id"], kind=case["kind"], variant=variant, repetition=repetition,
                          latency_ms=(time.perf_counter() - started) * 1000, **usage.fields())
            record(result)
            print(f"{case['id']} {variant} #{repetition + 1}: {result['status']}, {result['latency_ms']:.0f} ms")
    finally:
        # Importing Main's module instantiates the production retrieval clients; close them too.
        from app.graph.nodes import search_worker
        clients = [search_worker.retrieval_service_instance._vector_store.client,
                   search_worker.retrieval_service_instance._chunk_search.client,
                   search_worker.reranker_service.client]
        if args.command == "live-rag":
            clients += [retriever._vector_store.client, retriever._chunk_search.client, ranker.client]
        for client in clients:
            closer = getattr(client, "aclose", None) or getattr(client, "close", None)
            if closer:
                await closer()
        if args.command == "live-rag":
            await db.disconnect()
        if getattr(model, "root_async_client", None):
            await model.root_async_client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("score", "live-route", "live-rag"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--cases", required=True)
        sub.add_argument("--output", required=True)
        sub.add_argument("--repeats", type=int, default=1)
        if command == "score":
            sub.add_argument("--predictions", required=True)
        else:
            sub.add_argument("--warmup", type=int, default=1)
            sub.add_argument("--seed", type=int, default=42)
            sub.add_argument("--timeout", type=float, default=180)
            if command == "live-rag":
                sub.add_argument("--variants", nargs="+", choices=("bm25", "knn", "rrf", "rrf_rerank"),
                                 default=["bm25", "knn", "rrf", "rrf_rerank"])
                sub.add_argument("--rewrite", action="store_true", help="同时测查询改写；默认用相同原始查询做受控召回对照")
    args = parser.parse_args()
    if args.repeats < 1 or getattr(args, "warmup", 0) < 0 or getattr(args, "timeout", 1) <= 0:
        parser.error("次数和 timeout 无效")
    cases = read_jsonl(args.cases)
    validate_cases(cases)
    manifest = manifest_for(args)
    manifest["annotation_sources"] = sorted({case.get("annotation_source", "human" if case["kind"] == "rag" else "product_rules") for case in cases})
    if args.command == "score":
        predictions = read_jsonl(args.predictions)
        manifest["predictions_sha256"] = hashlib.sha256(Path(args.predictions).read_bytes()).hexdigest()
        original = Path(args.predictions).parent / "summary.json"
        if original.exists():
            manifest["measurement_manifest"] = json.loads(original.read_text(encoding="utf-8")).get("manifest")
    else:
        kind = "route" if args.command == "live-route" else "rag"
        cases = [case for case in cases if case["kind"] == kind and case.get("reviewed") is True]
        if not cases:
            parser.error("没有人工确认的样本；先标注 relevance/acceptable_routes 并设置 reviewed=true")
        if len(set(getattr(args, "variants", []))) != len(getattr(args, "variants", [])):
            parser.error("variant 不能重复")
        output = Path(args.output)
        output.mkdir(parents=True, exist_ok=True)
        prediction_path = output / "predictions.jsonl"
        if prediction_path.exists():
            parser.error("输出目录已有 predictions.jsonl，请使用新的目录避免覆盖原始实验")
        predictions = []
        with prediction_path.open("w", encoding="utf-8") as file:
            def record(item):
                predictions.append(item)
                file.write(json.dumps(item, ensure_ascii=False) + "\n")
                file.flush()
            try:
                asyncio.run(live(args, cases, record, manifest))
            finally:
                write_report(output, cases, predictions, args.repeats, manifest)
    report = write_report(args.output, cases, predictions, args.repeats, manifest)
    print(f"报告已保存：{Path(args.output) / 'report.md'}；{len(report['reports'])} 个 variant 报告")


if __name__ == "__main__":
    main()
