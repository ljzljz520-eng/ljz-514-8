"""管理员端：维护校园图数据（节点与通道的增删查、数据校验）。"""
from __future__ import annotations

import argparse
from pathlib import Path

from .graph_io import DEFAULT_DATA, load_graph, save_graph
from .models import Edge, EdgeType, Node, NodeKind


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="admin", description="校园图数据维护")
    parser.add_argument("--data", default=str(DEFAULT_DATA), help="图数据文件路径")
    sub = parser.add_subparsers(dest="action", required=True)

    sub.add_parser("list-nodes", help="列出所有节点")
    sub.add_parser("list-edges", help="列出所有通道")
    sub.add_parser("validate", help="校验图数据完整性")

    p = sub.add_parser("add-node", help="新增节点")
    p.add_argument("--id", required=True, help="节点编号，如 D1")
    p.add_argument("--name", required=True, help="节点名称")
    p.add_argument("--kind", default="junction", choices=NodeKind.ALL, help="地点类别")
    p.add_argument("--x", type=float, default=0.0)
    p.add_argument("--y", type=float, default=0.0)

    p = sub.add_parser("remove-node", help="删除节点（连同关联通道）")
    p.add_argument("--id", required=True)

    p = sub.add_parser("add-edge", help="新增通道")
    p.add_argument("--source", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--length", type=float, required=True, help="长度（米）")
    p.add_argument("--type", default="walkway", choices=EdgeType.ALL, help="通道类型")
    p.add_argument("--slope", type=float, default=0.0, help="坡度（%%）")
    p.add_argument("--wait", type=float, default=0.0, help="电梯平均候梯时间（秒）")
    p.add_argument("--oneway", action="store_true", help="单向通道")
    p.add_argument("--note", default="", help="备注")

    p = sub.add_parser("remove-edge", help="删除通道（含反向）")
    p.add_argument("--source", required=True)
    p.add_argument("--target", required=True)
    return parser


def _print_nodes(graph) -> None:
    print(f"{'编号':<8}{'类别':<8}{'名称':<20}{'坐标'}")
    for n in graph.nodes.values():
        kind = NodeKind.LABELS.get(n.kind, n.kind)
        print(f"{n.id:<8}{kind:<8}{n.name:<20}({n.x:.0f}, {n.y:.0f})")


def _print_edges(graph) -> None:
    seen: set[tuple[str, str]] = set()
    print(f"{'起点':<8}{'终点':<8}{'类型':<8}{'长度(m)':<9}{'坡度(%)':<9}{'候梯(s)':<8}备注")
    for edges in graph.adj.values():
        for e in edges:
            key = (e.source, e.target)
            if key in seen or (e.target, e.source) in seen:
                continue
            seen.add(key)
            label = EdgeType.LABELS.get(e.edge_type, e.edge_type)
            print(f"{e.source:<8}{e.target:<8}{label:<8}"
                  f"{e.length:<9.0f}{e.slope:<9.1f}{e.elevator_wait:<8.0f}{e.note}")


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data_path = Path(args.data)
    graph = load_graph(data_path)

    if args.action == "list-nodes":
        _print_nodes(graph)
        return 0
    if args.action == "list-edges":
        _print_edges(graph)
        return 0
    if args.action == "validate":
        problems = graph.validate()
        if problems:
            print("发现以下数据问题：")
            for p in problems:
                print(f"  - {p}")
            return 1
        print("图数据校验通过，未发现问题。")
        return 0

    if args.action == "add-node":
        graph.add_node(Node(id=args.id, name=args.name, kind=args.kind,
                            x=args.x, y=args.y))
        print(f"已新增节点 {args.id}（{args.name}）。")
    elif args.action == "remove-node":
        graph.remove_node(args.id)
        print(f"已删除节点 {args.id} 及其关联通道。")
    elif args.action == "add-edge":
        graph.add_edge(Edge(
            source=args.source, target=args.target, length=args.length,
            edge_type=args.type, slope=args.slope, elevator_wait=args.wait,
            bidirectional=not args.oneway, note=args.note,
        ))
        print(f"已新增通道 {args.source} -> {args.target}"
              f"（{EdgeType.LABELS[args.type]}，{args.length:.0f} 米）。")
    elif args.action == "remove-edge":
        removed = graph.remove_edge(args.source, args.target)
        if removed == 0:
            print(f"未找到通道 {args.source} -> {args.target}。")
            return 1
        print(f"已删除通道 {args.source} <-> {args.target}（共 {removed} 条记录）。")

    save_graph(graph, data_path)
    return 0
