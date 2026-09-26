#!/usr/bin/env python3
"""高校无障碍路线规划系统 —— 统一入口。

用法：
    python3 main.py places                        # 列出可选地点
    python3 main.py route --from D1 --to T1       # 查询无障碍路线
    python3 main.py route --from D1 --to C1 --mode prefer
    python3 main.py admin <子命令>                 # 管理员维护校园图数据
"""
from __future__ import annotations

import argparse
import sys

from src import admin
from src.graph_io import DEFAULT_DATA, load_graph
from src.student import list_places, query_route


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="高校无障碍路线规划系统")
    parser.add_argument("--data", default=str(DEFAULT_DATA), help="图数据文件路径")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("places", help="列出可选地点（宿舍/教学楼/食堂/图书馆）")

    p = sub.add_parser("route", help="查询无障碍路线")
    p.add_argument("--from", dest="start", required=True, help="起点编号")
    p.add_argument("--to", dest="goal", required=True, help="终点编号")
    p.add_argument("--mode", choices=["strict", "prefer"], default="strict",
                   help="strict=严格无障碍（默认）；prefer=优先无障碍")

    p = sub.add_parser("admin", help="管理员：维护校园图数据")
    p.add_argument("admin_args", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "admin":
        admin_args = args.admin_args
        if admin_args and admin_args[0] == "--":
            admin_args = admin_args[1:]
        return admin.run(["--data", args.data, *admin_args])

    graph = load_graph(args.data)

    if args.command == "places":
        print("可选地点：")
        for label, places in list_places(graph).items():
            print(f"  【{label}】")
            for pid, name in places:
                print(f"    {pid:<6}{name}")
        print("\n查询路线：python3 main.py route --from <起点编号> --to <终点编号>")
        return 0

    if args.command == "route":
        try:
            print(query_route(graph, args.start, args.goal, mode=args.mode))
        except KeyError as exc:
            print(f"地点编号有误：{exc}。可用 `python3 main.py places` 查看可选地点。")
            return 1
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
