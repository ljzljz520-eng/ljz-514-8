# 高校无障碍路线规划系统

面向行动不便师生的校园路线规划工具：学生选择宿舍、教学楼、食堂、图书馆等
地点，系统**优先避开楼梯和陡坡**，返回由**电梯、坡道和平缓通道**组成的路线；
管理员负责维护校园图数据。

纯 Python 3.11 标准库实现，零第三方依赖。

## 快速开始

```bash
# 列出可选地点（宿舍/教学楼/食堂/图书馆）
python3 main.py places

# 查询无障碍路线（默认严格无障碍模式）
python3 main.py route --from D1 --to T1

# 优先无障碍模式：允许楼梯/陡坡但重罚，适合对比
python3 main.py route --from D1 --to C1 --mode prefer

# 运行测试
python3 -m unittest discover -s tests -v
```

示例输出（宿舍 → 教学楼，自动选择电梯路线）：

```
路线：一号宿舍楼 → 宿舍前路口 → 教学楼西侧路口 → 教学楼电梯厅 → 第一教学楼

分段指引：
  1. [平缓通道] 一号宿舍楼 → 宿舍前路口，80 米，坡度 1.0%
  ...
  4. [电梯] 教学楼电梯厅 → 第一教学楼，3 米，平均候梯 40 秒

总里程约 245 米，预计用时约 4.2 分钟。
✓ 全程无障碍：仅由平缓通道、坡道和电梯组成，已避开楼梯与陡坡。
```

## 学生端功能

- 从宿舍、教学楼、食堂、图书馆中选择起点和终点；
- 严格无障碍模式（默认）：楼梯与陡坡（坡度 >8%）不可通行，
  路线只由平缓通道、坡道、电梯组成；
- 严格模式无解时自动降级为优先模式兜底，并明确提示"非全程无障碍"；
- 输出分段指引（通道类型、长度、坡度、候梯时间）、总里程与预计用时。

## 管理员功能

```bash
python3 main.py admin list-nodes                 # 查看节点
python3 main.py admin list-edges                 # 查看通道
python3 main.py admin validate                   # 校验图数据

python3 main.py admin add-node --id D2 --name 二号宿舍楼 --kind dorm --x 0 --y 120
python3 main.py admin add-edge --source D2 --target J1 --length 100 \
    --type walkway --slope 2.5 --note 新宿舍通道
python3 main.py admin remove-edge --source D2 --target J1
python3 main.py admin remove-node --id D2
```

通道类型（`--type`）：`walkway` 平缓通道、`ramp` 坡道、`stairs` 楼梯、
`elevator` 电梯；`--slope` 为坡度百分比，`--wait` 为电梯平均候梯秒数。
数据保存在 `data/campus_graph.json`（可用 `--data` 指定其他文件）。

## 项目结构

```
├── main.py                  # 统一入口（places / route / admin）
├── src/
│   ├── models.py            # 图数据模型：Node / Edge / CampusGraph
│   ├── weights.py           # 权重配置 WeightConfig 与边成本计算
│   ├── routing.py           # 加权 Dijkstra 寻路与降级策略
│   ├── graph_io.py          # 校园图 JSON 加载/保存
│   ├── student.py           # 学生端：地点列表、路线格式化
│   └── admin.py             # 管理员端：图数据维护 CLI
├── data/campus_graph.json   # 示例校园图数据
├── docs/algorithm_weights.md# 算法权重设置说明（调参必读）
└── tests/test_routing.py    # 单元测试（unittest，15 例）
```

## 文档

- **算法权重怎么设置**：见 [docs/algorithm_weights.md](docs/algorithm_weights.md)，
  包含成本公式 `cost = 长度 × 类型系数 × 坡度系数 + 固定惩罚`、
  各参数默认值与调参建议。
