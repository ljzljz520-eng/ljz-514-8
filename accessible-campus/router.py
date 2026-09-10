# -*- coding: utf-8 -*-
"""
无障碍寻路核心模块
==================

包含三部分:
1. 权重模型   —— 把"距离 + 楼梯 + 坡度 + 路面 + 电梯等待"折算为统一代价
2. CampusGraph —— 校园图数据结构
3. Dijkstra 最短路 + 多途经点路线拼接

权重模型(详见 docs/weights.md):

    W(e) = L(e) × M_type(e) × (1 + S(e)) × M_surface(e) + C(e)

    L(e)       边的实际长度(米)
    M_type(e)  设施类型倍率(平路/坡道/电梯/楼梯/陡坡道)
    S(e)       坡度惩罚系数(按坡度分档)
    M_surface  路面状况倍率(平整/颠簸)
    C(e)       固定成本(电梯等待的等效距离)

约定:权重配置中某一项为 null 表示"禁止通行"(代价视为无穷大)。
"""

import heapq
import math


# ---------------------------------------------------------------------------
# 默认权重配置(data/weights.json 不存在时兜底使用,管理员可在管理端修改)
# ---------------------------------------------------------------------------
DEFAULT_WEIGHTS = {
    "profiles": {
        "wheelchair": {
            "label": "轮椅模式",
            "description": "楼梯与陡坡绝对禁止通行,仅使用电梯、坡道和平缓通道",
            # 设施类型倍率 M_type:null = 禁止通行
            "type_multiplier": {
                "walkway": 1.0,      # 平缓通道
                "ramp": 1.05,        # 无障碍坡道(略绕路,微小代价)
                "elevator": 1.0,     # 电梯(距离短,另计固定等待成本)
                "stairs": None,      # 楼梯:禁止
                "slope_path": 1.0    # 坡道小路(惩罚主要来自坡度分档)
            },
            # 坡度分档惩罚 S(e):[坡度上限, 惩罚系数],null 表示"超过上一档的所有坡度"
            "slope_penalties": [
                [0.05, 0.0],         # ≤5%(1:20):符合无障碍规范,不惩罚
                [0.0833, 2.0],       # 5%~8.33%(1:12):轮椅独立通行上限
                [0.12, 8.0],         # 8.33%~12%:需协助,强惩罚
                [None, 20.0]         # >12%:本模式下已被硬限制拦截,此处兜底
            ],
            "slope_hard_limit": 0.12,   # 坡度硬上限:超过即禁止通行
            "surface_multiplier": {"smooth": 1.0, "rough": 1.8},
            "elevator_fixed_cost": 30.0,  # 电梯等待折算为 30 米等效距离
            "speed_mps": 0.9              # 轮椅平均速度 m/s,用于估算时间
        },
        "standard": {
            "label": "一般无障碍模式",
            "description": "优先避开楼梯和陡坡;实在无替代路线时允许兜底通行",
            "type_multiplier": {
                "walkway": 1.0,
                "ramp": 1.05,
                "elevator": 1.0,
                "stairs": 25.0,      # 楼梯:25 倍距离惩罚,近似"能不走就不走"
                "slope_path": 1.0
            },
            "slope_penalties": [
                [0.05, 0.0],
                [0.0833, 1.5],
                [0.12, 4.0],
                [None, 10.0]
            ],
            "slope_hard_limit": None,   # 不设硬上限
            "surface_multiplier": {"smooth": 1.0, "rough": 1.3},
            "elevator_fixed_cost": 30.0,
            "speed_mps": 1.1
        }
    }
}

# 设施类型中文名(前端/步骤描述共用)
KIND_LABELS = {
    "walkway": "平缓通道",
    "ramp": "无障碍坡道",
    "elevator": "电梯",
    "stairs": "楼梯",
    "slope_path": "坡道"
}


def normalize_profile(raw):
    """把 JSON 中的权重配置转换为可计算的形式(null -> inf)。"""
    p = dict(raw)
    tm = {}
    for k, v in raw.get("type_multiplier", {}).items():
        tm[k] = math.inf if v is None else float(v)
    p["type_multiplier"] = tm
    p["slope_penalties"] = [
        (math.inf if limit is None else float(limit), float(pen))
        for limit, pen in raw.get("slope_penalties", [])
    ]
    hard = raw.get("slope_hard_limit")
    p["slope_hard_limit"] = None if hard is None else float(hard)
    p["surface_multiplier"] = {
        k: float(v) for k, v in raw.get("surface_multiplier", {}).items()
    }
    p["elevator_fixed_cost"] = float(raw.get("elevator_fixed_cost", 0.0))
    p["speed_mps"] = float(raw.get("speed_mps", 1.0))
    return p


# ---------------------------------------------------------------------------
# 校园图
# ---------------------------------------------------------------------------
class CampusGraph:
    def __init__(self, data):
        self.nodes = data.get("nodes", {})
        self.edges = data.get("edges", [])
        self.adj = {}
        for e in self.edges:
            self.adj.setdefault(e["from"], []).append(e)
            if not e.get("oneway"):          # 默认双向通行
                self.adj.setdefault(e["to"], []).append(e)

    def edge_weight(self, edge, profile):
        """计算单条边的通行代价;不可通行返回 math.inf。"""
        kind = edge.get("kind", "walkway")
        slope = float(edge.get("slope", 0.0))
        surface = edge.get("surface", "smooth")
        length = float(edge.get("distance", 0.0))

        # 1) 坡度硬限制(如轮椅模式 >12% 禁行)
        hard = profile.get("slope_hard_limit")
        if hard is not None and slope > hard:
            return math.inf

        # 2) 设施类型倍率(null 已转为 inf,表示禁行)
        m_type = profile["type_multiplier"].get(kind, 1.0)
        if math.isinf(m_type):
            return math.inf

        # 3) 坡度分档惩罚:取第一个满足 slope <= 上限 的档位
        s_pen = 0.0
        for limit, pen in profile["slope_penalties"]:
            if slope <= limit:
                s_pen = pen
                break

        # 4) 路面倍率
        m_surface = profile["surface_multiplier"].get(surface, 1.0)

        # 5) 固定成本(目前仅电梯等待)
        fixed = profile["elevator_fixed_cost"] if kind == "elevator" else 0.0

        return length * m_type * (1.0 + s_pen) * m_surface + fixed

    # -- Dijkstra -----------------------------------------------------------
    def shortest_path(self, start, goal, profile):
        """返回 {'nodes': [...], 'edges': [...], 'cost': float};不可达返回 None。"""
        if start not in self.nodes or goal not in self.nodes:
            return None
        dist = {start: 0.0}
        prev_node, prev_edge = {}, {}
        pq = [(0.0, start)]
        done = set()
        while pq:
            d, u = heapq.heappop(pq)
            if u in done:
                continue
            done.add(u)
            if u == goal:
                break
            for e in self.adj.get(u, []):
                v = e["to"] if e["from"] == u else e["from"]
                w = self.edge_weight(e, profile)
                if math.isinf(w):
                    continue
                nd = d + w
                if nd < dist.get(v, math.inf):
                    dist[v] = nd
                    prev_node[v] = u
                    prev_edge[v] = e["id"]
                    heapq.heappush(pq, (nd, v))
        if goal not in dist:
            return None
        nodes, edges = [goal], []
        cur = goal
        while cur != start:
            edges.append(prev_edge[cur])
            cur = prev_node[cur]
            nodes.append(cur)
        nodes.reverse()
        edges.reverse()
        return {"nodes": nodes, "edges": edges, "cost": dist[goal]}


# ---------------------------------------------------------------------------
# 多途经点路线(宿舍 -> 教学楼 -> 食堂 -> 图书馆 分段拼接)
# ---------------------------------------------------------------------------
def build_route(graph, waypoints, profile, edge_index=None):
    """按顺序经过 waypoints,逐段求最短路并拼接,返回完整路线描述。"""
    if edge_index is None:
        edge_index = {e["id"]: e for e in graph.edges}

    legs, all_nodes, all_edges = [], [], []
    total_cost = 0.0
    for a, b in zip(waypoints, waypoints[1:]):
        leg = graph.shortest_path(a, b, profile)
        if leg is None:
            return None
        legs.append({"from": a, "to": b, **leg})
        total_cost += leg["cost"]
        all_nodes += leg["nodes"] if not all_nodes else leg["nodes"][1:]
        all_edges += leg["edges"]

    # 逐步骤描述 + 统计
    steps, facility_counts = [], {}
    total_distance = 0.0
    elevator_cnt = 0
    for nid_a, nid_b, eid in zip(all_nodes, all_nodes[1:], all_edges):
        e = edge_index[eid]
        kind = e.get("kind", "walkway")
        dist = float(e.get("distance", 0.0))
        total_distance += dist
        facility_counts[kind] = facility_counts.get(kind, 0) + 1
        if kind == "elevator":
            elevator_cnt += 1
        slope_pct = round(float(e.get("slope", 0.0)) * 100, 1)
        desc = KIND_LABELS.get(kind, kind)
        if kind in ("walkway", "ramp", "slope_path") and slope_pct > 0:
            desc += "(坡度 %s%%)" % slope_pct
        steps.append({
            "from": nid_a, "to": nid_b, "edge_id": eid,
            "kind": kind, "distance": dist, "slope": e.get("slope", 0.0),
            "surface": e.get("surface", "smooth"),
            "desc": desc
        })

    speed = profile.get("speed_mps", 1.0)
    est_minutes = round(total_distance / speed / 60.0 + elevator_cnt * 0.5, 1)

    return {
        "waypoints": waypoints,
        "legs": legs,
        "path": {"nodes": all_nodes, "edges": all_edges},
        "steps": steps,
        "total_distance": round(total_distance, 1),
        "total_cost": round(total_cost, 1),
        "estimated_minutes": est_minutes,
        "facility_counts": facility_counts,
        "barrier_free": facility_counts.get("stairs", 0) == 0
    }
