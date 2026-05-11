"""
Test suite for score blending logic.

Tests:
1. Score normalization (0-100 and 0-1 ranges)
2. Score blending (weighted combination)
3. Duplicate handling (merge by filename)
4. Edge cases (empty results, all same scores)
"""

import sys
from blender import blend_scores, normalize_scores, merge_results


def test_normalize_scores_0_100_range():
    """Test normalization of scores in 0-100 range."""
    print("Test 1: Normalize 0-100 range...")
    results = [
        {"score": 100, "filename": "a.js"},
        {"score": 50, "filename": "b.js"},
        {"score": 25, "filename": "c.js"},
    ]
    
    normalized = normalize_scores(results)
    
    # Should be normalized to 0-1 range
    assert 0 <= normalized[0]["score"] <= 1, f"Score out of range: {normalized[0]['score']}"
    assert 0 <= normalized[1]["score"] <= 1, f"Score out of range: {normalized[1]['score']}"
    assert 0 <= normalized[2]["score"] <= 1, f"Score out of range: {normalized[2]['score']}"
    
    # Highest score should be 1.0, lowest should be 0.0
    assert normalized[0]["score"] == 1.0, f"Max score should be 1.0, got {normalized[0]['score']}"
    assert normalized[2]["score"] == 0.0, f"Min score should be 0.0, got {normalized[2]['score']}"
    
    print(f"  ✓ Normalized 0-100 range: {[r['score'] for r in normalized]}")


def test_normalize_scores_0_1_range():
    """Test normalization of scores already in 0-1 range."""
    print("Test 2: Normalize 0-1 range...")
    results = [
        {"score": 0.9, "filename": "a.js"},
        {"score": 0.5, "filename": "b.js"},
        {"score": 0.1, "filename": "c.js"},
    ]
    
    normalized = normalize_scores(results)
    
    assert 0 <= normalized[0]["score"] <= 1
    assert 0 <= normalized[1]["score"] <= 1
    assert 0 <= normalized[2]["score"] <= 1
    
    assert normalized[0]["score"] == 1.0
    assert normalized[2]["score"] == 0.0
    
    print(f"  ✓ Normalized 0-1 range: {[r['score'] for r in normalized]}")


def test_normalize_scores_all_same():
    """Test normalization when all scores are identical."""
    print("Test 3: Normalize all same scores...")
    results = [
        {"score": 0.5, "filename": "a.js"},
        {"score": 0.5, "filename": "b.js"},
        {"score": 0.5, "filename": "c.js"},
    ]
    
    normalized = normalize_scores(results)
    
    # All scores should be 1.0 when all are identical
    assert all(r["score"] == 1.0 for r in normalized), f"Expected all 1.0, got {[r['score'] for r in normalized]}"
    
    print(f"  ✓ All same scores normalized to 1.0")


def test_normalize_scores_empty():
    """Test normalization with empty results."""
    print("Test 4: Normalize empty results...")
    results = []
    normalized = normalize_scores(results)
    assert normalized == [], f"Expected empty list, got {normalized}"
    print(f"  ✓ Empty results handled correctly")


def test_blend_scores_basic():
    """Test basic score blending with 70/30 weights."""
    print("Test 5: Basic score blending (70/30 weights)...")
    
    coco_results = [
        {"score": 0.8, "filename": "auth.py", "location": "L10-20", "snippet": "def login"},
        {"score": 0.6, "filename": "db.py", "location": "L1-10", "snippet": "def connect"},
    ]
    
    qdrant_results = [
        {"score": 0.9, "filename": "auth.py", "location": "L10-20", "snippet": "def login"},
        {"score": 0.4, "filename": "utils.py", "location": "L5-15", "snippet": "def helper"},
    ]
    
    blended = blend_scores(coco_results, qdrant_results, cocoindex_weight=0.7, qdrant_weight=0.3)
    
    # Should have 3 unique files: auth.py (both), db.py (coco only), utils.py (qdrant only)
    assert len(blended) == 3, f"Expected 3 results, got {len(blended)}"
    
    # Find auth.py result (should have both sources)
    auth_result = next((r for r in blended if r["filename"] == "auth.py"), None)
    assert auth_result is not None, "auth.py should be in results"
    assert auth_result["source"] == "both", f"auth.py should be from 'both' sources, got {auth_result['source']}"
    
    # Check blended score calculation for auth.py
    # Normalized: coco 0.8->1.0, qdrant 0.9->1.0
    # Blended: 1.0*0.7 + 1.0*0.3 = 1.0
    expected_score = round(1.0 * 0.7 + 1.0 * 0.3, 4)
    assert auth_result["blended_score"] == expected_score, \
        f"Expected {expected_score}, got {auth_result['blended_score']}"
    
    print(f"  ✓ Blended 3 results correctly")
    print(f"    - auth.py (both sources): {auth_result['blended_score']}")
    for r in blended:
        print(f"    - {r['filename']} ({r['source']}): {r['blended_score']}")


def test_blend_scores_no_duplicates():
    """Test that blending avoids duplicates."""
    print("Test 6: Avoid duplicates in blended results...")
    
    coco_results = [
        {"score": 0.8, "filename": "auth.py", "location": "L10-20", "snippet": "login"},
    ]
    
    qdrant_results = [
        {"score": 0.9, "filename": "auth.py", "location": "L10-20", "snippet": "login"},
    ]
    
    blended = blend_scores(coco_results, qdrant_results)
    
    # Should have only 1 result (merged)
    assert len(blended) == 1, f"Expected 1 result, got {len(blended)}"
    assert blended[0]["filename"] == "auth.py"
    assert blended[0]["source"] == "both"
    
    print(f"  ✓ Duplicates correctly merged into single result")


def test_blend_scores_scoring_formula():
    """Test the scoring formula: 0.7*coco + 0.3*qdrant."""
    print("Test 7: Verify scoring formula (0.7*coco + 0.3*qdrant)...")
    
    coco_results = [
        {"score": 100, "filename": "file1.js", "location": "L1", "snippet": "code1"},
        {"score": 50, "filename": "file3.js", "location": "L1", "snippet": "code1"},
    ]
    
    qdrant_results = [
        {"score": 0.9, "filename": "file2.js", "location": "L2", "snippet": "code2"},
        {"score": 0.3, "filename": "file4.js", "location": "L2", "snippet": "code2"},
    ]
    
    blended = blend_scores(coco_results, qdrant_results, cocoindex_weight=0.7, qdrant_weight=0.3)
    
    # After normalization within each source:
    # cocoindex: 100->1.0, 50->0.0 (normalized independently)
    # qdrant: 0.9->1.0, 0.3->0.0 (normalized independently)
    
    # Find file1.js (coco: 100 -> 1.0 after normalization)
    file1 = next((r for r in blended if r["filename"] == "file1.js"), None)
    assert file1 is not None
    # score should be 1.0 * 0.7 = 0.7
    assert file1["blended_score"] == 0.7, f"Expected 0.7, got {file1['blended_score']}"
    
    # Find file3.js (coco: 50 -> 0.0 after normalization)
    file3 = next((r for r in blended if r["filename"] == "file3.js"), None)
    assert file3 is not None
    # score should be 0.0 * 0.7 = 0.0
    assert file3["blended_score"] == 0.0, f"Expected 0.0, got {file3['blended_score']}"
    
    # Find file2.js (qdrant: 0.9 -> 1.0 after normalization)
    file2 = next((r for r in blended if r["filename"] == "file2.js"), None)
    assert file2 is not None
    # score should be 1.0 * 0.3 = 0.3
    assert file2["blended_score"] == 0.3, f"Expected 0.3, got {file2['blended_score']}"
    
    # Find file4.js (qdrant: 0.3 -> 0.0 after normalization)
    file4 = next((r for r in blended if r["filename"] == "file4.js"), None)
    assert file4 is not None
    # score should be 0.0 * 0.3 = 0.0
    assert file4["blended_score"] == 0.0, f"Expected 0.0, got {file4['blended_score']}"
    
    print(f"  ✓ Scoring formula verified:")
    print(f"    - file1.js (coco 100->1.0): {file1['blended_score']} = 1.0 * 0.7")
    print(f"    - file3.js (coco 50->0.0): {file3['blended_score']} = 0.0 * 0.7")
    print(f"    - file2.js (qdrant 0.9->1.0): {file2['blended_score']} = 1.0 * 0.3")
    print(f"    - file4.js (qdrant 0.3->0.0): {file4['blended_score']} = 0.0 * 0.3")


def test_blend_scores_sorted_by_score():
    """Test that results are sorted by blended_score descending."""
    print("Test 8: Results sorted by blended_score DESC...")
    
    coco_results = [
        {"score": 1.0, "filename": "a.js", "location": "L1", "snippet": ""},
        {"score": 0.5, "filename": "b.js", "location": "L2", "snippet": ""},
        {"score": 0.3, "filename": "c.js", "location": "L3", "snippet": ""},
    ]
    
    qdrant_results = []
    
    blended = blend_scores(coco_results, qdrant_results)
    
    # Check sorted order
    scores = [r["blended_score"] for r in blended]
    assert scores == sorted(scores, reverse=True), f"Scores not sorted: {scores}"
    
    print(f"  ✓ Results sorted by score DESC: {scores}")


def test_blend_scores_top_k_limit():
    """Test that blending respects top_k limit."""
    print("Test 9: Respect top_k limit...")
    
    coco_results = [
        {"score": float(100-i), "filename": f"file{i}.js", "location": f"L{i}", "snippet": ""}
        for i in range(30)
    ]
    
    qdrant_results = []
    
    blended = blend_scores(coco_results, qdrant_results, top_k=10)
    
    assert len(blended) == 10, f"Expected 10 results, got {len(blended)}"
    
    print(f"  ✓ Results limited to top_k={10}: {len(blended)} results returned")


def test_blend_scores_result_fields():
    """Test that blended results have required fields."""
    print("Test 10: Result fields present and valid...")
    
    coco_results = [
        {"score": 0.8, "filename": "auth.py", "location": "L10-20", "snippet": "def login"},
    ]
    
    qdrant_results = [
        {"score": 0.9, "filename": "auth.py", "location": "L10-20", "snippet": "def login"},
    ]
    
    blended = blend_scores(coco_results, qdrant_results)
    
    required_fields = ["source", "blended_score", "cocoindex_score", "qdrant_score", "filename", "sources"]
    
    for result in blended:
        for field in required_fields:
            assert field in result, f"Missing field: {field} in {result}"
    
    # Verify source is one of: cocoindex, qdrant, both
    assert blended[0]["source"] in ["cocoindex", "qdrant", "both"]
    
    # Verify sources is a list
    assert isinstance(blended[0]["sources"], list)
    
    print(f"  ✓ All required fields present in results")
    print(f"    Fields: {list(blended[0].keys())}")


def test_deduplicate_keeps_best_chunk():
    """Test that deduplicate_results keeps only highest-scoring chunk per filename."""
    print("Test 11: Dedup keeps highest-scoring chunk per file...")
    from blender import deduplicate_results
    results = [
        {"filename": "BillingService.php", "score": 0.6, "snippet": "chunk1"},
        {"filename": "BillingService.php", "score": 0.9, "snippet": "chunk2"},
        {"filename": "BillingService.php", "score": 0.4, "snippet": "chunk3"},
        {"filename": "Other.php", "score": 0.7, "snippet": "other"},
    ]
    deduped = deduplicate_results(results)
    assert len(deduped) == 2, f"Expected 2 files, got {len(deduped)}"
    billing = next(r for r in deduped if r["filename"] == "BillingService.php")
    assert billing["score"] == 0.9, f"Expected best chunk score 0.9, got {billing['score']}"
    assert billing["snippet"] == "chunk2"
    print("  ✓ Best chunk kept, others discarded")


def test_deduplicate_single_entry_per_file():
    """Test deduplicate with files that only appear once."""
    print("Test 12: Dedup passes through single-occurrence files...")
    from blender import deduplicate_results
    results = [
        {"filename": "a.php", "score": 0.8, "snippet": "a"},
        {"filename": "b.php", "score": 0.5, "snippet": "b"},
    ]
    deduped = deduplicate_results(results)
    assert len(deduped) == 2
    print("  ✓ Single-occurrence files preserved")


def test_blend_deduplicates_coco_chunks():
    """Test that blend_scores deduplicates multiple CocoIndex chunks for same file."""
    print("Test 13: Blend deduplicates CocoIndex multi-chunk files...")
    coco_results = [
        {"score": 0.9, "filename": "BillingService.php", "location": "L1-50", "snippet": "chunk1"},
        {"score": 0.4, "filename": "BillingService.php", "location": "L50-100", "snippet": "chunk2"},
        {"score": 0.6, "filename": "Other.php", "location": "L1-30", "snippet": "other"},
    ]
    blended = blend_scores(coco_results, [])
    filenames = [r["filename"] for r in blended]
    assert filenames.count("BillingService.php") == 1, f"Expected 1 BillingService.php, got {filenames.count('BillingService.php')}"
    billing = next(r for r in blended if r["filename"] == "BillingService.php")
    # Best chunk (0.9) should win, not inflate score via accumulation
    assert billing["cocoindex_score"] == 1.0, f"Expected normalized 1.0 for best chunk, got {billing['cocoindex_score']}"
    print("  ✓ Multi-chunk files deduplicated to single best result")


def run_all_tests():
    """Run all tests."""
    print("\n" + "="*60)
    print("Running Blender Score Tests")
    print("="*60 + "\n")

    tests = [
        test_normalize_scores_0_100_range,
        test_normalize_scores_0_1_range,
        test_normalize_scores_all_same,
        test_normalize_scores_empty,
        test_blend_scores_basic,
        test_blend_scores_no_duplicates,
        test_blend_scores_scoring_formula,
        test_blend_scores_sorted_by_score,
        test_blend_scores_top_k_limit,
        test_blend_scores_result_fields,
        test_deduplicate_keeps_best_chunk,
        test_deduplicate_single_entry_per_file,
        test_blend_deduplicates_coco_chunks,
    ]
    
    passed = 0
    failed = 0
    
    for test_func in tests:
        try:
            test_func()
            passed += 1
        except AssertionError as e:
            print(f"  ✗ FAILED: {e}\n")
            failed += 1
        except Exception as e:
            print(f"  ✗ ERROR: {e}\n")
            failed += 1
    
    print("="*60)
    print(f"Results: {passed} passed, {failed} failed")
    print("="*60 + "\n")
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
