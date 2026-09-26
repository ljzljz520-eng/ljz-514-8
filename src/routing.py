"""无障碍路线规划核心：加权 Dijkstra 最短路。

规划策略：
1. 先在「严格无障碍」模式下求解——楼梯与陡坡不可通行，
   保证结果只由电梯、坡道和平缓通道组成；
2. 若严格模式无解（图数据不完整或确实不存在无障碍通路），
   自动降级为「优先无障碍」模式：楼梯/陡坡允许通行但施加高额惩罚，
   并在结果中明确标注"非全程无障碍"。
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field, replace

from .models import CampusGraph, EdgeType
from .weights import WeightConfig, edge_cost


@dataclass
class Segment:
    """路线中的一段通道。"""
    source: str
    target: str
    edge_type: str
    length: float
    slope: float
    cost: float


@dataclass
class RouteResult:
    found: bool
    path: list[str] = field(default_factory=list)       # 节点 id 序列
    segments: list[Segment] = field(default_factory=list)
    total_length: float = 0.0                            # 实际里程（米）
    total_cost: float = 0.0                              # 加权成本
    fully_accessible: bool = False                       # 是否全程无障碍
    mode: str = "strict"                                 # 实际使用的模式
    fallback: bool = False                               # 是否由严格模式降级而来


def _dijkstra(graph: CampusGraph, start: str, goal: str,
              config: WeightConfig) -> RouteResult:
    """在给定权重配置下求 start→goal 的最小成本路线。"""
    if start not in graph.nodes:
        raise KeyError(f"起点不存在: {start}")
    if goal not in graph.nodes:
        raise KeyError(f"终点不存在: {goal}")

    dist: dict[str, float] = {start: 0.0}
    prev: dict[str, tuple[str, object]] = {}             # node -> (前驱, 边)
    # 堆元素: (累计成本, 节点id)；节点 id 作为第二键保证可比较
    heap: list[tuple[float, str]] = [(0.0, start)]
    settled: set[str] = set()

    while heap:
        d, u = heapq.heappop(heap)
        if u in settled:
            continue
        settled.add(u)
        if u == goal:
            break
        for edge in graph.neighbors(u):
            w = edge_cost(edge, config)
            if math.isinf(w):
                continue                                   # 不可通行
            nd = d + w
            if nd < dist.get(edge.target, math.inf):
                dist[edge.target] = nd
                prev[edge.target] = (u, edge)
                heapq.heappush(heap, (nd, edge.target))

    if goal not in dist:
        return RouteResult(found=False, mode="strict" if config.strict else "prefer")

    # 回溯路径
    path = [goal]
    segments: list[Segment] = []
    node = goal
    while node != start:
        p, edge = prev[node]
        path.append(p)
        segments.append(Segment(
            source=edge.source, target=edge.target,
            edge_type=edge.edge_type, length=edge.length,
            slope=edge.slope, cost=edge_cost(edge, config),
        ))
        node = p
    path.reverse()
    segments.reverse()

    accessible = all(
        s.edge_type != EdgeType.STAIRS and s.slope <= config.slope_hard_limit
        for s in segments
    )
    return RouteResult(
        found=True,
        path=path,
        segments=segments,
        total_length=sum(s.length for s in segments),
        total_cost=dist[goal],
        fully_accessible=accessible,
        mode="strict" if config.strict else "prefer",
    )


def plan_route(graph: CampusGraph, start: str, goal: str,
               config: WeightConfig | None = None) -> RouteResult:
    """规划无障碍路线。

    - config.strict=True（默认）：先严格模式求解，无解时自动降级为
      优先模式兜底（结果标记 fallback=True）；
    - config.strict=False：直接使用优先模式（楼梯/陡坡重罚但允许通行）。
    """
    base = config or WeightConfig()
    if not base.strict:
        return _dijkstra(graph, start, goal, base)

    strict_result = _dijkstra(graph, start, goal, base)
    if strict_result.found:
        return strict_result

    # 严格模式无解 → 降级为优先模式（楼梯/陡坡重罚但允许通行）
    prefer_result = _dijkstra(graph, start, goal, replace(base, strict=False))
    if prefer_result.found:
        prefer_result.fallback = True
        prefer_result.fully_accessible = False
    return prefer_result
