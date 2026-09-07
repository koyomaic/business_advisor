from __future__ import annotations

from app.targets import find_conflicts, normalize, overlap


def test_normalize():
    assert normalize("shared/reports/") == "shared/reports"
    assert normalize("  shared/reports  ") == "shared/reports"
    assert normalize("/abs/path/") == "abs/path"


def test_overlap_same():
    assert overlap("shared/reports", "shared/reports")


def test_overlap_parent_child():
    assert overlap("shared/reports", "shared/reports/9月")
    assert overlap("shared/reports/9月", "shared/reports")


def test_overlap_sibling_no():
    assert not overlap("shared/reports", "shared/report2")
    assert not overlap("shared/a/b", "shared/a/c")


def test_overlap_grandchild():
    assert overlap("shared/reports", "shared/reports/9月/archive")


def test_overlap_nested_grandchild():
    assert overlap("shared", "shared/reports/9月/x.md")


def test_find_conflicts():
    cand = [
        {"id": 1, "user": "li", "targets": ["shared/reports"], "status": "running"},
        {"id": 2, "user": "wang", "targets": ["shared/data"], "status": "queued"},
        {"id": 3, "user": "zhao", "targets": [], "status": "running"},
    ]
    hits = find_conflicts(["shared/reports/9月"], cand)
    assert [h["task_id"] for h in hits] == [1]
    assert hits[0]["user"] == "li"

    assert find_conflicts(["shared/data/2025"], cand) == [
        h for h in find_conflicts(["shared/data/2025"], cand)
        if h["task_id"] == 2
    ]
    # 空 targets 不检查
    assert find_conflicts([], cand) == []
    # 无重叠
    assert find_conflicts(["users/zhang"], cand) == []
