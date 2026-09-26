"""无障碍路线规划系统测试（标准库 unittest，零依赖）。"""
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.graph_io import DEFAULT_DATA, load_graph, save_graph
from src.models import CampusGraph, Edge, EdgeType, Node
from src.routing import _dijkstra, plan_route
from src.weights import WeightConfig, edge_cost


class RoutingTest(unittest.TestCase):
    """基于示例校园图的端到端寻路行为。"""

    @classmethod
    def setUpClass(cls):
        cls.graph = load_graph(DEFAULT_DATA)

    def test_strict_avoids_stairs(self):
        r = plan_route(self.graph, "D1", "L1")
        self.assertTrue(r.found)
        self.assertTrue(r.fully_accessible)
        self.assertFalse(any(s.edge_type == EdgeType.STAIRS for s in r.segments))

    def test_strict_avoids_steep_slope(self):
        r = plan_route(self.graph, "D1", "T1")
        self.assertTrue(r.found)
        self.assertTrue(all(s.slope <= 8.0 for s in r.segments))

    def test_elevator_route_to_teaching_building(self):
        # 教学楼最近的无障碍入口是电梯厅 E1
        r = plan_route(self.graph, "D1", "T1")
        self.assertIn("E1", r.path)
        self.assertTrue(any(s.edge_type == EdgeType.ELEVATOR for s in r.segments))

    def test_ramp_used_for_library(self):
        r = plan_route(self.graph, "D1", "L1")
        self.assertTrue(any(s.edge_type == EdgeType.RAMP for s in r.segments))

    def test_canteen_to_library_via_ramp(self):
        r = plan_route(self.graph, "C1", "L1")
        self.assertTrue(r.found)
        self.assertTrue(r.fully_accessible)
        self.assertEqual(r.path, ["C1", "J5", "L1"])

    def test_prefer_mode_uses_stairs_shortcut(self):
        # prefer 模式允许楼梯：D1→C1 会走 J1→J2 台阶捷径
        r = _dijkstra(self.graph, "D1", "C1", WeightConfig(strict=False))
        self.assertTrue(r.found)
        self.assertTrue(any(s.edge_type == EdgeType.STAIRS for s in r.segments))
        self.assertFalse(r.fully_accessible)

    def test_fallback_when_no_accessible_path(self):
        g = CampusGraph()
        g.add_node(Node("A", "甲"))
        g.add_node(Node("B", "乙"))
        g.add_edge(Edge("A", "B", 20, EdgeType.STAIRS))
        r = plan_route(g, "A", "B")
        self.assertTrue(r.found)
        self.assertTrue(r.fallback)
        self.assertFalse(r.fully_accessible)

    def test_unreachable(self):
        g = CampusGraph()
        g.add_node(Node("A", "甲"))
        g.add_node(Node("B", "乙"))
        self.assertFalse(plan_route(g, "A", "B").found)


class WeightTest(unittest.TestCase):
    """权重公式单元测试。"""

    def test_cost_formula(self):
        cfg = WeightConfig()
        # 平缓通道 100m、坡度 3%（≤软上限）→ 100
        e = Edge("a", "b", 100, EdgeType.WALKWAY, slope=3.0)
        self.assertAlmostEqual(edge_cost(e, cfg), 100.0)
        # 坡道 100m → 100 × 1.15
        e = Edge("a", "b", 100, EdgeType.RAMP, slope=4.0)
        self.assertAlmostEqual(edge_cost(e, cfg), 115.0)
        # 电梯 3m → 3 × 1.0 + 25 固定惩罚
        e = Edge("a", "b", 3, EdgeType.ELEVATOR)
        self.assertAlmostEqual(edge_cost(e, cfg), 28.0)

    def test_slope_penalty_in_prefer_mode(self):
        # 坡度 9%：100 × (1 + 0.4×(9-5)) = 260
        e = Edge("a", "b", 100, EdgeType.WALKWAY, slope=9.0)
        self.assertAlmostEqual(edge_cost(e, WeightConfig(strict=False)), 260.0)

    def test_strict_blocks_stairs_and_steep(self):
        cfg = WeightConfig(strict=True)
        self.assertTrue(math.isinf(edge_cost(Edge("a", "b", 10, EdgeType.STAIRS), cfg)))
        self.assertTrue(math.isinf(
            edge_cost(Edge("a", "b", 10, EdgeType.WALKWAY, slope=9.0), cfg)))
        # 坡度等于硬上限仍可通行
        self.assertFalse(math.isinf(
            edge_cost(Edge("a", "b", 10, EdgeType.WALKWAY, slope=8.0), cfg)))


class GraphIoTest(unittest.TestCase):
    def test_roundtrip(self):
        g = load_graph(DEFAULT_DATA)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "g.json"
            save_graph(g, p)
            g2 = load_graph(p)
        self.assertEqual(set(g.nodes), set(g2.nodes))
        self.assertEqual(sum(len(v) for v in g.adj.values()),
                         sum(len(v) for v in g2.adj.values()))
        self.assertEqual(plan_route(g, "D1", "T1").path,
                         plan_route(g2, "D1", "T1").path)


class AdminGraphTest(unittest.TestCase):
    def test_add_remove(self):
        g = CampusGraph()
        g.add_node(Node("A", "甲", kind="dorm"))
        g.add_node(Node("B", "乙", kind="library"))
        g.add_edge(Edge("A", "B", 50, EdgeType.RAMP, slope=4))
        self.assertEqual(len(g.neighbors("A")), 1)
        self.assertEqual(len(g.neighbors("B")), 1)   # 双向
        self.assertEqual(g.validate(), [])
        g.remove_edge("A", "B")
        self.assertEqual(len(g.neighbors("A")), 0)
        g.remove_node("B")
        self.assertNotIn("B", g.nodes)

    def test_validate_detects_dangling_edge(self):
        g = CampusGraph()
        g.add_node(Node("A", "甲"))
        g.adj["A"].append(Edge("A", "GHOST", 10))
        self.assertTrue(any("不存在" in p for p in g.validate()))


if __name__ == "__main__":
    unittest.main()


class PreferModeRegressionTest(unittest.TestCase):
    """回归：显式 prefer 模式必须直接使用优先模式求解。"""

    @classmethod
    def setUpClass(cls):
        cls.graph = load_graph(DEFAULT_DATA)

    def test_plan_route_prefer_mode_takes_stairs_shortcut(self):
        r = plan_route(self.graph, "D1", "C1", WeightConfig(strict=False))
        self.assertTrue(r.found)
        self.assertEqual(r.mode, "prefer")
        self.assertTrue(any(s.edge_type == EdgeType.STAIRS for s in r.segments))
