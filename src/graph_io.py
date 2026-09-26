"""校园图数据的 JSON 持久化（加载 / 保存）。"""
from __future__ import annotations

import json
from pathlib import Path

from .models import CampusGraph, Edge, Node

DEFAULT_DATA = Path(__file__).resolve().parent.parent / "data" / "campus_graph.json"


def load_graph(path: str | Path = DEFAULT_DATA) -> CampusGraph:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    graph = CampusGraph()
    for n in raw.get("nodes", []):
        graph.add_node(Node(
            id=n["id"], name=n["name"],
            kind=n.get("kind", "junction"),
            x=n.get("x", 0.0), y=n.get("y", 0.0),
        ))
    for e in raw.get("edges", []):
        graph.add_edge(Edge(
            source=e["source"], target=e["target"],
            length=float(e["length"]),
            edge_type=e.get("edge_type", "walkway"),
            slope=float(e.get("slope", 0.0)),
            elevator_wait=float(e.get("elevator_wait", 0.0)),
            bidirectional=bool(e.get("bidirectional", True)),
            note=e.get("note", ""),
        ))
    return graph


def save_graph(graph: CampusGraph, path: str | Path = DEFAULT_DATA) -> None:
    # 只导出正向定义的边（反向边由 bidirectional 标志重建），避免重复
    seen: set[tuple[str, str]] = set()
    edges = []
    for edges_from in graph.adj.values():
        for e in edges_from:
            key = (e.source, e.target)
            if key in seen or (e.target, e.source) in seen:
                continue
            seen.add(key)
            edges.append({
                "source": e.source, "target": e.target,
                "length": e.length, "edge_type": e.edge_type,
                "slope": e.slope, "elevator_wait": e.elevator_wait,
                "bidirectional": True, "note": e.note,
            })
    payload = {
        "nodes": [
            {"id": n.id, "name": n.name, "kind": n.kind, "x": n.x, "y": n.y}
            for n in graph.nodes.values()
        ],
        "edges": edges,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
