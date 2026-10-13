from rpc_fakes import public_reader
"""Scoring regressions, not measurements of the production model or retrieval quality."""
import json
import os
os.environ["DEEPSEEK_API_KEY"] = "offline-test"
os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
os.environ["LANGFUSE_PUBLIC_KEY"] = ""
os.environ["LANGFUSE_SECRET_KEY"] = ""
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from evaluation.metrics import percentile, retrieval_metrics, summarize, validate_cases
from evaluation.run import read_jsonl, write_report, Usage, live


class EvaluationTests(unittest.TestCase):
    def cases(self):
        return [{"id": "a", "kind": "rag", "query": "query", "reviewed": True, "relevance": {"1": 3, "2": 1}},
                {"id": "b", "kind": "rag", "query": "query", "reviewed": True, "relevance": {"3": 1}}]

    def record(self, **extra):
        return {"case_id": "a", "variant": "rrf", "repetition": 0, "status": "ok", "latency_ms": 100,
                "ranked_ids": ["9", "1", "2"], **extra}

    def test_retrieval_scoring_deduplicates_articles_before_top_k(self):
        score = retrieval_metrics(["9", "1", "1", "2"], {"1": 3, "2": 1}, 3)
        self.assertEqual(score["hit@3"], 1)
        self.assertEqual(score["recall@3"], 1)
        self.assertEqual(score["mrr@3"], 0.5)
        self.assertAlmostEqual(score["precision@3"], 2 / 3)
        self.assertGreater(score["ndcg@3"], 0)
        self.assertLess(score["ndcg@3"], 1)

    def test_ideal_ranking_and_no_hit(self):
        self.assertEqual(retrieval_metrics(["1", "2"], {"1": 3, "2": 1}, 3)["ndcg@3"], 1)
        self.assertEqual(retrieval_metrics(["9"], {"1": 1}, 5)["mrr@5"], 0)

    def test_missing_trials_reduce_quality_and_success_rate(self):
        report = summarize(self.cases(), [self.record()])["reports"][0]
        self.assertEqual(report["expected_trials"], 2)
        self.assertEqual(report["missing_trials"], 1)
        self.assertEqual(report["request_success_rate"], 0.5)
        self.assertEqual(report["quality"]["hit@5"], 0.5)
        self.assertEqual(report["quality"]["recall@5"], 0.5)
        self.assertEqual(report["quality"]["mrr@5"], 0.25)

    def test_errors_are_not_removed_or_allowed_to_score_stale_rankings(self):
        records = [self.record(), self.record(case_id="b", status="error", ranked_ids=["3"], latency_ms=200)]
        report = summarize(self.cases(), records)["reports"][0]
        self.assertEqual(report["error_trials"], 1)
        self.assertEqual(report["quality"]["hit@5"], 0.5)
        self.assertEqual(report["latency_ms"]["all"]["p50"], 150)
        self.assertEqual(report["latency_ms"]["successful"]["p50"], 100)

    def test_route_target_is_checked_and_multiple_legitimate_actions_are_allowed(self):
        cases = [{"id": "a", "kind": "route", "query": "查历史", "reviewed": True,
                  "acceptable_routes": [{"action": "retrieve", "target": "memory"}]}]
        wrong = self.record(action="retrieve", target="knowledge")
        self.assertEqual(summarize(cases, [wrong])["reports"][0]["quality"]["route_accuracy"], 0)
        correct = self.record(action="retrieve", target="memory")
        self.assertEqual(summarize(cases, [correct])["reports"][0]["quality"]["route_accuracy"], 1)

    def test_unknown_tokens_and_unreviewed_answers_remain_unknown(self):
        report = summarize(self.cases()[:1], [self.record()])["reports"][0]
        self.assertIsNone(report["usage"]["input_tokens"]["total"])
        self.assertIsNone(report["answer_reviews"]["human"]["factual_accuracy"])
        self.assertIsNone(report["answer_reviews"]["human"]["task_success_rate"])
        self.assertEqual(Usage().fields()["input_tokens"], 0)

    def test_human_and_llm_answer_reviews_are_reported_separately(self):
        human = self.record(answer_review={"assessor": "human", "total_claims": 4, "correct_claims": 3,
                                          "supported_claims": 2, "task_success": True})
        judge = self.record(case_id="b", answer_review={"assessor": "llm", "total_claims": 2,
                                                        "correct_claims": 2, "supported_claims": 2, "task_success": False})
        report = summarize(self.cases(), [human, judge])["reports"][0]
        self.assertEqual(report["answer_reviews"]["human"]["factual_accuracy"], 0.75)
        self.assertEqual(report["answer_reviews"]["human"]["evidence_support_rate"], 0.5)
        self.assertEqual(report["answer_reviews"]["llm"]["task_success_rate"], 0)

    def test_duplicate_unknown_and_invalid_measurements_are_rejected(self):
        for records in ([self.record(), self.record()], [self.record(case_id="unknown")],
                        [self.record(latency_ms=float("nan"))], [self.record(repetition=2)],
                        [self.record(llm_calls=-1)], [self.record(answer_review={"assessor": "human", "total_claims": 1, "correct_claims": 2})]):
            with self.subTest(records=records), self.assertRaises(ValueError):
                summarize(self.cases(), records)

    def test_templates_are_valid_but_unlabelled_rag_is_not_a_benchmark(self):
        base = Path(__file__).resolve().parents[1] / "evaluation" / "datasets"
        routes, rag = read_jsonl(base / "route.jsonl"), read_jsonl(base / "rag.template.jsonl")
        validate_cases(routes + rag)
        self.assertEqual(len(routes), 16)
        self.assertTrue(all(case["reviewed"] is False for case in rag))
        with self.assertRaises(ValueError):
            validate_cases([{**rag[0], "reviewed": True}])

    def test_percentiles_and_report_export(self):
        self.assertIsNone(percentile([], 95))
        self.assertEqual(percentile([100], 95), 100)
        self.assertAlmostEqual(percentile([100, 200], 95), 195)
        with tempfile.TemporaryDirectory() as directory:
            write_report(directory, self.cases(), [self.record()], 1,
                         {"mode": "offline_scorer_fixture", "dataset_sha256": "fixture"})
            report = json.loads((Path(directory) / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(report["reports"][0]["missing_trials"], 1)
            self.assertIn("不等于任务完成率", (Path(directory) / "report.md").read_text(encoding="utf-8"))


class EvaluationRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_rag_ablation_reuses_production_clients_and_does_not_generate_an_answer(self):
        from app.clients.es_client import EsVectorStore, EsChunkSearch
        from app.services.retrieval_service import RetrievalService
        from app.services.reranker import RerankerService
        from app.services.query_rewrite import ResolvedFilters
        from app.graph.nodes import search_worker
        from app.config import settings
        from fakes import article_chunk
        import app.clients.mysql_client as mysql
        cases = [{"id": "rag", "kind": "rag", "query": "RAG", "reviewed": True, "relevance": {"42": 3}}]
        docs = [article_chunk(aid="42"), article_chunk(aid="99")]
        hits = [{"_source": {**doc, "chunk_content": doc["content"]}, "_score": 0.9 - i / 10} for i, doc in enumerate(docs)]
        async def es_search(**kwargs):
            return {"hits": {"hits": hits if "knn" in kwargs else list(reversed(hits))}}
        es = SimpleNamespace(search=AsyncMock(side_effect=es_search), close=AsyncMock())
        vector = EsVectorStore.__new__(EsVectorStore)
        vector.client, vector.embedding_service = es, SimpleNamespace(aembed=AsyncMock(return_value=[0.1]))
        keyword = EsChunkSearch.__new__(EsChunkSearch)
        keyword.client = es
        retrieval = RetrievalService.__new__(RetrievalService)
        retrieval._vector_store, retrieval._chunk_search = vector, keyword
        ranker = RerankerService.__new__(RerankerService)
        ranker.client = SimpleNamespace(post=AsyncMock(return_value=SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: {"output": {"results": [{"index": 0, "relevance_score": 0.9}]}})), aclose=AsyncMock())
        database = SimpleNamespace(connect=AsyncMock(), disconnect=AsyncMock(), fetch_all=AsyncMock(return_value=[
            SimpleNamespace(_mapping={"article_id": int(doc["article_id"]), "title": "RAG", "content": "<p>current public evidence</p>"}) for doc in docs]))
        rewrite = SimpleNamespace(llm=None, rewrite=AsyncMock())
        model = SimpleNamespace(model_name="offline-fixture", root_async_client=None, ainvoke=AsyncMock())
        args = SimpleNamespace(command="live-rag", variants=["bm25", "knn", "rrf", "rrf_rerank"],
                               seed=42, timeout=1, warmup=0, repeats=1, rewrite=False)
        results = []
        with patch("app.config.get_llm", return_value=model), patch.object(settings, "ZHIPUAI_API_KEY", "offline"), \
             patch.object(mysql, "db", database), patch.object(search_worker, "public_read", public_reader(database)), \
             patch("app.services.query_rewrite.QueryRewriteService", return_value=rewrite), \
             patch("app.services.filter_resolver.FilterResolver", return_value=SimpleNamespace(resolve=AsyncMock(return_value=ResolvedFilters()))), \
             patch("app.services.retrieval_service.RetrievalService", side_effect=lambda: retrieval), \
             patch("app.services.reranker.RerankerService", return_value=ranker):
            # Keep normalization on the real class when its constructor is substituted.
            with patch.object(search_worker, "retrieval_service", SimpleNamespace(RetrievalService=RetrievalService)):
                await live(args, cases, results.append, {})
        rewrite.rewrite.assert_not_awaited()
        model.ainvoke.assert_not_awaited()
        self.assertEqual(len(results), 4)
        self.assertTrue(all(item["status"] == "ok" for item in results))
        by_variant = {item["variant"]: item for item in results}
        self.assertEqual(by_variant["bm25"]["embedding_calls"], 0)
        self.assertEqual(by_variant["knn"]["embedding_calls"], 1)
        self.assertEqual(by_variant["rrf_rerank"]["rerank_calls"], 1)
        self.assertEqual(by_variant["bm25"]["ranked_ids"], ["99", "42"])
        self.assertEqual(by_variant["rrf_rerank"]["ranked_ids"], ["42"])
        database.connect.assert_awaited_once()
        database.disconnect.assert_awaited_once()

    async def test_first_decision_measurement_counts_calls_and_parse_failures_without_execution(self):
        from app.graph.main_agent import MainDecision
        from app.services.memory_policy import memory_policy_service
        cases = [{"id": "route", "kind": "route", "query": "你好", "reviewed": True,
                  "acceptable_routes": [{"action": "answer"}]}]
        raw = SimpleNamespace(usage_metadata={"input_tokens": 100, "output_tokens": 10})
        structured = SimpleNamespace(ainvoke=AsyncMock(side_effect=[
            {"raw": raw, "parsed": MainDecision(action="answer", reply="你好"), "parsing_error": None},
            {"raw": raw, "parsed": None, "parsing_error": ValueError()}]))
        model = SimpleNamespace(model_name="offline-fixture", with_structured_output=Mock(return_value=structured), root_async_client=None)
        args = SimpleNamespace(command="live-route", seed=42, timeout=1, warmup=0, repeats=2)
        results = []
        with patch("app.config.get_llm", return_value=model), \
             patch.object(memory_policy_service, "apply_changes", AsyncMock()) as writes:
            await live(args, cases, results.append, {})
        writes.assert_not_awaited()
        self.assertEqual([item["status"] for item in results], ["ok", "error"])
        self.assertTrue(all(item["llm_calls"] == 1 for item in results))
        self.assertEqual(results[0]["input_tokens"], 100)
        self.assertEqual(results[0]["reply"], "你好")
        self.assertEqual(results[0]["decision"]["action"], "answer")
        report = summarize(cases, results, repeats=2)["reports"][0]
        self.assertEqual(report["quality"]["route_accuracy"], 0.5)
        self.assertEqual(report["error_trials"], 1)
