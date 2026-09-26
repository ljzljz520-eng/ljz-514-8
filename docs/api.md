# HTTP API 文档

所有接口返回 JSON，成功包含 `"ok": true`，失败为 `"ok": false, "error": "..."`。
写操作（`/api/admin/*` 的 POST/DELETE）需要管理员 Token，请求头携带：

```
Authorization: Bearer <token>
```

## 公开接口（学生端）

### GET /api/pois
返回可作为起终点的地点列表（room / entrance / indoor 类型节点）。

```json
{ "ok": true,
  "pois": [{"id": "dorm_room", "name": "宿舍 305", "type": "room",
            "building": "dorm", "building_label": "宿舍",
            "x": 80, "y": 130, "floor": 3}],
  "buildings": {"dorm": "宿舍", "teach": "教学楼", "canteen": "食堂", "library": "图书馆"} }
```

### GET /api/graph
返回完整校园图（nodes + edges + meta），供前端 SVG 渲染。

### GET /api/route?start=ID&goal=ID&mode=accessible|regular
规划路线。`mode` 省略时为 `accessible`。

返回字段：

| 字段 | 说明 |
|---|---|
| `route.weight` | 综合权重（越低越优） |
| `route.distance_m` | 物理长度（米） |
| `route.duration_min` | 预计用时（分钟） |
| `route.stairs_segments` | 途经台阶段数（无障碍模式应为 0） |
| `route.steep_segments` | 途经陡坡道数（无障碍模式应为 0） |
| `route.elevator_segments` | 乘用电梯段数 |
| `route.edge_ids` / `node_ids` | 有序路径，供地图高亮 |
| `route.warnings` | 风险提示（超规坡道、窄门等） |
| `route.instructions` | 分步文字指引（含图标类型） |
| `regular_comparison` | 无障碍模式下附带的普通步行路线对比 |

### GET /api/weights
返回当前权重配置（与 `data/weights.json` 一致）。

## 管理员接口

### POST /api/admin/login
请求：`{"username": "admin", "password": "admin123"}`
成功：`{"ok": true, "token": "..."}`（Token 保存在服务端 `data/auth.json`）。
默认账号 `admin / admin123`。

### POST /api/admin/logout
注销当前 Token。

### POST /api/admin/node
新增或更新节点（按 id 幂等：id 已存在则更新）。

```json
{"node": {"id": "new_gate", "name": "校园东南门", "type": "entrance",
          "building": null, "x": 880, "y": 450, "floor": 0}}
```

节点 `type` 取值：`entrance | indoor | room | elevator | stairs | junction`。
服务端校验：id 唯一、type 合法、坐标齐全；边引用的端点必须存在。

### DELETE /api/admin/node?id=xxx
删除节点，**并级联删除与它相连的所有边**。

### POST /api/admin/edge
新增或更新通道（按 id 幂等）。

```json
{"edge": {"id": "e200", "a": "new_gate", "b": "j_south_mid",
          "type": "ramp", "length": 42.0, "grade": 0.07, "width_m": 1.5,
          "surface": "asphalt", "tactile": true, "blocked": false}}
```

边字段说明：

| 字段 | 适用类型 | 说明 |
|---|---|---|
| `type` | 全部 | `path/corridor/ramp/slope/stairs/elevator/door` |
| `length` | 平路/坡道等 | 米；省略时按节点坐标自动估算 |
| `grade` | ramp/slope | 坡度（升高/水平距），合规坡道 ≤ 0.083 |
| `width_m` | path/ramp/door | 净宽（米），低于阈值产生惩罚 |
| `surface` | path/slope/ramp | `asphalt/concrete/brick/gravel/cobble` |
| `stair_count` | stairs | 台阶级数 |
| `floors` | stairs/elevator | 跨越楼层数 |
| `tactile` | path | 沿线有盲道 |
| `has_elevator` | elevator | 是否有可用电梯 |
| `heavy` | door | 沉重/回弹门 |
| `blocked` | 全部 | 施工封闭，寻路时以极大代价避开 |

### DELETE /api/admin/edge?id=xxx
删除一条边。

### POST /api/admin/weights
整体覆盖权重配置：`{"weights": { ... 与 /api/weights 同结构 ... }}`。
保存后下一次寻路立即生效。

### POST /api/admin/reset
放弃全部图数据改动，恢复 `data/default_graph.json`。

## 错误约定

| HTTP 状态 | 场景 |
|---|---|
| 400 | 参数缺失 / JSON 非法 / 图数据校验失败（错误信息中文说明原因） |
| 401 | 未登录或 Token 失效 |
| 404 | 接口或资源不存在 |
| 500 | 服务端内部错误 |
