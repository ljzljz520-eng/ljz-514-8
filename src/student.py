"""学生端：选择起终点（宿舍/教学楼/食堂/图书馆），查询无障碍路线。"""
from __future__ import annotations

from .models import CampusGraph, EdgeType, NodeKind
from .routing import RouteResult, plan_route
from .weights import WeightConfig

# 各类通道的参考通行速度（米/秒），用于估算行程时间
SPEED = {
    EdgeType.WALKWAY: 1.2,
    EdgeType.RAMP: 0.9,
    EdgeType.STAIRS: 0.6,
    EdgeType.ELEVATOR: 0.0,   # 电梯按候梯+运行时间单独计算
}
ELEVATOR_RIDE_SECONDS = 10.0


def list_places(graph: CampusGraph) -> dict[str, list[tuple[str, str]]]:
    """按类别分组返回可作为起终点的地点：{类别标签: [(id, 名称)]}。"""
    grouped: dict[str, list[tuple[str, str]]] = {
        NodeKind.LABELS[k]: [] for k in NodeKind.DESTINATIONS
    }
    for node in graph.nodes.values():
        if node.kind in NodeKind.DESTINATIONS:
            grouped[NodeKind.LABELS[node.kind]].append((node.id, node.name))
    return grouped


def estimate_seconds(graph: CampusGraph, result: RouteResult) -> float:
    """按通道类型估算行程时间（秒）。"""
    total = 0.0
    for seg in result.segments:
        if seg.edge_type == EdgeType.ELEVATOR:
            wait = 0.0
            for e in graph.neighbors(seg.source):
                if e.target == seg.target:
                    wait = e.elevator_wait
                    break
            total += wait + ELEVATOR_RIDE_SECONDS
        else:
            total += seg.length / SPEED[seg.edge_type]
    return total


def format_route(graph: CampusGraph, result: RouteResult) -> str:
    """把规划结果格式化为学生可读的路线指引。"""
    if not result.found:
        return "未找到可用路线：起点与终点之间暂无连通通道，请联系管理员完善校园图数据。"

    lines: list[str] = []
    if result.fallback:
        lines.append("⚠ 未找到全程无障碍的路线，以下路线包含楼梯或陡坡，请谨慎选择：")
    elif result.mode == "prefer":
        lines.append("⚠ 当前为“优先无障碍”模式，路线可能包含楼梯或陡坡：")

    lines.append("路线：" + " → ".join(graph.nodes[n].name for n in result.path))
    lines.append("")
    lines.append("分段指引：")
    for i, seg in enumerate(result.segments, 1):
        label = EdgeType.LABELS[seg.edge_type]
        frm, to = graph.nodes[seg.source].name, graph.nodes[seg.target].name
        detail = f"  {i}. [{label}] {frm} → {to}，{seg.length:.0f} 米"
        if seg.edge_type == EdgeType.RAMP:
            detail += f"，坡度 {seg.slope:.1f}%"
        elif seg.edge_type == EdgeType.WALKWAY and seg.slope > 0:
            detail += f"，坡度 {seg.slope:.1f}%"
        elif seg.edge_type == EdgeType.ELEVATOR:
            wait = next((e.elevator_wait for e in graph.neighbors(seg.source)
                         if e.target == seg.target), 0.0)
            detail += f"，平均候梯 {wait:.0f} 秒"
        elif seg.edge_type == EdgeType.STAIRS:
            detail += "（楼梯！）"
        lines.append(detail)

    minutes = estimate_seconds(graph, result) / 60.0
    lines.append("")
    lines.append(f"总里程约 {result.total_length:.0f} 米，预计用时约 {minutes:.1f} 分钟。")
    if result.fully_accessible:
        lines.append("✓ 全程无障碍：仅由平缓通道、坡道和电梯组成，已避开楼梯与陡坡。")
    return "\n".join(lines)


def query_route(graph: CampusGraph, start: str, goal: str,
                mode: str = "strict") -> str:
    """学生查询入口：mode=strict 严格无障碍（可自动降级），prefer 优先无障碍。"""
    config = WeightConfig(strict=(mode == "strict"))
    return format_route(graph, plan_route(graph, start, goal, config))
