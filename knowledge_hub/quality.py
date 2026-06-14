LOW_QUALITY_SIGNALS = [
    "测试",
    "占位",
    "示例",
    "TODO",
    "待补充",
    "暂无",
    "待定",
    "暂无内容",
    "示例数据",
    "test",
    "示例文本",
    "placeholder",
]


def auto_evaluate_quality(item: dict) -> float:
    """
    Evaluate knowledge quality from 0 to 100.

    The hub owns this score and does not trust node-submitted quality values.
    """
    return evaluate_quality_detail(item)["score"]


def evaluate_quality_detail(item: dict) -> dict:
    """Evaluate quality and return score, review status, and explainable reasons."""
    title = item.get("title", "") or ""
    summary = item.get("summary", "") or ""
    url = item.get("url", "") or ""
    reasons = []

    score = 60

    if len(title) < 8:
        score -= 10
        reasons.append({"code": "title_too_short", "delta": -10, "message": "Title is shorter than 8 characters."})
    elif 10 <= len(title) <= 50:
        score += 5
        reasons.append({"code": "title_good_length", "delta": 5, "message": "Title length is suitable."})

    if len(summary) < 50:
        score -= 15
        reasons.append({"code": "summary_too_short", "delta": -15, "message": "Summary is shorter than 50 characters."})
    else:
        delta = min(15, (len(summary) - 50) // 50 * 5)
        score += delta
        if delta:
            reasons.append({"code": "summary_substantial", "delta": delta, "message": "Summary contains reusable detail."})

    if url and (url.startswith("http://") or url.startswith("https://")):
        score += 5
        reasons.append({"code": "source_url_present", "delta": 5, "message": "Source URL is present."})

    for signal in LOW_QUALITY_SIGNALS:
        if signal in title or signal in summary:
            score -= 5
            reasons.append({"code": "low_quality_signal", "delta": -5, "message": f"Low quality signal found: {signal}"})

    if len(title) + len(summary) < 30:
        score -= 20
        reasons.append({"code": "content_too_short", "delta": -20, "message": "Title and summary are too short together."})

    score = max(0, min(100, score))
    if score < 60:
        review_status = "rejected"
    elif score < 75:
        review_status = "pending"
    else:
        review_status = "approved"

    return {
        "score": score,
        "review_status": review_status,
        "reviewed_by": "auto",
        "reasons": reasons,
    }
