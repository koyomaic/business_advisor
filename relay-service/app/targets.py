from __future__ import annotations

"""targets 归一化与重叠判定（事前防碰）。"""


def normalize(t: str) -> str:
    return t.strip().strip("/")


def overlap(a: str, b: str) -> bool:
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return True
    if a == b:
        return True
    return a.startswith(b + "/") or b.startswith(a + "/")


def find_conflicts(new_targets: list[str], candidates: list[dict]) -> list[dict]:
    """返回与 new_targets 重叠的在途任务列表。"""
    new_targets = [normalize(t) for t in new_targets if normalize(t)]
    if not new_targets:
        return []
    hits = []
    for t in candidates:
        cand = [normalize(x) for x in t.get("targets", []) if normalize(x)]
        if not cand:
            continue
        if any(overlap(a, b) for a in new_targets for b in cand):
            hits.append({
                "task_id": t["id"],
                "user": t["user"],
                "targets": t["targets"],
                "status": t["status"],
            })
    return hits
