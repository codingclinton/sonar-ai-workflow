"""
Score blending for cocoindex + qdrant search results.

Merges by chunk_id (not filename). Each unique chunk_id gets one entry;
scores from both backends are weighted and summed. CocoIndex metadata
takes precedence when a chunk appears in both.

Weights (70/30) are inherited from earlier implementation, not empirically
tuned. Revisit after Phase 7 trace data exists.
"""

from typing import Any, Dict, List


def normalize_scores(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize scores to 0-1 range via min-max scaling."""
    if not results:
        return []

    scores = [r.get("score", 0) for r in results]
    min_score = min(scores)
    max_score = max(scores)

    if max_score == min_score:
        for result in results:
            result["score"] = 1.0 if max_score > 0 else 0.0
        return results

    score_range = max_score - min_score
    for result in results:
        original = result.get("score", 0)
        result["score"] = round((original - min_score) / score_range, 4)

    return results


def blend_scores(
    cocoindex_results: List[Dict[str, Any]],
    qdrant_results: List[Dict[str, Any]],
    cocoindex_weight: float = 0.7,
    qdrant_weight: float = 0.3,
    top_k: int = 20,
) -> List[Dict[str, Any]]:
    """
    Blend cocoindex and qdrant results, merging by chunk_id.

    When the same chunk_id appears in both backends, scores are blended and
    cocoindex metadata takes precedence. Chunks only in one backend get a
    partial weighted score.
    """
    norm_coco   = normalize_scores([r.copy() for r in cocoindex_results])
    norm_qdrant = normalize_scores([r.copy() for r in qdrant_results])

    merged: Dict[str, Dict[str, Any]] = {}

    for r in norm_coco:
        cid = r.get("chunk_id")
        if not cid:
            continue
        merged[cid] = {
            **r,
            "blended_score":    r["score"] * cocoindex_weight,
            "cocoindex_score":  r["score"],
            "qdrant_score":     None,
            "sources":          ["cocoindex"],
            "source":           "cocoindex",
        }

    for r in norm_qdrant:
        cid = r.get("chunk_id")
        if not cid:
            continue
        if cid in merged:
            merged[cid]["blended_score"] += r["score"] * qdrant_weight
            merged[cid]["qdrant_score"]   = r["score"]
            merged[cid]["sources"].append("qdrant")
            merged[cid]["source"]         = "both"
        else:
            merged[cid] = {
                **r,
                "blended_score":   r["score"] * qdrant_weight,
                "cocoindex_score": None,
                "qdrant_score":    r["score"],
                "sources":         ["qdrant"],
                "source":          "qdrant",
            }

    results = sorted(merged.values(), key=lambda x: x["blended_score"], reverse=True)[:top_k]
    for r in results:
        r["blended_score"] = round(r["blended_score"], 4)
    return results
