"""校园图数据模型。

校园被抽象为一张加权图：
- 节点（Node）：宿舍、教学楼、食堂、图书馆、路口、电梯厅等地点；
- 边（Edge）：节点之间的通道，携带长度、类型、坡度等无障碍相关属性。
"""
from __future__ import annotations

from dataclasses import dataclass, field


class EdgeType:
    """通道类型。"""
    WALKWAY = "walkway"      # 平缓通道
    RAMP = "ramp"            # 坡道
    STAIRS = "stairs"        # 楼梯
    ELEVATOR = "elevator"    # 电梯

    ALL = (WALKWAY, RAMP, STAIRS, ELEVATOR)

    LABELS = {
        WALKWAY: "平缓通道",
        RAMP: "坡道",
        STAIRS: "楼梯",
        ELEVATOR: "电梯",
    }


class NodeKind:
    """地点类别。"""
    DORM = "dorm"            # 宿舍
    TEACHING = "teaching"    # 教学楼
    CANTEEN = "canteen"      # 食堂
    LIBRARY = "library"      # 图书馆
    JUNCTION = "junction"    # 普通路口
    ELEVATOR = "elevator"    # 电梯厅

    ALL = (DORM, TEACHING, CANTEEN, LIBRARY, JUNCTION, ELEVATOR)

    LABELS = {
        DORM: "宿舍",
        TEACHING: "教学楼",
        CANTEEN: "食堂",
        LIBRARY: "图书馆",
        JUNCTION: "路口",
        ELEVATOR: "电梯厅",
    }

    # 学生可直接选为起点/终点的地点类别
    DESTINATIONS = (DORM, TEACHING, CANTEEN, LIBRARY)


@dataclass
class Node:
    id: str
    name: str
    kind: str = NodeKind.JUNCTION
    x: float = 0.0           # 校园平面坐标（米），用于展示与扩展
    y: float = 0.0


@dataclass
class Edge:
    source: str
    target: str
    length: float                       # 通道长度（米）
    edge_type: str = EdgeType.WALKWAY
    slope: float = 0.0                  # 坡度（百分比，如 4.5 表示 4.5%）
    elevator_wait: float = 0.0          # 平均候梯时间（秒），仅电梯边有意义
    bidirectional: bool = True
    note: str = ""


@dataclass
class CampusGraph:
    """校园图：节点表 + 邻接表。"""
    nodes: dict[str, Node] = field(default_factory=dict)
    adj: dict[str, list[Edge]] = field(default_factory=dict)

    # ---------- 节点维护 ----------
    def add_node(self, node: Node) -> None:
        if node.id in self.nodes:
            raise ValueError(f"节点已存在: {node.id}")
        self.nodes[node.id] = node
        self.adj.setdefault(node.id, [])

    def remove_node(self, node_id: str) -> None:
        if node_id not in self.nodes:
            raise KeyError(f"节点不存在: {node_id}")
        del self.nodes[node_id]
        self.adj.pop(node_id, None)
        for edges in self.adj.values():
            edges[:] = [e for e in edges if e.target != node_id]

    # ---------- 边维护 ----------
    def add_edge(self, edge: Edge) -> None:
        for nid in (edge.source, edge.target):
            if nid not in self.nodes:
                raise KeyError(f"节点不存在: {nid}")
        self.adj[edge.source].append(edge)
        if edge.bidirectional:
            self.adj[edge.target].append(Edge(
                source=edge.target, target=edge.source,
                length=edge.length, edge_type=edge.edge_type,
                slope=edge.slope, elevator_wait=edge.elevator_wait,
                bidirectional=False, note=edge.note,
            ))

    def remove_edge(self, source: str, target: str) -> int:
        """删除 source→target 及其反向边，返回删除条数。"""
        removed = 0
        for a, b in ((source, target), (target, source)):
            before = len(self.adj.get(a, []))
            self.adj[a] = [e for e in self.adj.get(a, []) if e.target != b]
            removed += before - len(self.adj[a])
        return removed

    def neighbors(self, node_id: str) -> list[Edge]:
        return self.adj.get(node_id, [])

    # ---------- 校验 ----------
    def validate(self) -> list[str]:
        """返回数据问题列表（空列表表示无问题）。"""
        problems: list[str] = []
        for nid, edges in self.adj.items():
            if nid not in self.nodes:
                problems.append(f"邻接表中存在未注册节点: {nid}")
            for e in edges:
                if e.target not in self.nodes:
                    problems.append(f"边 {e.source}->{e.target} 指向不存在的节点")
                if e.length <= 0:
                    problems.append(f"边 {e.source}->{e.target} 长度必须为正数")
                if e.edge_type not in EdgeType.ALL:
                    problems.append(f"边 {e.source}->{e.target} 类型非法: {e.edge_type}")
                if e.slope < 0:
                    problems.append(f"边 {e.source}->{e.target} 坡度不能为负")
        return problems
