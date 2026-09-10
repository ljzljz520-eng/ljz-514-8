#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高校无障碍路线规划系统 —— 后端服务
仅依赖 Python 标准库,直接运行:  python3 server.py [--port 8000]

学生端:  http://localhost:8000/
管理端:  http://localhost:8000/admin
"""

import copy
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from router import CampusGraph, build_route, normalize_profile, DEFAULT_WEIGHTS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CAMPUS_FILE = os.path.join(DATA_DIR, "campus.json")
WEIGHTS_FILE = os.path.join(DATA_DIR, "weights.json")
STATIC_DIR = os.path.join(BASE_DIR, "static")

LOCATION_TYPES = {
    "dormitory": "宿舍",
    "teaching": "教学楼",
    "cafeteria": "食堂",
    "library": "图书馆",
    "junction": "路口/途经点",
}
EDGE_KINDS = ["walkway", "ramp", "elevator", "stairs", "slope_path"]
SURFACES = ["smooth", "rough"]

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


# ---------------------------------------------------------------------------
# 数据存取(内存缓存 + 修改即落盘,读写加锁)
# ---------------------------------------------------------------------------
class DataStore:
    def __init__(self):
        self.lock = threading.RLock()
        self.campus = self._load(CAMPUS_FILE)
        if os.path.exists(WEIGHTS_FILE):
            self.weights = self._load(WEIGHTS_FILE)
        else:
            self.weights = copy.deepcopy(DEFAULT_WEIGHTS)
            self._save(WEIGHTS_FILE, self.weights)

    @staticmethod
    def _load(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _save(path, obj):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)

    # -- 图数据 -------------------------------------------------------------
    def graph(self):
        with self.lock:
            return CampusGraph(self.campus)

    def campus_snapshot(self):
        with self.lock:
            return copy.deepcopy(self.campus)

    def save_campus(self):
        with self.lock:
            self._save(CAMPUS_FILE, self.campus)

    # -- 权重 ---------------------------------------------------------------
    def weights_snapshot(self):
        with self.lock:
            return copy.deepcopy(self.weights)

    def get_profile(self, name):
        with self.lock:
            raw = self.weights.get("profiles", {}).get(name)
        return normalize_profile(raw) if raw else None

    def replace_weights(self, weights):
        with self.lock:
            self.weights = weights
            self._save(WEIGHTS_FILE, self.weights)


STORE = DataStore()


# ---------------------------------------------------------------------------
# 输入校验
# ---------------------------------------------------------------------------
def validate_node(data, node_id=None):
    nid = (node_id or data.get("id") or "").strip()
    if not nid:
        return None, "节点 id 不能为空"
    name = (data.get("name") or "").strip()
    if not name:
        return None, "节点名称不能为空"
    ntype = data.get("type", "junction")
    if ntype not in LOCATION_TYPES:
        return None, "未知节点类型: %s" % ntype
    try:
        x, y = float(data.get("x", 0)), float(data.get("y", 0))
    except (TypeError, ValueError):
        return None, "坐标必须是数字"
    return {"id": nid, "node": {"name": name, "type": ntype, "x": x, "y": y}}, None


def validate_edge(data, edge_id=None):
    eid = (edge_id or data.get("id") or "").strip()
    if not eid:
        return None, "边 id 不能为空"
    a, b = data.get("from"), data.get("to")
    campus = STORE.campus_snapshot()
    if a not in campus["nodes"] or b not in campus["nodes"]:
        return None, "边的起止节点不存在"
    if a == b:
        return None, "边的起点和终点不能相同"
    kind = data.get("kind", "walkway")
    if kind not in EDGE_KINDS:
        return None, "未知边类型: %s" % kind
    surface = data.get("surface", "smooth")
    if surface not in SURFACES:
        return None, "未知路面类型: %s" % surface
    try:
        distance = float(data.get("distance", 0))
        slope = float(data.get("slope", 0))
    except (TypeError, ValueError):
        return None, "距离和坡度必须是数字"
    if distance <= 0:
        return None, "距离必须大于 0"
    if not (0 <= slope <= 0.5):
        return None, "坡度应在 0~0.5 之间(如 0.08 表示 8%)"
    return {"id": eid, "edge": {
        "id": eid, "from": a, "to": b, "distance": distance,
        "kind": kind, "slope": slope, "surface": surface,
        "oneway": bool(data.get("oneway", False)),
    }}, None


def validate_weights(data):
    if not isinstance(data, dict) or "profiles" not in data:
        return "权重配置必须包含 profiles 对象"
    for name, p in data["profiles"].items():
        if not isinstance(p.get("type_multiplier"), dict):
            return "profile %s 缺少 type_multiplier" % name
        if not isinstance(p.get("slope_penalties"), list):
            return "profile %s 缺少 slope_penalties" % name
    return None


# ---------------------------------------------------------------------------
# HTTP 处理器
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "AccessibleCampus/1.0"

    # -- 工具 ---------------------------------------------------------------
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return None

    def _serve_static(self, path):
        if path == "/":
            path = "/index.html"
        elif path == "/admin":
            path = "/admin.html"
        else:
            path = path[len("/static"):] if path.startswith("/static") else path
        full = os.path.normpath(os.path.join(STATIC_DIR, path.lstrip("/")))
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            return self._send(404, {"error": "not found"})
        ext = os.path.splitext(full)[1]
        with open(full, "rb") as f:
            self._send(200, f.read(), MIME.get(ext, "application/octet-stream"))

    def log_message(self, fmt, *args):  # 精简日志
        pass

    # -- GET ----------------------------------------------------------------
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/admin") or path.startswith("/static/"):
            return self._serve_static(path)

        if path == "/api/locations":
            campus = STORE.campus_snapshot()
            locs = [
                {"id": nid, "name": n["name"], "type": n["type"]}
                for nid, n in campus["nodes"].items()
            ]
            locs.sort(key=lambda l: (list(LOCATION_TYPES).index(l["type"]), l["id"]))
            return self._send(200, {"types": LOCATION_TYPES, "locations": locs})

        if path == "/api/graph":
            return self._send(200, STORE.campus_snapshot())

        if path == "/api/weights":
            return self._send(200, STORE.weights_snapshot())

        return self._send(404, {"error": "not found"})

    # -- POST ---------------------------------------------------------------
    def do_POST(self):
        path = urlparse(self.path).path
        body = self._json_body()
        if body is None:
            return self._send(400, {"error": "请求体不是合法 JSON"})

        # 学生端:路线查询
        if path == "/api/route":
            waypoints = body.get("waypoints") or []
            profile_name = body.get("profile", "wheelchair")
            if len(waypoints) < 2:
                return self._send(400, {"error": "至少需要起点和终点两个地点"})
            campus = STORE.campus_snapshot()
            for w in waypoints:
                if w not in campus["nodes"]:
                    return self._send(400, {"error": "未知地点: %s" % w})
            profile = STORE.get_profile(profile_name)
            if profile is None:
                return self._send(400, {"error": "未知出行模式: %s" % profile_name})
            graph = CampusGraph(campus)
            result = build_route(graph, waypoints, profile)
            if result is None:
                return self._send(422, {
                    "error": "在当前出行模式下找不到满足无障碍要求的路线,"
                             "请尝试更换模式或联系管理员完善校园图数据"
                })
            result["profile"] = profile_name
            result["node_names"] = {
                nid: n["name"] for nid, n in campus["nodes"].items()
            }
            return self._send(200, result)

        # 管理端:新增节点
        if path == "/api/admin/nodes":
            parsed, err = validate_node(body)
            if err:
                return self._send(400, {"error": err})
            with STORE.lock:
                if parsed["id"] in STORE.campus["nodes"]:
                    return self._send(409, {"error": "节点 id 已存在"})
                STORE.campus["nodes"][parsed["id"]] = parsed["node"]
                STORE.save_campus()
            return self._send(201, {"ok": True})

        # 管理端:新增边
        if path == "/api/admin/edges":
            parsed, err = validate_edge(body)
            if err:
                return self._send(400, {"error": err})
            with STORE.lock:
                if any(e["id"] == parsed["id"] for e in STORE.campus["edges"]):
                    return self._send(409, {"error": "边 id 已存在"})
                STORE.campus["edges"].append(parsed["edge"])
                STORE.save_campus()
            return self._send(201, {"ok": True})

        return self._send(404, {"error": "not found"})

    # -- PUT ----------------------------------------------------------------
    def do_PUT(self):
        path = urlparse(self.path).path
        body = self._json_body()
        if body is None:
            return self._send(400, {"error": "请求体不是合法 JSON"})

        if path.startswith("/api/admin/nodes/"):
            nid = path.rsplit("/", 1)[-1]
            parsed, err = validate_node(body, node_id=nid)
            if err:
                return self._send(400, {"error": err})
            with STORE.lock:
                if nid not in STORE.campus["nodes"]:
                    return self._send(404, {"error": "节点不存在"})
                STORE.campus["nodes"][nid] = parsed["node"]
                STORE.save_campus()
            return self._send(200, {"ok": True})

        if path.startswith("/api/admin/edges/"):
            eid = path.rsplit("/", 1)[-1]
            parsed, err = validate_edge(body, edge_id=eid)
            if err:
                return self._send(400, {"error": err})
            with STORE.lock:
                for i, e in enumerate(STORE.campus["edges"]):
                    if e["id"] == eid:
                        STORE.campus["edges"][i] = parsed["edge"]
                        STORE.save_campus()
                        return self._send(200, {"ok": True})
            return self._send(404, {"error": "边不存在"})

        if path == "/api/admin/weights":
            err = validate_weights(body)
            if err:
                return self._send(400, {"error": err})
            STORE.replace_weights(body)
            return self._send(200, {"ok": True})

        return self._send(404, {"error": "not found"})

    # -- DELETE -------------------------------------------------------------
    def do_DELETE(self):
        path = urlparse(self.path).path

        if path.startswith("/api/admin/nodes/"):
            nid = path.rsplit("/", 1)[-1]
            with STORE.lock:
                if nid not in STORE.campus["nodes"]:
                    return self._send(404, {"error": "节点不存在"})
                del STORE.campus["nodes"][nid]
                # 级联删除关联边
                STORE.campus["edges"] = [
                    e for e in STORE.campus["edges"]
                    if e["from"] != nid and e["to"] != nid
                ]
                STORE.save_campus()
            return self._send(200, {"ok": True})

        if path.startswith("/api/admin/edges/"):
            eid = path.rsplit("/", 1)[-1]
            with STORE.lock:
                before = len(STORE.campus["edges"])
                STORE.campus["edges"] = [
                    e for e in STORE.campus["edges"] if e["id"] != eid
                ]
                if len(STORE.campus["edges"]) == before:
                    return self._send(404, {"error": "边不存在"})
                STORE.save_campus()
            return self._send(200, {"ok": True})

        return self._send(404, {"error": "not found"})


def main():
    import argparse
    parser = argparse.ArgumentParser(description="高校无障碍路线规划系统")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print("学生端:  http://localhost:%d/" % args.port)
    print("管理端:  http://localhost:%d/admin" % args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
