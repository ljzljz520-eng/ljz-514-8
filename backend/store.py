"""图数据加载、保存、校验，以及管理员 Token 鉴权。"""
import json
import os
import hashlib
import secrets
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
GRAPH_FILE = os.path.join(DATA_DIR, "graph.json")
DEFAULT_GRAPH_FILE = os.path.join(DATA_DIR, "default_graph.json")
WEIGHTS_FILE = os.path.join(DATA_DIR, "weights.json")
AUTH_FILE = os.path.join(DATA_DIR, "auth.json")

NODE_TYPES = {"entrance", "indoor", "elevator", "stairs", "room", "junction"}
EDGE_TYPES = {"path", "corridor", "ramp", "elevator", "door", "slope", "stairs"}
SURFACES = {"asphalt", "concrete", "brick", "gravel", "cobble"}


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_graph():
    """加载当前校园图；若尚未初始化则从默认数据复制一份。"""
    if not os.path.exists(GRAPH_FILE):
        reset_graph()
    return _read_json(GRAPH_FILE)


def save_graph(graph):
    validate_graph(graph)
    graph.setdefault("meta", {})["version"] = graph.get("meta", {}).get("version", 0) + 1
    _write_json(GRAPH_FILE, graph)


def reset_graph():
    data = _read_json(DEFAULT_GRAPH_FILE)
    _write_json(GRAPH_FILE, data)
    return data


def load_weights():
    return _read_json(WEIGHTS_FILE)


def save_weights(weights):
    _write_json(WEIGHTS_FILE, weights)


# ---------------------------------------------------------------- auth

DEFAULT_ADMIN = {"username": "admin", "password_sha256": None}


def _load_auth():
    if not os.path.exists(AUTH_FILE):
        auth = {
            "admin": {
                "username": "admin",
                # 默认密码 admin123 的 sha256
                "password_sha256": hashlib.sha256(b"admin123").hexdigest(),
            },
            "tokens": {},
        }
        _write_json(AUTH_FILE, auth)
    return _read_json(AUTH_FILE)


def login(username, password):
    auth = _load_auth()
    admin = auth.get("admin", {})
    pwd_hash = hashlib.sha256((password or "").encode("utf-8")).hexdigest()
    if username == admin.get("username") and pwd_hash == admin.get("password_sha256"):
        token = secrets.token_hex(24)
        auth["tokens"][token] = {"issued_at": int(time.time())}
        _write_json(AUTH_FILE, auth)
        return token
    return None


def check_token(token):
    if not token:
        return False
    auth = _load_auth()
    return token in auth.get("tokens", {})


def logout(token):
    auth = _load_auth()
    if token in auth.get("tokens", {}):
        del auth["tokens"][token]
        _write_json(AUTH_FILE, auth)
        return True
    return False


def change_password(old, new):
    auth = _load_auth()
    admin = auth.get("admin", {})
    old_hash = hashlib.sha256((old or "").encode("utf-8")).hexdigest()
    if admin.get("password_sha256") != old_hash:
        return False
    if not new or len(new) < 6:
        raise ValueError("新密码至少 6 位")
    auth["admin"]["password_sha256"] = hashlib.sha256(new.encode("utf-8")).hexdigest()
    _write_json(AUTH_FILE, auth)
    return True


# ------------------------------------------------------------- validate

def validate_graph(graph):
    if not isinstance(graph, dict) or "nodes" not in graph or "edges" not in graph:
        raise ValueError("图数据必须包含 nodes 与 edges 数组")
    node_ids = set()
    for n in graph["nodes"]:
        nid = n.get("id")
        if not nid:
            raise ValueError("节点缺少 id")
        if nid in node_ids:
            raise ValueError(f"节点 id 重复: {nid}")
        node_ids.add(nid)
        if n.get("type") not in NODE_TYPES:
            raise ValueError(f"节点 {nid} 的 type 非法: {n.get('type')}")
        if "x" not in n or "y" not in n:
            raise ValueError(f"节点 {nid} 缺少坐标 x/y")
        n.setdefault("floor", 0)
    edge_ids = set()
    for e in graph["edges"]:
        eid = e.get("id")
        if not eid:
            raise ValueError("边缺少 id")
        if eid in edge_ids:
            raise ValueError(f"边 id 重复: {eid}")
        edge_ids.add(eid)
        if e.get("a") not in node_ids or e.get("b") not in node_ids:
            raise ValueError(f"边 {eid} 的端点不存在")
        if e.get("type") not in EDGE_TYPES:
            raise ValueError(f"边 {eid} 的 type 非法: {e.get('type')}")
        if e.get("surface") and e["surface"] not in SURFACES:
            raise ValueError(f"边 {eid} 的 surface 非法: {e['surface']}")
    return True
