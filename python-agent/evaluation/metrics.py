"""Deterministic scoring of human-labelled cases and recorded measurements."""
import math
from statistics import mean


def percentile(values, percentile_value):
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * percentile_value / 100
    low, high = math.floor(position), math.ceil(position)
    return values[low] + (values[high] - values[low]) * (position - low)


def retrieval_metrics(ranked_ids, relevance, k):
    """Deduplicate before applying K. Binary recall; graded nDCG with 2**grade-1 gain."""
    ranking = list(dict.fromkeys(ranked_ids))[:k]
    positive = {key for key, grade in relevance.items() if grade > 0}
    if not positive:
        raise ValueError("检索样本至少需要一个人工标注的相关文档")
    hits = [key in positive for key in ranking]
    dcg = sum((2 ** relevance.get(key, 0) - 1) / math.log2(i + 2) for i, key in enumerate(ranking))
    ideal = sorted(relevance.values(), reverse=True)[:k]
    idcg = sum((2 ** grade - 1) / math.log2(i + 2) for i, grade in enumerate(ideal))
    return {f"hit@{k}": float(any(hits)), f"recall@{k}": sum(hits) / len(positive),
            f"precision@{k}": sum(hits) / k,
            f"mrr@{k}": next((1 / (i + 1) for i, hit in enumerate(hits) if hit), 0.0),
            f"ndcg@{k}": dcg / idcg if idcg else 0.0}


def validate_cases(cases):
    ids = set()
    for case in cases:
        cid = case.get("id")
        if not isinstance(cid, str) or not cid or cid in ids:
            raise ValueError("样本 id 必须为唯一非空字符串")
        ids.add(cid)
        if not isinstance(case.get("reviewed", False), bool):
            raise ValueError(f"{cid}: reviewed 必须是布尔值")
        if not isinstance(case.get("requires_behavior_review", False), bool):
            raise ValueError(f"{cid}: requires_behavior_review 必须是布尔值")
        if case.get("kind") not in ("rag", "route") or not str(case.get("query", "")).strip():
            raise ValueError(f"{cid}: 必须提供 kind=rag/route 和 query")
        relevance = case.get("relevance", {})
        if not isinstance(relevance, dict) or any(not isinstance(key, str) or not isinstance(grade, int)
                or isinstance(grade, bool) or grade < 0 or grade > 3 for key, grade in relevance.items()):
            raise ValueError(f"{cid}: relevance 应为文档ID到0–3相关性等级的字典")
        if case.get("reviewed"):
            if case["kind"] == "rag" and not any(relevance.values()):
                raise ValueError(f"{cid}: 人工确认的检索样本缺少相关文档标注")
            if case["kind"] == "route" and not case.get("acceptable_routes"):
                raise ValueError(f"{cid}: 路由样本缺少 acceptable_routes")
            for route in case.get("acceptable_routes", []):
                if not isinstance(route, dict) or set(route) - {"action", "target", "allow_web"}:
                    raise ValueError(f"{cid}: 非法路由标签字段")
                if route.get("action") not in ("answer", "retrieve", "delegate", "write_draft"):
                    raise ValueError(f"{cid}: 非法期望动作")
                if "target" in route and (route["action"] != "retrieve" or route["target"] not in ("knowledge", "memory")):
                    raise ValueError(f"{cid}: 非法检索目标")
                if "allow_web" in route and (route["action"] != "retrieve" or not isinstance(route["allow_web"], bool)
                        or (route.get("target") == "memory" and route["allow_web"])):
                    raise ValueError(f"{cid}: 非法联网许可标签")


def route_matches(case, prediction):
    return prediction.get("status") == "ok" and any(
        all(prediction.get(key) == value for key, value in route.items())
        for route in case["acceptable_routes"])


def summarize(cases, predictions, repeats=1, ks=(1, 3, 5)):
    """Missing/error measurements score zero, rather than disappearing from the denominator."""
    validate_cases(cases)
    if repeats < 1 or any(not isinstance(k, int) or isinstance(k, bool) or k < 1 for k in ks):
        raise ValueError("repeats 与 K 必须为正数")
    by_id = {case["id"]: case for case in cases}
    records, variants = {}, set()
    for prediction in predictions:
        cid, variant, repetition = prediction.get("case_id"), prediction.get("variant"), prediction.get("repetition")
        if cid not in by_id or not isinstance(variant, str) or not variant or not isinstance(repetition, int) or isinstance(repetition, bool) or not 0 <= repetition < repeats:
            raise ValueError("记录的样本、variant 或 repetition 无效")
        if prediction.get("status") not in ("ok", "error"):
            raise ValueError("status 必须为 ok/error")
        if prediction.get("kind", by_id[cid]["kind"]) != by_id[cid]["kind"]:
            raise ValueError("记录类型与样本类型不一致")
        key = (cid, variant, repetition)
        if key in records:
            raise ValueError("同一 variant 的样本重复记录，不能重复计分")
        latency = prediction.get("latency_ms")
        if not isinstance(latency, (int, float)) or isinstance(latency, bool) or not math.isfinite(latency) or latency < 0:
            raise ValueError("latency_ms 必须是非负有限数")
        if not isinstance(prediction.get("ranked_ids", []), list) or any(not isinstance(v, str) for v in prediction.get("ranked_ids", [])):
            raise ValueError("ranked_ids 必须为字符串列表")
        for name in ("llm_calls", "embedding_calls", "rerank_calls", "input_tokens", "output_tokens"):
            value = prediction.get(name)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                raise ValueError(f"{name} 必须为非负整数或 null")
        review = prediction.get("answer_review")
        if review is not None:
            if not isinstance(review, dict):
                raise ValueError("answer_review 必须是字典或 null")
            if review.get("assessor") not in ("human", "llm"):
                raise ValueError("回答评审必须注明 human/llm，不能混用成客观准确率")
            total = review.get("total_claims", 0)
            if not isinstance(total, int) or isinstance(total, bool) or total < 0:
                raise ValueError("total_claims 必须为非负整数")
            for name in ("total_claims", "correct_claims", "supported_claims"):
                value = review.get(name, 0)
                if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= total:
                    raise ValueError("回答评审的事实计数不合法")
            if "task_success" in review and not isinstance(review["task_success"], bool):
                raise ValueError("task_success 必须是布尔值")
        behavior = prediction.get("behavior_review")
        if behavior is not None and (not isinstance(behavior, dict) or behavior.get("assessor") not in ("human", "llm")
                or not isinstance(behavior.get("passed"), bool)):
            raise ValueError("behavior_review 必须明确 human/llm 与布尔 passed")
        records[key] = prediction
        variants.add((variant, by_id[cid]["kind"]))
    reports = []
    for variant, kind in sorted(variants):
        eligible = [case for case in cases if case["kind"] == kind and case.get("reviewed") is True]
        expected = [(case, repetition) for case in eligible for repetition in range(repeats)]
        measured = [records[(case["id"], variant, repetition)] for case, repetition in expected
                    if (case["id"], variant, repetition) in records]
        successful = [item for item in measured if item["status"] == "ok"]
        quality = []
        for case, repetition in expected:
            item = records.get((case["id"], variant, repetition), {})
            ok = item.get("status") == "ok"
            if kind == "rag":
                metrics = {}
                for k in ks:
                    metrics.update(retrieval_metrics(item.get("ranked_ids", []) if ok else [], case["relevance"], k))
            else:
                metrics = {"route_accuracy": float(route_matches(case, item))}
            quality.append(metrics)
        latencies = [item["latency_ms"] for item in measured]
        success_latencies = [item["latency_ms"] for item in successful]
        report = {"variant": variant, "kind": kind, "labelled_cases": len(eligible), "expected_trials": len(expected),
                  "recorded_trials": len(measured), "missing_trials": len(expected) - len(measured),
                  "error_trials": len(measured) - len(successful),
                  "rewrite_degraded_trials": sum(bool(item.get("rewrite_degraded")) for item in measured),
                  "rerank_degraded_trials": sum(bool(item.get("rerank_degraded")) for item in measured),
                  "request_success_rate": len(successful) / len(expected) if expected else None,
                  "quality": {key: mean(item[key] for item in quality) for key in quality[0]} if quality else {},
                  "latency_ms": {"all": _latency(latencies), "successful": _latency(success_latencies)},
                  "usage": {name: _usage(measured, name) for name in
                      ("llm_calls", "embedding_calls", "rerank_calls", "input_tokens", "output_tokens")},
                  "answer_reviews": {assessor: _review(measured, assessor) for assessor in ("human", "llm")}}
        if kind == "route":
            report["categories"] = []
            for category in sorted({case.get("category", "uncategorized") for case in eligible}):
                subset = [(case, repetition) for case, repetition in expected if case.get("category", "uncategorized") == category]
                count = sum(route_matches(case, records.get((case["id"], variant, repetition), {})) for case, repetition in subset)
                report["categories"].append({"category": category, "labelled_cases": len(subset) // repeats,
                    "expected_trials": len(subset), "correct_trials": count, "route_accuracy": count / len(subset)})
            report["mismatches"] = [{"case_id": case["id"], "query": case["query"], "category": case.get("category", "uncategorized"),
                "repetition": repetition, "expected": case["acceptable_routes"],
                "actual": {name: records.get((case["id"], variant, repetition), {}).get(name)
                    for name in ("status", "action", "target", "allow_web", "error_type")}}
                for case, repetition in expected if not route_matches(case, records.get((case["id"], variant, repetition), {}))]
            required = [(case, repetition) for case, repetition in expected if case.get("requires_behavior_review")]
            report["behavior_reviews"] = {}
            for assessor in ("human", "llm"):
                reviews = [item["behavior_review"] for case, repetition in required
                    if (item := records.get((case["id"], variant, repetition), {})).get("status") == "ok"
                    and (item.get("behavior_review") or {}).get("assessor") == assessor]
                report["behavior_reviews"][assessor] = {"required_trials": len(required), "reviewed_trials": len(reviews),
                    "pending_trials": len(required) - len(reviews),
                    "pass_rate_reviewed_only": sum(review["passed"] for review in reviews) / len(reviews) if reviews else None}
        reports.append(report)
    return {"repeats": repeats, "ks": list(ks), "unreviewed_cases": sum(case.get("reviewed") is not True for case in cases),
            "reports": reports,
            "notes": ["路由准确率仅衡量首轮动作/检索目标及已标注的 allow_web，不等于任务完成率。",
                      "安全拒答、澄清质量与上下文遵循需要独立语义复核；选择 answer 不能自动判定安全，未复核不报告通过率。",
                      "检索相关性需冻结标签并注明来源；合成标签不能当作独立人工标注。未标注样本不计分，失败与缺失记录按零分计入。",
                      "P50/P95为线性插值样本分位数，失败耗时与成功耗时分别报告；不是首Token耗时。",
                      "回答正确性/证据支持率/任务完成率仅对有独立评审的记录计算，human与llm分开报告。"]}


def _latency(values):
    return {"n": len(values), "mean": mean(values) if values else None,
            "p50": percentile(values, 50), "p95": percentile(values, 95)}


def _usage(records, name):
    known = [item[name] for item in records if item.get(name) is not None]
    return {"known_trials": len(known), "total": sum(known) if known else None, "mean": mean(known) if known else None}


def _review(records, assessor):
    reviews = [item["answer_review"] for item in records if (item.get("answer_review") or {}).get("assessor") == assessor]
    total = sum(item.get("total_claims", 0) for item in reviews)
    outcomes = [item["task_success"] for item in reviews if "task_success" in item]
    return {"reviewed_trials": len(reviews), "total_claims": total,
            "factual_accuracy": sum(item.get("correct_claims", 0) for item in reviews) / total if total else None,
            "evidence_support_rate": sum(item.get("supported_claims", 0) for item in reviews) / total if total else None,
            "task_success_rate": sum(outcomes) / len(outcomes) if outcomes else None}
