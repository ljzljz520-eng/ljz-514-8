#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高校无障碍路线规划系统 —— 后端服务
仅依赖 Python 标准库,直接运行:  python3 server.py [--port 8000] [--admin-password PWD]

学生端:  http://localhost:8000/
管理端:  http://localhost:8000/admin   (HTTP Basic Auth)

管理端(/admin 页面与 /api/admin/* 接口)启用 Basic Auth 访问控制:
  - 通过 --admin-password 或环境变量 ADMIN_PASSWORD 指定密码(用户名固定 admin);
  - 均未提供时,启动时随机生成一次性密码并打印到控制台;
  - 程序内部未配置密码时管理端一律拒绝访问(fail-closed)。
"""

import base64
import copy
import hmac
import json
import math
import os
import secrets
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

# 管理端访问控制:启动时由 main() 注入。未设置密码时管理端不可访问(fail-closed)。
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = None  # 优先读 --admin-password,其次环境变量 ADMIN_PASSWORD

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


def _finite_number(value, name, *, non_negative=True, positive=False):
    """校验 value 是有限实数(拒绝 bool/NaN/Infinity);非法时返回 (None, 错误信息)。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, "%s 必须是数字" % name
    value = float(value)
    if not math.isfinite(value):
        return None, "%s 必须是有限数字" % name
    if positive and value <= 0:
        return None, "%s 必须大于 0" % name
    elif non_negative and value < 0:
        return None, "%s 不能为负数" % name
    return value, None


def validate_weights(data):
    """严格校验整体重配置,任何不合法配置都拒绝保存(返回错误信息)。

    保证:通过校验的配置可被 router.normalize_profile 安全解析,且所有
    倍率/惩罚/成本非负,不会破坏 Dijkstra 的非负权前提。
    """
    if not isinstance(data, dict):
        return "权重配置必须是 JSON 对象"
    profiles = data.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        return "权重配置必须包含非空的 profiles 对象"

    for name, p in profiles.items():
        if not isinstance(name, str) or not name.strip():
            return "存在非法的 profile 名称"
        if not isinstance(p, dict):
            return "profile %s 必须是对象" % name
        prefix = "profile %s 的" % name

        # 1) 设施类型倍率:五种设施必须齐全,值为非负数或 null(null=禁行)
        tm = p.get("type_multiplier")
        if not isinstance(tm, dict):
            return "%s type_multiplier 必须是对象" % prefix
        if not tm:
            return "%s type_multiplier 不能为空" % prefix
        for kind in EDGE_KINDS:
            if kind not in tm:
                return "%s type_multiplier 缺少设施类型 %s" % (prefix, kind)
        for kind, mult in tm.items():
            if kind not in EDGE_KINDS:
                return "%s type_multiplier 含未知设施类型 %s" % (prefix, kind)
            if mult is None:
                continue
            _, err = _finite_number(mult, "%s 设施 %s 的倍率" % (prefix, kind))
            if err:
                return err

        # 2) 坡度分档:至少一档;每档为 [上限, 惩罚],上限递增,null 只能在最后
        tiers = p.get("slope_penalties")
        if not isinstance(tiers, list) or not tiers:
            return "%s slope_penalties 必须是非空列表" % prefix
        prev_limit = None
        for i, tier in enumerate(tiers):
            if not isinstance(tier, (list, tuple)) or len(tier) != 2:
                return "%s 坡度分档第 %d 档格式错误,应为 [坡度上限, 惩罚系数]" % (prefix, i + 1)
            limit, pen = tier
            last = (i == len(tiers) - 1)
            if limit is None:
                if not last:
                    return "%s 坡度分档的 null(兜底档)只能位于最后一档" % prefix
            else:
                lv, err = _finite_number(
                    limit, "%s 坡度分档第 %d 档上限" % (prefix, i + 1))
                if err:
                    return err
                if prev_limit is not None and lv <= prev_limit:
                    return "%s 坡度分档上限必须严格递增" % prefix
                prev_limit = lv
            _, err = _finite_number(
                pen, "%s 坡度分档第 %d 档惩罚系数" % (prefix, i + 1))
            if err:
                return err

        # 3) 坡度硬上限:null(不限)或 0~0.5 的数字
        if "slope_hard_limit" not in p:
            return "%s 缺少 slope_hard_limit(不限请显式设为 null)" % prefix
        hard = p["slope_hard_limit"]
        if hard is not None:
            hv, err = _finite_number(hard, "%s slope_hard_limit" % prefix)
            if err:
                return err
            if hv > 0.5:
                return "%s slope_hard_limit 不能超过 0.5(50%%)" % prefix

        # 4) 路面倍率:两种路面必须齐全,必须为非负数字(null 不允许)
        sm = p.get("surface_multiplier")
        if not isinstance(sm, dict):
            return "%s surface_multiplier 必须是对象" % prefix
        for s in SURFACES:
            if s not in sm:
                return "%s surface_multiplier 缺少路面类型 %s" % (prefix, s)
        for s, mult in sm.items():
            if s not in SURFACES:
                return "%s surface_multiplier 含未知路面类型 %s" % (prefix, s)
            _, err = _finite_number(mult, "%s 路面 %s 的倍率" % (prefix, s))
            if err:
                return err

        # 5) 电梯固定成本:非负数字
        if "elevator_fixed_cost" not in p:
            return "%s 缺少 elevator_fixed_cost" % prefix
        _, err = _finite_number(
            p["elevator_fixed_cost"], "%s elevator_fixed_cost" % prefix)
        if err:
            return err

        # 6) 速度:必须为正数(预计耗时要做除数)
        if "speed_mps" not in p:
            return "%s 缺少 speed_mps" % prefix
        _, err = _finite_number(
            p["speed_mps"], "%s speed_mps" % prefix, positive=True)
        if err:
            return err

        # 标签/描述为可选字符串
        for key in ("label", "description"):
            if key in p and not isinstance(p[key], str):
                return "%s %s 必须是字符串" % (prefix, key)

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

    # -- 管理端访问控制 -----------------------------------------------------
    def _require_admin(self):
        """校验 HTTP Basic Auth;未通过则发送 401 并返回 False。

        未配置管理员密码时一律拒绝(fail-closed),避免误配置导致管理端裸奔。
        """
        if not ADMIN_PASSWORD:
            self._send(503, {"error": "服务未启用管理功能"})
            return False
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return self._ask_auth()
        try:
            decoded = base64.b64decode(header[6:].strip()).decode("utf-8")
            username, password = decoded.split(":", 1)
        except (ValueError, UnicodeDecodeError):
            return self._ask_auth()
        # 常量时间比较,防止计时侧信道
        ok_user = hmac.compare_digest(username, ADMIN_USERNAME)
        ok_pass = hmac.compare_digest(password, ADMIN_PASSWORD)
        if not (ok_user and ok_pass):
            return self._ask_auth()
        return True

    def _ask_auth(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate",
                         'Basic realm="Accessible Campus Admin", charset="UTF-8"')
        self.send_header("Content-Type", "application/json; charset=utf-8")
        body = json.dumps({"error": "需要管理员认证"}, ensure_ascii=False).encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return False

    # -- GET ----------------------------------------------------------------
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/admin":
            if not self._require_admin():
                return
            return self._serve_static(path)
        if path == "/" or path.startswith("/static/"):
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
        if path.startswith("/api/admin/") and not self._require_admin():
            return
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
            try:
                profile = STORE.get_profile(profile_name)
            except (TypeError, ValueError):
                profile = None
            if profile is None:
                return self._send(400, {"error": "未知或配置损坏的出行模式: %s"
                                               % profile_name})
            graph = CampusGraph(campus)
            try:
                result = build_route(graph, waypoints, profile)
            except (TypeError, ValueError, ZeroDivisionError, KeyError) as exc:
                return self._send(500, {"error": "权重配置异常导致路线计算失败,"
                                                 "请联系管理员检查权重设置: %s" % exc})
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
        if path.startswith("/api/admin/") and not self._require_admin():
            return
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
        if path.startswith("/api/admin/") and not self._require_admin():
            return

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
    global ADMIN_PASSWORD
    parser = argparse.ArgumentParser(description="高校无障碍路线规划系统")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--admin-password",
                        default=os.environ.get("ADMIN_PASSWORD"),
                        help="管理端密码(默认读环境变量 ADMIN_PASSWORD;"
                             "均未提供则启动时随机生成并打印)")
    args = parser.parse_args()

    # 管理端必须有访问控制:未显式配置时随机生成一次性密码,避免裸奔
    ADMIN_PASSWORD = args.admin_password or secrets.token_urlsafe(12)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print("学生端:  http://localhost:%d/" % args.port)
    print("管理端:  http://localhost:%d/admin" % args.port)
    print("管理账号: %s (用户名固定;%s)" % (
        ADMIN_USERNAME,
        "密码来自 --admin-password / ADMIN_PASSWORD" if args.admin_password
        else "本次启动随机生成密码如下,重启后失效"))
    if not args.admin_password:
        print("管理密码: %s" % ADMIN_PASSWORD)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
