"""无障碍路线的成本权重配置与计算。

成本公式（详见 docs/algorithm_weights.md）：

    cost(e) = length(e) × M_type × M_slope(e) + P_fixed(e)

- M_type   ：通道类型系数（坡道略贵、楼梯重罚、电梯按固定惩罚）；
- M_slope  ：坡度系数，坡度超过平缓阈值后线性加价；
- P_fixed  ：固定惩罚（目前仅电梯，折算候梯时间）。

严格模式（strict）下，楼梯与陡坡（超过硬上限）直接视为不可通行；
优先模式（prefer）下，它们被允许通行但施加高额惩罚。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .models import Edge, EdgeType


@dataclass
class WeightConfig:
    """算法权重配置。所有参数含义见 docs/algorithm_weights.md。"""

    # 通行模式：True=严格无障碍（楼梯/陡坡禁行）；False=优先无障碍（重罚兜底）
    strict: bool = True

    # ---- 通道类型系数 M_type ----
    walkway_multiplier: float = 1.0     # 平缓通道：基准
    ramp_multiplier: float = 1.15       # 坡道：略慢，轻微加价
    stairs_multiplier: float = 6.0      # 楼梯：重罚（仅 prefer 模式生效）
    elevator_multiplier: float = 1.0    # 电梯：距离本身不加价

    # ---- 电梯固定惩罚 P_fixed（等效米）----
    # 折算候梯与乘梯时间：候梯约 30s，按步行 1.2m/s 折算约 36m，取整 25~40 均可
    elevator_fixed_penalty: float = 25.0

    # ---- 坡度参数 ----
    slope_soft_limit: float = 5.0       # 坡度 ≤5% 视为平缓，不加价
    slope_hard_limit: float = 8.0       # 坡度 >8% 视为陡坡，strict 模式禁行
    slope_penalty_rate: float = 0.4     # 每超出软上限 1 个百分点，成本 +40%

    def type_multiplier(self, edge_type: str) -> float:
        return {
            EdgeType.WALKWAY: self.walkway_multiplier,
            EdgeType.RAMP: self.ramp_multiplier,
            EdgeType.STAIRS: self.stairs_multiplier,
            EdgeType.ELEVATOR: self.elevator_multiplier,
        }[edge_type]

    def slope_multiplier(self, slope: float) -> float:
        """坡度系数：软上限内为 1，超出部分线性惩罚。"""
        if slope <= self.slope_soft_limit:
            return 1.0
        return 1.0 + self.slope_penalty_rate * (slope - self.slope_soft_limit)

    def is_blocked(self, edge: Edge) -> bool:
        """严格模式下不可通行的边：楼梯、陡坡。"""
        if not self.strict:
            return False
        if edge.edge_type == EdgeType.STAIRS:
            return True
        return edge.slope > self.slope_hard_limit


def edge_cost(edge: Edge, config: WeightConfig) -> float:
    """计算单条边的通行成本；不可通行返回 math.inf。"""
    if config.is_blocked(edge):
        return math.inf
    cost = edge.length * config.type_multiplier(edge.edge_type) \
        * config.slope_multiplier(edge.slope)
    if edge.edge_type == EdgeType.ELEVATOR:
        cost += config.elevator_fixed_penalty
    return cost
