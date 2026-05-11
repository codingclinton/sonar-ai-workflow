"""
Score blending for cocoindex + qdrant search results.

Implements weighted blending strategy:
- Cocoindex (lexical): 70% weight
- Qdrant (semantic): 30% weight

Normalizes scores to 0-1 range, applies weights, and merges results.
"""

from typing import Any, Dict, List, Optional


def normalize_scores(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Normalize scores in results to 0-1 range.

    Handles variable score ranges:
    - If scores are 0-100, divides by 100
    - If scores are 0-1, keeps as-is
    - If all scores are identical, sets to 1.0
    - Returns early for empty lists

    Args:
        results: List of result dictionaries with 'score' field

    Returns:
        List of results with normalized scores in 0-1 range
    """
    if not results:
        return []

    # Extract scores and find min/max
    scores = [r.get("score", 0) for r in results]
    min_score = min(scores) if scores else 0
    max_score = max(scores) if scores else 0

    # Handle edge case: all same score
    if max_score == min_score:
        for result in results:
            result["score"] = 1.0 if max_score > 0 else 0.0
        return results

    # Normalize scores
    score_range = max_score - min_score

    # Detect if scores are in 0-100 range (likely percentages)
    # If max_score > 1, assume 0-100 range
    if max_score > 1:
        # Normalize from 0-100 to 0-1
        for result in results:
            original_score = result.get("score", 0)
            # Normalize min-max to 0-1
            normalized = (original_score - min_score) / score_range if score_range > 0 else 0
            result["score"] = round(normalized, 4)
    else:
        # Already in 0-1 range, just normalize min-max
        for result in results:
            original_score = result.get("score", 0)
            normalized = (original_score - min_score) / score_range if score_range > 0 else 0
            result["score"] = round(normalized, 4)

    return results


def deduplicate_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Keep only the highest-scoring chunk per filename.

    CocoIndex returns multiple chunks per file (different line ranges).
    Before blending we collapse to one entry per file so scores don't
    inflate through accumulation.
    """
    best: Dict[str, Dict[str, Any]] = {}
    for result in results:
        filename = result.get("filename")
        if not filename:
            continue
        if filename not in best or result.get("score", 0) > best[filename].get("score", 0):
            best[filename] = result
    return list(best.values())


def blend_scores(
    cocoindex_results: List[Dict[str, Any]],
    qdrant_results: List[Dict[str, Any]],
    cocoindex_weight: float = 0.7,
    qdrant_weight: float = 0.3,
    top_k: int = 20,
) -> List[Dict[str, Any]]:
    """
    Blend cocoindex and qdrant results using weighted scoring.

    Combines lexical (cocoindex) and semantic (qdrant) search results
    by normalizing their scores and applying configurable weights.

    Merges results by filename to avoid duplicates. When the same file
    appears in both result sets, their scores are added together.

    Args:
        cocoindex_results: Lexical search results from cocoindex
        qdrant_results: Semantic search results from qdrant
        cocoindex_weight: Weight for cocoindex scores (default 0.7)
        qdrant_weight: Weight for qdrant scores (default 0.3)
        top_k: Maximum number of results to return (default 20)

    Returns:
        Merged and sorted results by final blended_score DESC
        Each result includes: source, blended_score, cocoindex_score, qdrant_score
    """
    # Deduplicate to one chunk per file before normalizing
    cocoindex_results = deduplicate_results(cocoindex_results)
    qdrant_results = deduplicate_results(qdrant_results)

    # Normalize scores independently for each source
    norm_coco = normalize_scores([r.copy() for r in cocoindex_results])
    norm_qdrant = normalize_scores([r.copy() for r in qdrant_results])

    # Create merged dictionary keyed by filename
    merged: Dict[str, Dict[str, Any]] = {}

    # Process cocoindex results
    for result in norm_coco:
        filename = result.get("filename")
        if not filename:
            continue

        weighted_score = result.get("score", 0) * cocoindex_weight
        if filename not in merged:
            merged[filename] = {
                "source": "cocoindex",
                "filename": filename,
                "location": result.get("location", ""),
                "snippet": result.get("snippet", ""),
                "blended_score": weighted_score,
                "cocoindex_score": result.get("score", 0),
                "qdrant_score": None,
                "sources": ["cocoindex"],
            }
            if "code" in result:
                merged[filename]["code"] = result["code"]
        else:
            # File already in merged, accumulate score
            merged[filename]["blended_score"] += weighted_score
            merged[filename]["cocoindex_score"] = result.get("score", 0)
            if "cocoindex" not in merged[filename]["sources"]:
                merged[filename]["sources"].append("cocoindex")

    # Process qdrant results
    for result in norm_qdrant:
        # Qdrant results may have 'path' or 'filename' field
        filename = result.get("filename") or result.get("path")
        if not filename:
            continue

        weighted_score = result.get("score", 0) * qdrant_weight
        if filename not in merged:
            merged[filename] = {
                "source": "qdrant",
                "filename": filename,
                "location": result.get("location", ""),
                "snippet": result.get("snippet", ""),
                "blended_score": weighted_score,
                "cocoindex_score": None,
                "qdrant_score": result.get("score", 0),
                "sources": ["qdrant"],
            }
            if "code" in result:
                merged[filename]["code"] = result["code"]
        else:
            # File already in merged, accumulate score
            merged[filename]["blended_score"] += weighted_score
            merged[filename]["qdrant_score"] = result.get("score", 0)
            # Update source to reflect both
            merged[filename]["source"] = "both"
            if "qdrant" not in merged[filename]["sources"]:
                merged[filename]["sources"].append("qdrant")

    # Sort by blended_score descending and limit to top_k
    results = sorted(merged.values(), key=lambda x: x["blended_score"], reverse=True)[:top_k]

    # Round blended scores
    for result in results:
        result["blended_score"] = round(result["blended_score"], 4)

    return results


def merge_results(
    cocoindex_results: List[Dict[str, Any]],
    qdrant_results: List[Dict[str, Any]],
    key_field: str = "filename",
) -> Dict[str, Dict[str, Any]]:
    """
    Merge cocoindex and qdrant results into unified dictionary.

    Creates a dictionary keyed by the specified field (typically filename or path).
    Results from both sources are merged by key, preserving metadata from both.

    Args:
        cocoindex_results: Results from cocoindex
        qdrant_results: Results from qdrant
        key_field: Field to use as merge key (default 'filename')

    Returns:
        Dictionary keyed by key_field with merged metadata
    """
    merged: Dict[str, Dict[str, Any]] = {}

    # Add cocoindex results
    for result in cocoindex_results:
        key = result.get(key_field)
        if key:
            merged[key] = result.copy()
            merged[key]["_source"] = "cocoindex"

    # Merge qdrant results
    for result in qdrant_results:
        key = result.get(key_field) or result.get("path")
        if key:
            if key in merged:
                # Merge metadata
                merged[key]["_sources"] = ["cocoindex", "qdrant"]
                # Add qdrant-specific fields
                for k, v in result.items():
                    if k not in merged[key]:
                        merged[key][k] = v
            else:
                merged[key] = result.copy()
                merged[key]["_source"] = "qdrant"

    return merged
