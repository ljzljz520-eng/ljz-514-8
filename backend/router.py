"""无障碍加权 Dijkstra 寻路。

权重模型（与 docs/algorithm.md、data/weights.json 保持一致）：
  cost(edge) = length_m * base_per_m * type_multiplier * surface_factor
             * slope_factor * width_factor * accessible_factor
             + stairs_cost / elevator_cost / door_cost
坡度因子: 1 + k_linear * grade + k_cubic * grade^3
"""
import heapq
import math

from store import load_graph, load_weights


def _distance_px(n1, n2):
    return math.hypot(n1["x"] - n2["x"], n1["y"] - n2["y"])


def edge_length_m(graph, edge):
    """边的物理长度(米)：显式 length 优先，否则按像素坐标换算（1 像素=0.55 米），
    楼层间的电梯/楼梯不按坐标估长，而按楼层数固定计价。"""
    etype = edge.get("type")
    if etype in ("elevator", "stairs"):
        return 3.0 * max(1, int(edge.get("floors", 1)))
    if edge.get("length") is not None:
        return float(edge["length"])
    nodes = graph["_node_index"]
    return round(_distance_px(nodes[edge["a"]], nodes[edge["b"]]) * 0.55, 1)


def edge_cost(graph, edge, profile):
    """计算一条边在指定模式(accessible/regular)下的权重。返回 (cost, flags)。"""
    etype = edge.get("type", "path")
    w = profile
    length = edge_length_m(graph, edge)
    flags = {"warnings": [], "is_stairs": False, "is_steep": False, "is_elevator": False}

    # ---- 台阶：固定高权重（或完全不可通过） ----
    if etype == "stairs":
        sc = w["stairs"]
        if sc.get("blocked") or edge.get("blocked"):
            return float(w["blocked_edge_cost"]), flags
        steps = int(edge.get("stair_count", 12 * edge.get("floors", 1)))
        floors = int(edge.get("floors", 1))
        cost = (sc["per_step"] * steps
                + sc["floors_per_floor"] * floors
                + sc["length_factor"] * length)
        flags["is_stairs"] = True
        flags["warnings"].append(
            f"含台阶 {steps} 级（跨越 {floors} 层），轮椅无法通行，请谨慎选择")
        return cost, flags

    # ---- 电梯：固定等待/乘坐开销 + 很低的移动开销 ----
    if etype == "elevator":
        ec = w["elevator"]
        floors = int(edge.get("floors", 1))
        cost = ec["per_floor"] * floors + ec["length_factor"] * length
        cost *= w.get("accessible_bonus", {}).get("elevator", 1.0)
        flags["is_elevator"] = True
        return cost, flags

    # ---- 门：固定开销 ----
    cost = length * w["base_per_m"]
    cost *= w["type_multiplier"].get(etype, 1.0)

    if etype == "door":
        dc = w["door"]
        cost += dc.get("heavy_door" if edge.get("heavy") else "flat_cost", 2.0)
        if edge.get("width_m") and edge["width_m"] < w["narrow_width_min"]:
            cost += (w["narrow_width_min"] - edge["width_m"]) * 50
        return cost, flags

    # ---- 路面材质 ----
    surface = edge.get("surface", w.get("default_surface", "asphalt"))
    cost *= w["surface_factor"].get(surface, 1.0)

    # ---- 坡度 ----
    grade = float(edge.get("grade", 0) or 0)
    g = w["grade"]
    if grade > 0:
        cost *= 1.0 + g["k_linear"] * grade + g["k_cubic"] * grade ** 3
    if etype == "ramp":
        cost *= w.get("accessible_bonus", {}).get("ramp", 1.0)
        if grade > g["ramp_max"]:
            flags["warnings"].append(
                f"坡道坡度 {grade:.1%} 超过规范 1:12 ({g['ramp_max']:.1%})")
    elif etype == "slope" and grade >= g.get("ramp_max", 0.083):
        flags["is_steep"] = True
        flags["warnings"].append(f"陡坡，坡度约 {grade:.0%}，轮椅通行困难")

    # ---- 宽度不足 ----
    width = edge.get("width_m")
    if width and width < w["narrow_width_min"]:
        cost += w["narrow_penalty_per_m"] * (w["narrow_width_min"] - width) * length
        flags["warnings"].append(f"通道净宽 {width}m 偏窄")

    # ---- 盲道奖励（仅无障碍模式生效，regular 因子为 1） ----
    if edge.get("tactile"):
        cost *= w.get("tactile_factor", 1.0)

    if edge.get("blocked"):
        return float(w["blocked_edge_cost"]), flags

    return cost, flags


def _build_index(graph):
    return {n["id"]: n for n in graph["nodes"]}


def dijkstra(graph, start, goal, mode="accessible"):
    graph["_node_index"] = _build_index(graph)
    weights = load_weights()
    profile = weights[mode]

    nodes = graph["_node_index"]
    if start not in nodes or goal not in nodes:
        raise ValueError("起点或终点不存在")

    adj = {}
    edge_flags = {}
    for e in graph["edges"]:
        cost, flags = edge_cost(graph, e, profile)
        adj.setdefault(e["a"], []).append((e["b"], cost, e["id"]))
        adj.setdefault(e["b"], []).append((e["a"], cost, e["id"]))
        edge_flags[e["id"]] = flags

    dist = {start: 0.0}
    prev = {}
    pq = [(0.0, start)]
    visited = set()
    while pq:
        d, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)
        if u == goal:
            break
        for v, c, eid in adj.get(u, []):
            nd = d + c
            if nd < dist.get(v, math.inf):
                dist[v] = nd
                prev[v] = (u, eid, c)
                heapq.heappush(pq, (nd, v))

    if goal not in dist:
        return None

    # 回溯
    node_ids, edge_ids = [goal], []
    cur = goal
    while cur != start:
        u, eid, c = prev[cur]
        edge_ids.append(eid)
        node_ids.append(u)
        cur = u
    node_ids.reverse()
    edge_ids.reverse()

    edge_map = {e["id"]: e for e in graph["edges"]}
    warnings, used_stairs, used_steep, used_elev = [], 0, 0, 0
    total_m = 0.0
    for eid in edge_ids:
        e = edge_map[eid]
        total_m += edge_length_m(graph, e)
        f = edge_flags[eid]
        warnings.extend(f["warnings"])
        used_stairs += 1 if f["is_stairs"] else 0
        used_steep += 1 if f["is_steep"] else 0
        used_elev += 1 if f["is_elevator"] else 0

    return {
        "mode": mode,
        "node_ids": node_ids,
        "edge_ids": edge_ids,
        "weight": round(dist[goal], 2),
        "distance_m": round(total_m, 1),
        "stairs_segments": used_stairs,
        "steep_segments": used_steep,
        "elevator_segments": used_elev,
        "warnings": warnings,
        "duration_min": estimate_minutes(graph, edge_map, edge_ids, mode),
        "instructions": build_instructions(graph, edge_map, edge_ids, node_ids, nodes),
    }


def estimate_minutes(graph, edge_map, edge_ids, mode):
    """按通行方式估算用时（分钟）。"""
    speed = {"accessible": 1.1, "regular": 1.4}[mode]
    seconds = 0.0
    for eid in edge_ids:
        e = edge_map[eid]
        t = e.get("type")
        if t == "elevator":
            seconds += 20 + 15 * int(e.get("floors", 1))
        elif t == "stairs":
            seconds += int(e.get("stair_count", 12)) * (2.2 if mode == "accessible" else 0.8)
        elif t == "door":
            seconds += 6
        else:
            seconds += edge_length_m(graph, e) / speed
    return round(seconds / 60, 1)


def build_instructions(graph, edge_map, edge_ids, node_ids, nodes):
    steps = []
    for i, eid in enumerate(edge_ids, 1):
        e = edge_map[eid]
        # 按路线实际通行方向确定上一节点 / 到达节点
        prev_id, cur_id = node_ids[i - 1], node_ids[i]
        src, dst = nodes[prev_id], nodes[cur_id]
        t = e.get("type")
        length = edge_length_m(graph, e)
        if t == "elevator":
            text = f"在 {src.get('name', src['id'])} 乘电梯前往 {dst.get('name', dst['id'])}（跨越 {e.get('floors', 1)} 层）"
            icon = "elevator"
        elif t == "stairs":
            text = f"经台阶由 {src.get('name', src['id'])} 前往 {dst.get('name', dst['id'])}（{e.get('stair_count', '?')} 级）"
            icon = "stairs"
        elif t == "door":
            entering = dst.get("type") in ("indoor", "room", "elevator", "stairs")
            if entering:
                text = f"通过 {src.get('name', src['id'])} 进入建筑，到达 {dst.get('name', dst['id'])}"
            else:
                text = f"经 {dst.get('name', dst['id'])} 离开建筑"
            icon = "door"
        elif t == "ramp":
            text = f"沿无障碍坡道前行约 {length:.0f} 米，到达 {dst.get('name', dst['id'])}（坡度 {e.get('grade', 0):.0%}）"
            icon = "ramp"
        elif t == "slope":
            text = f"沿坡路前行约 {length:.0f} 米，到达 {dst.get('name', dst['id'])}（坡度 {e.get('grade', 0):.0%}）"
            icon = "slope"
        elif t == "corridor":
            text = f"沿室内通道前往 {dst.get('name', dst['id'])}（约 {length:.0f} 米）"
            icon = "corridor"
        else:
            text = f"沿道路前行约 {length:.0f} 米，到达 {dst.get('name', dst['id'])}"
            icon = "path"
        if e.get("tactile"):
            text += "（沿线有盲道）"
        steps.append({"seq": i, "text": text, "icon": icon, "edge_id": eid})
    return steps


def find_route(start, goal, mode="accessible", compare=True):
    graph = load_graph()
    result = dijkstra(graph, start, goal, mode)
    if result is None:
        return {"ok": False, "error": "两点之间没有可达路径"}
    out = {"ok": True, "route": result}
    if compare and mode == "accessible":
        regular = dijkstra(load_graph(), start, goal, "regular")
        if regular:
            out["regular_comparison"] = {
                "weight": regular["weight"],
                "distance_m": regular["distance_m"],
                "stairs_segments": regular["stairs_segments"],
                "steep_segments": regular["steep_segments"],
                "duration_min": regular["duration_min"],
                "edge_ids": regular["edge_ids"],
                "node_ids": regular["node_ids"],
            }
    return out
