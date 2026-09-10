# 高校无障碍路线规划系统

为校园内行动不便的师生(轮椅使用者、推婴儿车、拉行李箱等)提供无障碍路线
规划:学生选择宿舍、教学楼、食堂、图书馆等地点,系统**优先避开楼梯和陡坡**,
返回由**电梯、坡道和平缓通道**组成的路线;管理员可在线维护校园图数据与算法权重。

## 功能一览

| 角色 | 功能 |
|------|------|
| 学生 | 选择出发地/目的地/多个途经点(宿舍、教学楼、食堂、图书馆等);两种出行模式;地图高亮路线;逐步骤导航说明;距离/时间/无障碍设施统计 |
| 管理员 | 校园节点(建筑/路口)增删改查;通道(边)增删改查(距离、设施类型、坡度、路面);算法权重在线调整,保存即时生效 |

## 快速开始

零第三方依赖,只需 Python 3.8+:

```bash
cd accessible-campus
python3 server.py            # 默认 8000 端口
# python3 server.py --port 9000
```

- 学生端: http://localhost:8000/
- 管理端: http://localhost:8000/admin (需 Basic Auth)

**管理端访问控制**:`/admin` 页面与全部 `/api/admin/*` 接口均要求 HTTP Basic
Auth(用户名固定 `admin`),密码按以下优先级确定:

1. 启动参数 `--admin-password PWD`
2. 环境变量 `ADMIN_PASSWORD`
3. 两者都未提供时,启动时**随机生成一次性密码**并打印在控制台(重启失效)

```bash
ADMIN_PASSWORD=s3cret python3 server.py
# 或: python3 server.py --admin-password s3cret
# 之后 curl -u admin:s3cret http://localhost:8000/admin
```

学生端页面与查询接口(`/api/route`、`/api/locations`、`/api/graph`、
`/api/weights`)保持公开,无需认证。

运行测试:

```bash
python3 -m unittest discover -s tests -v
```

## 项目结构

```
accessible-campus/
├── server.py            # HTTP 服务 + REST API(仅标准库)
├── router.py            # 图结构 + 权重模型 + Dijkstra 寻路
├── data/
│   ├── campus.json      # 校园图数据(节点 + 边)
│   └── weights.json     # 权重配置(首次运行自动生成,管理员可改)
├── static/              # 学生端 index.html / 管理端 admin.html + CSS/JS
├── tests/
│   ├── test_router.py     # 算法单元测试(11 个用例)
│   └── test_server.py     # 服务端测试:管理端访问控制 + 权重校验
└── docs/weights.md      # ★ 算法权重设置详细说明
```

## 算法与权重(摘要)

边权重 = `距离 × 设施类型倍率 × (1 + 坡度惩罚) × 路面倍率 + 固定成本`,
用 Dijkstra 求最小代价路径;多途经点按顺序分段求解后拼接。

- **楼梯**:轮椅模式禁止通行;一般模式 25 倍距离惩罚
- **陡坡**:按 5% / 8.33% / 12% 分档惩罚;轮椅模式 >12% 禁止通行
- **电梯**:计 30 米等效候梯成本
- **坡道/平缓通道**:基本不惩罚,系统自然优先选择

完整参数说明、设计依据与调参指南见 **[docs/weights.md](docs/weights.md)**。

## API 摘要

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/locations` | 可选地点列表(按类型分组) |
| POST | `/api/route` | 路线查询 `{waypoints:[...], profile:"wheelchair"\|"standard"}` |
| GET | `/api/graph` | 全量校园图数据 |
| GET | `/api/weights` | 当前权重配置 |
| POST/PUT/DELETE | `/api/admin/nodes[/<id>]` | 节点增改删(删节点级联删边),**需 Basic Auth** |
| POST/PUT/DELETE | `/api/admin/edges[/<id>]` | 边增改删,**需 Basic Auth** |
| PUT | `/api/admin/weights` | 整体更新权重配置(严格校验,非法配置返回 400 不落盘),**需 Basic Auth** |

未携带/错误的认证凭据统一返回 `401 Unauthorized` 及 `WWW-Authenticate: Basic`
响应头,浏览器会弹出登录框。

## 校园图数据格式

```json
{
  "nodes": {"dorm_a": {"name": "学生宿舍A栋", "type": "dormitory", "x": 80, "y": 110}},
  "edges": [{"id": "e1", "from": "dorm_a", "to": "p6", "distance": 95,
             "kind": "walkway", "slope": 0.01, "surface": "smooth"}]
}
```

- 节点 `type`:`dormitory / teaching / cafeteria / library / junction`
- 边 `kind`:`walkway(平缓通道)/ ramp(坡道)/ elevator(电梯)/ stairs(楼梯)/ slope_path(坡道)`
- `slope` 为小数(0.08 = 8%);边默认双向,可加 `"oneway": true`

## 说明

- 管理端已内置 HTTP Basic Auth 访问控制(见上文"管理端访问控制");Basic Auth
  仅为简单口令保护,生产部署建议再配合 HTTPS 或在反向代理层接入 SSO。
- 权重保存接口执行严格的结构与数值校验:倍率/惩罚/固定成本必须为有限非负数,
  `speed_mps` 必须为正数,坡度分档必须是 `[上限, 惩罚]` 二元组且上限严格递增
  (`null` 兜底档只能位于最后);非法配置返回 400 且**不写盘**,从源头杜绝坏配置
  导致后续路线查询异常。
- 数据文件为 JSON,修改即落盘;多实例部署可替换为数据库,`DataStore`
  类已隔离全部存取逻辑。
