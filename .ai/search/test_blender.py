"""
Tests for chunk_id-based score blending.

Key invariants:
- Same chunk_id in both backends → one merged entry with blended_score from both
- Different chunk_ids from same file → two distinct entries (no filename dedup)
- CocoIndex metadata takes precedence when chunk_id appears in both backends
"""

import sys
from blender import blend_scores, normalize_scores


def test_normalize_scores_basic():
    print("Test 1: normalize_scores — min-max scaling to 0-1...")
    results = [
        {"score": 0.9, "chunk_id": "a.php#L1-L10"},
        {"score": 0.5, "chunk_id": "b.php#L1-L10"},
        {"score": 0.1, "chunk_id": "c.php#L1-L10"},
    ]
    normalized = normalize_scores(results)
    assert normalized[0]["score"] == 1.0
    assert normalized[2]["score"] == 0.0
    assert 0 <= normalized[1]["score"] <= 1
    print("  ✓ Scores normalized to [0, 1]")


def test_normalize_scores_all_same():
    print("Test 2: normalize_scores — all same scores → 1.0...")
    results = [{"score": 0.5, "chunk_id": f"a.php#L{i}-L{i+10}"} for i in range(3)]
    normalized = normalize_scores(results)
    assert all(r["score"] == 1.0 for r in normalized)
    print("  ✓ All-same scores → all 1.0")


def test_normalize_scores_empty():
    print("Test 3: normalize_scores — empty list...")
    assert normalize_scores([]) == []
    print("  ✓ Empty list handled")


def test_blend_same_chunk_id_both_backends():
    """Core invariant: same chunk_id → one merged entry."""
    print("Test 4: blend — same chunk_id in both backends → one merged entry...")
    coco = [{
        "chunk_id": "app/Services/Billing.php#L10-L50",
        "filename": "app/Services/Billing.php",
        "score": 0.8,
        "snippet": "coco snippet",
        "layer_type": "service",
        "source": "cocoindex",
    }]
    qdrant = [{
        "chunk_id": "app/Services/Billing.php#L10-L50",
        "filename": "app/Services/Billing.php",
        "score": 0.7,
        "snippet": "qdrant snippet",
        "layer_type": "service",
        "source": "qdrant",
    }]
    results = blend_scores(coco, qdrant, cocoindex_weight=0.7, qdrant_weight=0.3)
    assert len(results) == 1, f"Expected 1 merged entry, got {len(results)}"
    r = results[0]
    assert r["source"] == "both"
    assert r["cocoindex_score"] is not None
    assert r["qdrant_score"] is not None
    # Both normalized to 1.0 (single item per backend), blended = 1.0*0.7 + 1.0*0.3 = 1.0
    assert r["blended_score"] == 1.0, f"Expected 1.0, got {r['blended_score']}"
    # CocoIndex snippet should win
    assert r["snippet"] == "coco snippet"
    print(f"  ✓ One merged entry, blended_score={r['blended_score']}, source={r['source']}")


def test_blend_different_chunk_ids_same_file():
    """Different chunks from the same file stay separate — no filename dedup."""
    print("Test 5: blend — different chunk_ids from same file → two entries...")
    coco = [{
        "chunk_id": "app/Services/Billing.php#L1-L50",
        "filename": "app/Services/Billing.php",
        "score": 0.9,
        "snippet": "chunk A",
        "source": "cocoindex",
    }]
    qdrant = [{
        "chunk_id": "app/Services/Billing.php#L51-L100",
        "filename": "app/Services/Billing.php",
        "score": 0.7,
        "snippet": "chunk B",
        "source": "qdrant",
    }]
    results = blend_scores(coco, qdrant)
    assert len(results) == 2, f"Expected 2 distinct entries, got {len(results)}"
    chunk_ids = {r["chunk_id"] for r in results}
    assert "app/Services/Billing.php#L1-L50" in chunk_ids
    assert "app/Services/Billing.php#L51-L100" in chunk_ids
    print("  ✓ Two distinct chunk_ids → two entries (no filename collapse)")


def test_blend_coco_only():
    print("Test 6: blend — cocoindex only...")
    coco = [
        {"chunk_id": "a.php#L1-L10", "filename": "a.php", "score": 0.8, "snippet": "", "source": "cocoindex"},
        {"chunk_id": "b.php#L1-L10", "filename": "b.php", "score": 0.4, "snippet": "", "source": "cocoindex"},
    ]
    results = blend_scores(coco, [])
    assert len(results) == 2
    # Both normalized: 0.8→1.0, 0.4→0.0; blended = score * 0.7
    scores = sorted([r["blended_score"] for r in results], reverse=True)
    assert scores[0] == round(1.0 * 0.7, 4), f"Expected 0.7, got {scores[0]}"
    assert scores[1] == round(0.0 * 0.7, 4), f"Expected 0.0, got {scores[1]}"
    print(f"  ✓ Coco-only blended scores: {scores}")


def test_blend_qdrant_only():
    print("Test 7: blend — qdrant only...")
    qdrant = [
        {"chunk_id": "a.php#L1-L10", "filename": "a.php", "score": 0.9, "snippet": "", "source": "qdrant"},
    ]
    results = blend_scores([], qdrant)
    assert len(results) == 1
    assert results[0]["source"] == "qdrant"
    assert results[0]["cocoindex_score"] is None
    assert results[0]["qdrant_score"] is not None
    print("  ✓ Qdrant-only result, cocoindex_score=None")


def test_blend_sorted_desc():
    print("Test 8: blend — results sorted by blended_score DESC...")
    coco = [
        {"chunk_id": f"f{i}.php#L1-L10", "filename": f"f{i}.php", "score": float(i), "snippet": "", "source": "cocoindex"}
        for i in range(5)
    ]
    results = blend_scores(coco, [])
    scores = [r["blended_score"] for r in results]
    assert scores == sorted(scores, reverse=True), f"Not sorted: {scores}"
    print(f"  ✓ Sorted DESC: {scores}")


def test_blend_top_k():
    print("Test 9: blend — top_k limit respected...")
    coco = [
        {"chunk_id": f"f{i}.php#L1-L10", "filename": f"f{i}.php", "score": float(i), "snippet": "", "source": "cocoindex"}
        for i in range(30)
    ]
    results = blend_scores(coco, [], top_k=10)
    assert len(results) == 10, f"Expected 10, got {len(results)}"
    print("  ✓ top_k=10 respected")


def test_blend_missing_chunk_id_skipped():
    """Results without chunk_id are skipped — they can't be merged."""
    print("Test 10: blend — results without chunk_id are skipped...")
    coco = [
        {"chunk_id": "a.php#L1-L10", "filename": "a.php", "score": 0.8, "snippet": "", "source": "cocoindex"},
        {"filename": "b.php", "score": 0.6, "snippet": "", "source": "cocoindex"},  # no chunk_id
    ]
    results = blend_scores(coco, [])
    assert len(results) == 1, f"Expected 1 (b.php skipped), got {len(results)}"
    assert results[0]["chunk_id"] == "a.php#L1-L10"
    print("  ✓ Entry without chunk_id skipped")


def test_blend_required_fields():
    print("Test 11: blend — required fields present...")
    coco = [{"chunk_id": "a.php#L1-L10", "filename": "a.php", "score": 0.8, "snippet": "s", "source": "cocoindex"}]
    qdrant = [{"chunk_id": "a.php#L1-L10", "filename": "a.php", "score": 0.7, "snippet": "s", "source": "qdrant"}]
    results = blend_scores(coco, qdrant)
    assert len(results) == 1
    r = results[0]
    for field in ["chunk_id", "blended_score", "cocoindex_score", "qdrant_score", "source", "sources"]:
        assert field in r, f"Missing field: {field}"
    assert isinstance(r["sources"], list)
    assert r["source"] in ("cocoindex", "qdrant", "both")
    print("  ✓ All required fields present")


def run_all_tests():
    print("\n" + "=" * 60)
    print("Blender Tests (chunk_id-based merge)")
    print("=" * 60 + "\n")

    tests = [
        test_normalize_scores_basic,
        test_normalize_scores_all_same,
        test_normalize_scores_empty,
        test_blend_same_chunk_id_both_backends,
        test_blend_different_chunk_ids_same_file,
        test_blend_coco_only,
        test_blend_qdrant_only,
        test_blend_sorted_desc,
        test_blend_top_k,
        test_blend_missing_chunk_id_skipped,
        test_blend_required_fields,
    ]

    passed = 0
    failed = 0

    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"  ✗ FAILED: {e}\n")
            failed += 1
        except Exception as e:
            print(f"  ✗ ERROR: {e}\n")
            failed += 1

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60 + "\n")
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
