"""端到端冒烟测试：启动服务后执行 `python3 tests/smoke_test.py [base_url]`。"""
import json
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
PASS, FAIL = 0, 0


def call(method, path, body=None, token=None):
    req = urllib.request.Request(BASE + path, method=method)
    if body is not None:
        req.data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {extra}")


print("== 公开数据 ==")
s, r = call("GET", "/api/pois")
check("GET /api/pois", s == 200 and len(r["pois"]) >= 12)
s, r = call("GET", "/api/graph")
check("GET /api/graph 含四类建筑节点",
      {"dorm", "teach", "canteen", "library"} <= {n.get("building") for n in r["graph"]["nodes"] if n.get("building")})

print("== 无障碍路线：避开楼梯和陡坡 ==")
s, r = call("GET", "/api/route?start=dorm_room&goal=lib_read&mode=accessible")
rt = r["route"]
check("请求成功", r["ok"])
check("0 段台阶", rt["stairs_segments"] == 0, str(rt["stairs_segments"]))
check("0 段陡坡", rt["steep_segments"] == 0, str(rt["steep_segments"]))
check("使用了电梯", rt["elevator_segments"] >= 2, str(rt["elevator_segments"]))
check("走 7% 坡道 e61 而非 13% 陡坡 e60", "e61" in rt["edge_ids"] and "e60" not in rt["edge_ids"])
check("走图书馆南门坡道 e65 而非北门台阶 e64", "e65" in rt["edge_ids"] and "e64" not in rt["edge_ids"])
check("有分步指引", len(rt["instructions"]) >= 5)

print("== 普通步行对比：允许台阶 ==")
cmp = r["regular_comparison"]
check("返回对比路线", cmp is not None)
check("普通路线含台阶", cmp["stairs_segments"] >= 1, str(cmp and cmp["stairs_segments"]))

print("== 参数校验 ==")
s, r = call("GET", "/api/route?start=&goal=x")
check("缺少起点返回 400", s == 400)
s, r = call("POST", "/api/admin/node", {"node": {"id": "h"}})
check("未登录写操作返回 401", s == 401)

print("== 管理员增删改 ==")
s, r = call("POST", "/api/admin/login", {"username": "admin", "password": "admin123"})
check("管理员登录", r["ok"])
token = r.get("token")
s, r = call("POST", "/api/admin/node", {"node": {
    "id": "smoke_n", "name": "冒烟测试点", "type": "junction", "x": 450, "y": 350}}, token)
check("新增节点", r["ok"])
s, r = call("POST", "/api/admin/edge", {"edge": {
    "id": "smoke_e", "a": "smoke_n", "b": "j_south", "type": "ramp",
    "grade": 0.06, "width_m": 1.5, "tactile": True}}, token)
check("新增坡道", r["ok"])
s, r = call("POST", "/api/admin/edge", {"edge": {
    "id": "smoke_bad", "a": "smoke_n", "b": "no_such", "type": "path"}}, token)
check("悬空端点被拒绝", not r["ok"] and "端点" in r["error"])
s, r = call("DELETE", "/api/admin/edge?id=smoke_e", token=token)
check("删除边", r["ok"])
s, r = call("DELETE", "/api/admin/node?id=smoke_n", token=token)
check("删除节点(级联)", r["ok"])
s, r = call("POST", "/api/admin/reset", token=token)
check("恢复默认图", r["ok"])
s, r = call("POST", "/api/admin/logout", token=token)
check("注销", r["ok"])

print(f"\n结果: {PASS} 通过, {FAIL} 失败")
sys.exit(1 if FAIL else 0)
