# -*- coding: utf-8 -*-
"""无障碍寻路算法单元测试: python3 -m unittest discover -s tests -v"""
import json
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from router import CampusGraph, build_route, normalize_profile, DEFAULT_WEIGHTS

BASE = os.path.join(os.path.dirname(__file__), "..")
with open(os.path.join(BASE, "data", "campus.json"), encoding="utf-8") as f:
    CAMPUS = json.load(f)

WHEELCHAIR = normalize_profile(DEFAULT_WEIGHTS["profiles"]["wheelchair"])
STANDARD = normalize_profile(DEFAULT_WEIGHTS["profiles"]["standard"])
EDGE = {e["id"]: e for e in CAMPUS["edges"]}


class TestWeights(unittest.TestCase):
    def setUp(self):
        self.g = CampusGraph(CAMPUS)

    def test_stairs_forbidden_in_wheelchair_mode(self):
        """轮椅模式下楼梯代价为无穷大"""
        w = self.g.edge_weight(EDGE["e18"], WHEELCHAIR)  # e18 是楼梯
        self.assertEqual(w, math.inf)

    def test_stairs_penalized_in_standard_mode(self):
        """一般模式下楼梯被强惩罚(25倍距离)"""
        w = self.g.edge_weight(EDGE["e18"], STANDARD)
        self.assertEqual(w, 100 * 25.0)

    def test_steep_slope_hard_limit(self):
        """轮椅模式下坡度>12%的边禁止通行"""
        w = self.g.edge_weight(EDGE["e13"], WHEELCHAIR)  # 14% 陡坡
        self.assertEqual(w, math.inf)

    def test_elevator_fixed_cost(self):
        """电梯计入固定等待成本"""
        w = self.g.edge_weight(EDGE["e17"], WHEELCHAIR)
        self.assertEqual(w, 8 * 1.0 + 30.0)

    def test_slope_penalty_tiers(self):
        """坡度分档:5%不惩罚,10%进入第三档"""
        ramp = self.g.edge_weight(EDGE["e8"], WHEELCHAIR)   # 5% 坡道
        self.assertAlmostEqual(ramp, 105 * 1.05 * 1.0 * 1.0)
        steep = self.g.edge_weight(EDGE["e22"], WHEELCHAIR)  # 10% 颠簸坡道
        self.assertAlmostEqual(steep, 150 * 1.0 * (1 + 8.0) * 1.8)


class TestRouting(unittest.TestCase):
    def setUp(self):
        self.g = CampusGraph(CAMPUS)

    def test_prefers_ramp_over_stairs(self):
        """图书馆北广场->图书馆:应走坡道 e8 而非楼梯捷径 e18"""
        r = self.g.shortest_path("p4", "lib", STANDARD)
        self.assertIn("e8", r["edges"])
        self.assertNotIn("e18", r["edges"])

    def test_avoids_steep_shortcut(self):
        """宿舍A->一食堂:应绕平缓大道,不走10%陡坡土路 e22"""
        r = self.g.shortest_path("dorm_a", "cant1", WHEELCHAIR)
        self.assertNotIn("e22", r["edges"])
        self.assertIn("e3", r["edges"])  # 走中央广场平缓路

    def test_wheelchair_uses_elevator_or_ramp_to_library(self):
        """宿舍A->图书馆(轮椅):全程无楼梯、无陡坡"""
        r = build_route(self.g, ["dorm_a", "lib"], WHEELCHAIR)
        self.assertIsNotNone(r)
        kinds = {EDGE[eid]["kind"] for eid in r["path"]["edges"]}
        self.assertNotIn("stairs", kinds)
        for eid in r["path"]["edges"]:
            self.assertLessEqual(EDGE[eid]["slope"], 0.12)
        self.assertTrue(r["barrier_free"])

    def test_multi_waypoints_in_order(self):
        """宿舍->教学楼->食堂->图书馆:按顺序途经"""
        r = build_route(self.g, ["dorm_a", "tb1", "cant1", "lib"], WHEELCHAIR)
        self.assertIsNotNone(r)
        nodes = r["path"]["nodes"]
        idx = [nodes.index(w) for w in ["dorm_a", "tb1", "cant1", "lib"]]
        self.assertEqual(idx, sorted(idx))
        self.assertEqual(len(r["legs"]), 3)

    def test_unreachable_returns_none(self):
        """轮椅模式下若唯一通道是楼梯,应返回不可达"""
        campus = {
            "nodes": {"a": {"name": "A", "type": "junction", "x": 0, "y": 0},
                      "b": {"name": "B", "type": "junction", "x": 1, "y": 1}},
            "edges": [{"id": "x", "from": "a", "to": "b", "distance": 10,
                       "kind": "stairs", "slope": 0, "surface": "smooth"}],
        }
        g = CampusGraph(campus)
        self.assertIsNone(g.shortest_path("a", "b", WHEELCHAIR))
        # 一般模式下则可兜底通行
        self.assertIsNotNone(g.shortest_path("a", "b", STANDARD))

    def test_facility_counts(self):
        """路线统计应包含设施计数"""
        r = build_route(self.g, ["dorm_a", "lib"], WHEELCHAIR)
        total = sum(r["facility_counts"].values())
        self.assertEqual(total, len(r["path"]["edges"]))


if __name__ == "__main__":
    unittest.main()
