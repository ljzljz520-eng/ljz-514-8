# -*- coding: utf-8 -*-
"""服务端测试: 管理端访问控制(Basic Auth)+ 权重配置校验。

python3 -m unittest discover -s tests -v
"""
import base64
import copy
import json
import os
import sys
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import server
from router import DEFAULT_WEIGHTS

TEST_PASSWORD = "test-secret-123"


def _request(method, path, body=None, auth=None, port=None):
    url = "http://127.0.0.1:%d%s" % (port, path)
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if auth is not None:
        token = base64.b64encode((":".join(auth)).encode("utf-8")).decode()
        headers["Authorization"] = "Basic " + token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("utf-8")
            parsed = json.loads(raw) if "application/json" in resp.headers.get(
                "Content-Type", "") else raw
            return resp.status, parsed, resp.headers
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        parsed = json.loads(raw) if "application/json" in e.headers.get(
            "Content-Type", "") else raw
        return e.code, parsed, e.headers


def _mutate(fn):
    d = copy.deepcopy(DEFAULT_WEIGHTS)
    fn(d)
    return d


class TestValidateWeights(unittest.TestCase):
    """权重配置在保存入口被严格校验,杜绝坏配置落盘后在路线查询时炸掉。"""

    def test_default_and_disk_config_valid(self):
        self.assertIsNone(server.validate_weights(copy.deepcopy(DEFAULT_WEIGHTS)))
        with open(os.path.join(os.path.dirname(__file__), "..", "data",
                               "weights.json"), encoding="utf-8") as f:
            self.assertIsNone(server.validate_weights(json.load(f)))

    def test_missing_or_wrong_shaped_profiles(self):
        for payload in (
            {}, {"profiles": []}, {"profiles": {}},
            {"profiles": "x"}, [], "x",
        ):
            with self.subTest(payload=payload):
                self.assertIsNotNone(server.validate_weights(payload))

    def test_non_numeric_multiplier_rejected(self):
        p = _mutate(lambda d: d["profiles"]["wheelchair"]["type_multiplier"]
                    .__setitem__("walkway", "abc"))
        self.assertIn("数字", server.validate_weights(p))

    def test_empty_slope_tier_rejected(self):
        p = _mutate(lambda d: d["profiles"]["wheelchair"]["slope_penalties"]
                    .__setitem__(0, []))
        self.assertIn("格式错误", server.validate_weights(p))

    def test_negative_fixed_cost_rejected(self):
        p = _mutate(lambda d: d["profiles"]["wheelchair"]
                    .update(elevator_fixed_cost=-100))
        self.assertIn("不能为负数", server.validate_weights(p))

    def test_missing_required_fields_rejected(self):
        def drop(field, root=None):
            def fn(d):
                obj = d["profiles"]["wheelchair"] if root is None else root(d)
                obj.pop(field)
            return fn
        for fn in (drop("type_multiplier"), drop("slope_penalties"),
                   drop("surface_multiplier"), drop("elevator_fixed_cost"),
                   drop("speed_mps"), drop("slope_hard_limit")):
            self.assertIsNotNone(server.validate_weights(_mutate(fn)))

    def test_invalid_numbers_rejected(self):
        w = _mutate(lambda d: d["profiles"]["wheelchair"]["type_multiplier"]
                    .__setitem__("ramp", float("nan")))
        self.assertIn("有限", server.validate_weights(w))
        w = _mutate(lambda d: d["profiles"]["wheelchair"]["type_multiplier"]
                    .__setitem__("ramp", True))  # bool 不得冒充数字
        self.assertIn("数字", server.validate_weights(w))
        w = _mutate(lambda d: d["profiles"]["wheelchair"].update(speed_mps=0))
        self.assertIn("大于 0", server.validate_weights(w))

    def test_slope_tier_order_and_null_position(self):
        w = _mutate(lambda d: d["profiles"]["wheelchair"]["slope_penalties"]
                    .__setitem__(1, [0.04, 2.0]))  # 上限不递增
        self.assertIn("递增", server.validate_weights(w))
        w = _mutate(lambda d: d["profiles"]["wheelchair"]["slope_penalties"]
                    .__setitem__(1, [None, 2.0]))  # null 不在最后
        self.assertIn("最后一档", server.validate_weights(w))

    def test_null_multiplier_still_allowed(self):
        # null = 禁行,是合法语义
        w = copy.deepcopy(DEFAULT_WEIGHTS)
        w["profiles"]["standard"]["type_multiplier"]["stairs"] = None
        self.assertIsNone(server.validate_weights(w))


class TestServerHTTP(unittest.TestCase):
    """真实 HTTP 层:管理端页面与 /api/admin/* 必须通过 Basic Auth。"""

    @classmethod
    def setUpClass(cls):
        # 测试使用临时目录的数据,绝不覆盖仓库中的 data/*.json。
        # 模块导入时 STORE 已按仓库真实 data/ 路径创建,这里改路径后重建。
        import tempfile
        cls._tmp = tempfile.TemporaryDirectory()
        cls._old_paths = (server.CAMPUS_FILE, server.WEIGHTS_FILE, server.STORE)
        server.CAMPUS_FILE = os.path.join(cls._tmp.name, "campus.json")
        server.WEIGHTS_FILE = os.path.join(cls._tmp.name, "weights.json")
        src = os.path.join(os.path.dirname(__file__), "..", "data", "campus.json")
        with open(src, "rb") as f:
            with open(server.CAMPUS_FILE, "wb") as g:
                g.write(f.read())
        server.STORE = server.DataStore()
        cls._srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls._srv.server_address[1]
        cls._thread = threading.Thread(target=cls._srv.serve_forever, daemon=True)
        cls._thread.start()
        cls._old_pw = server.ADMIN_PASSWORD
        server.ADMIN_PASSWORD = TEST_PASSWORD

    @classmethod
    def tearDownClass(cls):
        cls._srv.shutdown()
        cls._srv.server_close()
        cls._thread.join(timeout=5)
        server.ADMIN_PASSWORD = cls._old_pw
        server.CAMPUS_FILE, server.WEIGHTS_FILE, server.STORE = cls._old_paths
        cls._tmp.cleanup()

    def req(self, method, path, body=None, auth=None):
        return _request(method, path, body, auth, self.port)

    # -- 访问控制 -----------------------------------------------------------
    def test_student_pages_and_apis_open(self):
        for method, path in (("GET", "/"), ("GET", "/static/js/admin.js"),
                             ("GET", "/api/locations"), ("GET", "/api/graph"),
                             ("GET", "/api/weights")):
            code, _, _ = self.req(method, path)
            self.assertEqual(code, 200, path)

    def test_admin_page_requires_auth(self):
        code, _, headers = self.req("GET", "/admin")
        self.assertEqual(code, 401)
        self.assertTrue(headers.get("WWW-Authenticate", "").startswith("Basic"))

    def test_admin_apis_requires_auth(self):
        cases = [
            ("POST", "/api/admin/nodes", {"id": "x", "name": "X",
                                          "type": "junction", "x": 0, "y": 0}),
            ("PUT", "/api/admin/weights", DEFAULT_WEIGHTS),
            ("DELETE", "/api/admin/nodes/nope", None),
            ("POST", "/api/admin/edges", {"id": "ex", "from": "dorm_a",
                                          "to": "lib", "distance": 10}),
        ]
        for method, path, body in cases:
            code, _, headers = self.req(method, path, body)
            self.assertEqual(code, 401, path)
            self.assertIn("WWW-Authenticate", headers)

    def test_wrong_credentials_rejected(self):
        code, _, _ = self.req("GET", "/admin",
                              auth=("admin", "wrong-password"))
        self.assertEqual(code, 401)
        code, _, _ = self.req("GET", "/admin",
                              auth=("hacker", TEST_PASSWORD))
        self.assertEqual(code, 401)

    def test_correct_credentials_accepted(self):
        code, body, _ = self.req("GET", "/admin", auth=("admin", TEST_PASSWORD))
        self.assertEqual(code, 200)
        self.assertIn("校园图数据管理", body)

    def test_no_password_configured_fail_closed(self):
        old = server.ADMIN_PASSWORD
        server.ADMIN_PASSWORD = None
        try:
            code, _, headers = self.req("GET", "/admin")
            # 没有配置密码时一律拒绝(401 或 503 都算不放行)
            self.assertIn(code, (401, 503))
            if code == 401:
                self.assertIn("WWW-Authenticate", headers)
        finally:
            server.ADMIN_PASSWORD = old

    # -- 权重保存校验(端到端) ----------------------------------------------
    def test_bad_weights_rejected_not_persisted(self):
        before = server.STORE.weights_snapshot()
        bad = _mutate(lambda d: d["profiles"]["wheelchair"]["slope_penalties"]
                      .__setitem__(0, []))
        code, body, _ = self.req("PUT", "/api/admin/weights", bad,
                                 auth=("admin", TEST_PASSWORD))
        self.assertEqual(code, 400)
        self.assertIn("格式错误", body["error"])
        self.assertEqual(before, server.STORE.weights_snapshot())

    def test_bad_weights_without_auth_does_not_leak_validation(self):
        bad = _mutate(lambda d: d["profiles"]["wheelchair"]["slope_penalties"]
                      .__setitem__(0, []))
        code, _, _ = self.req("PUT", "/api/admin/weights", bad)
        self.assertEqual(code, 401)

    def test_valid_weights_persisted_and_route_still_works(self):
        good = copy.deepcopy(DEFAULT_WEIGHTS)
        good["profiles"]["wheelchair"]["elevator_fixed_cost"] = 45.0
        code, _, _ = self.req("PUT", "/api/admin/weights", good,
                              auth=("admin", TEST_PASSWORD))
        self.assertEqual(code, 200)
        self.assertEqual(server.STORE.weights_snapshot(), good)

        # 保存合法配置后路线查询正常
        code, body, _ = self.req("POST", "/api/route",
                                 {"waypoints": ["dorm_a", "lib"],
                                  "profile": "wheelchair"})
        self.assertEqual(code, 200)
        self.assertIn("path", body)
        # 还原默认配置
        code, _, _ = self.req("PUT", "/api/admin/weights",
                              copy.deepcopy(DEFAULT_WEIGHTS),
                              auth=("admin", TEST_PASSWORD))
        self.assertEqual(code, 200)


if __name__ == "__main__":
    unittest.main()
