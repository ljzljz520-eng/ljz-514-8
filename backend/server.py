"""高校无障碍路线规划 —— HTTP 服务（仅使用 Python 标准库）。

启动: python3 server.py [--port 8000]
学生端: http://localhost:8000/
管理端: http://localhost:8000/admin.html  (默认账号 admin / admin123)
"""
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import store
import router

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "frontend"))

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}

BUILDING_LABEL = {
    "dorm": "宿舍", "teach": "教学楼", "canteen": "食堂", "library": "图书馆",
}


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "AccessibleCampus/1.0"

    # ---------------------------------------------------------- helpers
    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            raise ValueError("请求体不是合法 JSON")

    def _token(self):
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:].strip()
        return self.headers.get("X-Admin-Token", "").strip()

    def _require_admin(self):
        if not store.check_token(self._token()):
            self._send_json({"ok": False, "error": "未登录或登录已过期"}, 401)
            return False
        return True

    def log_message(self, fmt, *args):
        pass  # 静默；需要调试可打开下一行
        # super().log_message(fmt, *args)

    # ------------------------------------------------------------- GET
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        try:
            if path.startswith("/api/"):
                return self._handle_api_get(path)
            return self._serve_static(path)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"ok": False, "error": f"服务器错误: {exc}"}, 500)

    def _handle_api_get(self, path):
        if path == "/api/graph":
            g = store.load_graph()
            g.pop("_node_index", None)
            return self._send_json({"ok": True, "graph": g})
        if path == "/api/pois":
            g = store.load_graph()
            pois = [
                {"id": n["id"], "name": n["name"], "type": n["type"],
                 "building": n.get("building"),
                 "building_label": BUILDING_LABEL.get(n.get("building"), ""),
                 "x": n["x"], "y": n["y"], "floor": n.get("floor", 0)}
                for n in g["nodes"] if n["type"] in ("room", "entrance", "indoor")
            ]
            return self._send_json({"ok": True, "pois": pois,
                                    "buildings": BUILDING_LABEL})
        if path == "/api/weights":
            return self._send_json({"ok": True, "weights": store.load_weights()})
        if path == "/api/route":
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            start = q.get("start", [""])[0]
            goal = q.get("goal", [""])[0]
            mode = q.get("mode", ["accessible"])[0]
            if mode not in ("accessible", "regular"):
                return self._send_json({"ok": False, "error": "mode 非法"}, 400)
            if not start or not goal:
                return self._send_json({"ok": False, "error": "缺少起点或终点"}, 400)
            return self._send_json(router.find_route(start, goal, mode))
        self._send_json({"ok": False, "error": "接口不存在"}, 404)

    # ------------------------------------------------------------ POST
    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            body = self._read_body()
            if path == "/api/admin/login":
                token = store.login(body.get("username", ""), body.get("password", ""))
                if not token:
                    return self._send_json({"ok": False, "error": "用户名或密码错误"}, 401)
                return self._send_json({"ok": True, "token": token})
            if path == "/api/admin/logout":
                store.logout(self._token())
                return self._send_json({"ok": True})
            if not self._require_admin():
                return
            if path == "/api/admin/node":
                return self._upsert_node(body)
            if path == "/api/admin/edge":
                return self._upsert_edge(body)
            if path == "/api/admin/weights":
                store.save_weights(body.get("weights", body))
                return self._send_json({"ok": True})
            if path == "/api/admin/reset":
                store.reset_graph()
                return self._send_json({"ok": True})
            self._send_json({"ok": False, "error": "接口不存在"}, 404)
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"ok": False, "error": f"服务器错误: {exc}"}, 500)

    # ------------------------------------------------------------- PUT/DELETE
    def do_DELETE(self):
        path = self.path.split("?", 1)[0]
        try:
            if not self._require_admin():
                return
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            graph = store.load_graph()
            if path == "/api/admin/node":
                nid = q.get("id", [""])[0]
                graph["edges"] = [e for e in graph["edges"]
                                  if e["a"] != nid and e["b"] != nid]
                graph["nodes"] = [n for n in graph["nodes"] if n["id"] != nid]
                store.save_graph(graph)
                return self._send_json({"ok": True})
            if path == "/api/admin/edge":
                eid = q.get("id", [""])[0]
                graph["edges"] = [e for e in graph["edges"] if e["id"] != eid]
                store.save_graph(graph)
                return self._send_json({"ok": True})
            self._send_json({"ok": False, "error": "接口不存在"}, 404)
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, 400)

    # ---------------------------------------------------- admin mutations
    def _upsert_node(self, body):
        n = body.get("node", body)
        for key in ("id", "name", "type", "x", "y"):
            if key not in n:
                raise ValueError(f"节点缺少字段: {key}")
        n["x"] = float(n["x"]); n["y"] = float(n["y"])
        n["floor"] = int(n.get("floor", 0) or 0)
        graph = store.load_graph()
        for i, existing in enumerate(graph["nodes"]):
            if existing["id"] == n["id"]:
                graph["nodes"][i] = n
                store.save_graph(graph)
                return self._send_json({"ok": True, "node": n})
        graph["nodes"].append(n)
        store.save_graph(graph)
        return self._send_json({"ok": True, "node": n})

    def _upsert_edge(self, body):
        e = body.get("edge", body)
        for key in ("id", "a", "b", "type"):
            if key not in e:
                raise ValueError(f"边缺少字段: {key}")
        for num_field in ("length", "grade", "width_m"):
            if e.get(num_field) not in (None, ""):
                e[num_field] = float(e[num_field])
        for int_field in ("floors", "stair_count"):
            if e.get(int_field) not in (None, ""):
                e[int_field] = int(e[int_field])
        for bool_field in ("tactile", "has_elevator", "blocked", "heavy"):
            if bool_field in e:
                e[bool_field] = bool(e[bool_field])
        graph = store.load_graph()
        for i, existing in enumerate(graph["edges"]):
            if existing["id"] == e["id"]:
                graph["edges"][i] = e
                store.save_graph(graph)
                return self._send_json({"ok": True, "edge": e})
        graph["edges"].append(e)
        store.save_graph(graph)
        return self._send_json({"ok": True, "edge": e})

    # -------------------------------------------------------- static files
    def _serve_static(self, path):
        if path == "/":
            path = "/index.html"
        # 防目录穿越
        rel = os.path.normpath(os.path.join(FRONTEND_DIR, path.lstrip("/")))
        if not rel.startswith(FRONTEND_DIR) or not os.path.isfile(rel):
            self.send_error(404, "Not Found")
            return
        ext = os.path.splitext(rel)[1]
        body = open(rel, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    store.load_graph()  # 首次启动初始化数据
    httpd = ThreadingHTTPServer((args.host, args.port), ApiHandler)
    print(f"高校无障碍路线规划服务已启动: http://localhost:{args.port}")
    print(f"管理端: http://localhost:{args.port}/admin.html (admin / admin123)")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
