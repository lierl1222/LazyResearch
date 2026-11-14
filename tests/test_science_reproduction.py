from lazyresearch.science.reproduce import compare_final


def test_final_comparison_rejects_failed_or_changed_test():
    original = {"candidate_id": "e1", "metrics": {"average_precision": .7}, "predictions": [.1, .8], "labels": [0, 1]}
    assert compare_final(original, dict(original))["matches"]
    assert not compare_final(original, {"error": "timeout"})["matches"]
    assert not compare_final(original, {**original, "metrics": {"average_precision": .6}})["matches"]
    assert not compare_final(original, {**original, "predictions": [.2, .8]})["matches"]
