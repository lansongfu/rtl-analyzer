#!/usr/bin/env python3
"""
RTL Analyzer - 基于 pyslang 的静态时序分析工具

使用 pyslang 解析 SystemVerilog/Verilog 代码，进行静态结构分析和时序热点估算。

Usage:
    python rtl_analyzer.py <rtl_file_or_directory> [--output output.json]
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Set

try:
    import pyslang
    from pyslang import SyntaxTree, SyntaxKind
except ImportError:
    print("❌ 错误：pyslang 未安装", file=sys.stderr)
    print("请运行：pip install pyslang", file=sys.stderr)
    sys.exit(1)


class RTLAnalyzer:
    """RTL 静态分析器 - 基于 pyslang SyntaxTree API"""

    def __init__(self, max_depth: int = 15):
        self.max_depth = max_depth
        self.modules: Dict[str, Dict] = {}
        self.instances: List[Dict] = []
        self.combinational_paths: List[Dict] = []
        self.timing_bottlenecks: List[Dict] = []

    def analyze_file(self, filepath: str) -> Dict[str, Any]:
        """分析单个 RTL 文件"""
        # 重置状态
        self.modules = {}
        self.instances = []
        self.combinational_paths = []
        self.timing_bottlenecks = []

        result = {
            "file": filepath,
            "top_module": None,
            "analysis": {
                "max_structure_depth": 0,
                "module_count": 0,
                "instance_count": 0,
                "combinational_paths": [],
                "timing_bottlenecks": [],
                "complexity_metrics": {}
            }
        }

        try:
            # 使用 pyslang SyntaxTree API 解析文件
            tree = SyntaxTree.fromFile(filepath)
            if not tree or not tree.root:
                result["error"] = f"无法解析文件：{filepath}"
                return result

            # 遍历语法树
            root = tree.root
            if hasattr(root, 'members'):
                for member in root.members:
                    self._traverse(member, depth=0, if_depth=0)

            # 设置顶层模块
            if self.modules:
                result["top_module"] = list(self.modules.keys())[0]

            result["analysis"]["module_count"] = len(self.modules)
            result["analysis"]["instance_count"] = len(self.instances)
            result["analysis"]["max_structure_depth"] = self._calc_max_depth()
            result["analysis"]["combinational_paths"] = self.combinational_paths[:10]
            result["analysis"]["timing_bottlenecks"] = self.timing_bottlenecks[:10]
            result["analysis"]["complexity_metrics"] = self._calculate_complexity(root)

        except Exception as e:
            result["error"] = f"{type(e).__name__}: {str(e)}"

        return result

    def _get_children(self, node) -> List:
        """获取节点的所有子节点（使用 pyslang 原生属性）"""
        children = []
        if not node:
            return children

        # 注意：不使用 visited 缓存，因为 pyslang 树可能有共享节点

        # 遍历 pyslang 节点的常见子节点属性
        for attr in ['members', 'statements', 'items', 'specifiers', 'clauses', 'ports']:
            if hasattr(node, attr):
                val = getattr(node, attr)
                if val is None:
                    continue
                # 尝试迭代（pyslang 的 SyntaxNode 可迭代但不是列表）
                if hasattr(val, '__iter__') and not isinstance(val, str):
                    try:
                        # 尝试用 enumerate 迭代（适用于 pyslang SyntaxNode）
                        for item in val:
                            if item and hasattr(item, 'kind'):
                                children.append(item)
                    except (TypeError, Exception):
                        # 迭代失败，当作单个节点
                        if val and hasattr(val, 'kind'):
                            children.append(val)
                elif hasattr(val, 'kind'):
                    children.append(val)

        # 单数属性
        for attr in ['statement', 'body', 'condition', 'elseClause', 'action', 'header', 'decl', 'clause']:
            if hasattr(node, attr):
                val = getattr(node, attr)
                if val and hasattr(val, 'kind'):
                    children.append(val)

        return children

    def _traverse(self, node, depth: int, if_depth: int):
        """递归遍历语法树"""
        if not node or depth > self.max_depth:
            return

        kind = node.kind if hasattr(node, 'kind') else None

        # 检测模块定义
        if kind == SyntaxKind.ModuleDeclaration:
            name = self._get_name(node)
            if name:
                self.modules[name] = {"name": name, "depth": depth}

        # 检测接口定义
        elif kind == SyntaxKind.InterfaceDeclaration:
            name = self._get_name(node)
            if name:
                self.modules[name] = {"name": name, "depth": depth}

        # 检测模块实例化
        elif kind == SyntaxKind.HierarchyInstantiation:
            instances = self._extract_instances(node)
            self.instances.extend(instances)

        # 检测条件语句（if）
        elif kind == SyntaxKind.ConditionalStatement:
            new_if_depth = if_depth + 1
            location = self._get_location(node)
            if new_if_depth > 3:
                self.combinational_paths.append({
                    "path": f"if_nesting at {location}",
                    "depth": new_if_depth,
                    "type": "combinational",
                    "hotspot_reason": f"嵌套 if-else 层级过深 ({new_if_depth} 层)"
                })
            # 继续遍历子节点
            for child in self._get_children(node):
                self._traverse(child, depth + 1, new_if_depth)
            return

        # 检测 case 语句
        elif kind == SyntaxKind.CaseStatement:
            location = self._get_location(node)
            items = self._count_case_items(node)
            if items > 8:
                self.timing_bottlenecks.append({
                    "location": location,
                    "type": "large_case_statement",
                    "severity": "high" if items > 16 else "medium",
                    "suggestion": f"case 语句有 {items} 个分支，考虑使用编码优化或流水线",
                    "details": f"分支数：{items}"
                })

        # 递归遍历子节点
        for child in self._get_children(node):
            self._traverse(child, depth + 1, if_depth)

    def _get_name(self, node) -> Optional[str]:
        """获取模块/接口名称"""
        # 模块/接口的名字在 header.name 里
        if hasattr(node, 'header') and node.header:
            header = node.header
            if hasattr(header, 'name') and header.name:
                name_val = header.name
                if hasattr(name_val, 'valueText'):
                    return str(name_val.valueText).strip()
                elif hasattr(name_val, 'text'):
                    return str(name_val.text).strip()
                else:
                    return str(name_val).strip()
        return None

    def _extract_instances(self, node) -> List[Dict]:
        """提取模块实例化信息"""
        instances = []
        try:
            if hasattr(node, 'instances'):
                inst_val = node.instances
                inst_list = []
                # 处理可能是单个节点或列表
                if hasattr(inst_val, '__iter__') and not isinstance(inst_val, str):
                    try:
                        inst_list = list(inst_val)
                    except TypeError:
                        inst_list = [inst_val]
                else:
                    inst_list = [inst_val]

                for inst in inst_list:
                    if inst and hasattr(inst, 'decl') and inst.decl:
                        decl = inst.decl
                        if hasattr(decl, 'name') and decl.name:
                            inst_name = str(decl.name).strip()
                            instances.append({
                                "name": inst_name,
                                "location": self._get_location(node)
                            })
        except:
            pass
        return instances

    def _get_location(self, node) -> str:
        """获取节点在源代码中的位置"""
        try:
            if hasattr(node, 'sourceRange') and node.sourceRange:
                start = node.sourceRange.start
                if hasattr(start, 'line'):
                    return f"line {start.line + 1}"
        except:
            pass
        return "unknown"

    def _count_case_items(self, node) -> int:
        """统计 case 语句的分支数"""
        count = 0
        if hasattr(node, 'items'):
            items = node.items
            if hasattr(items, '__iter__') and not isinstance(items, str):
                try:
                    count = len(list(items))
                except TypeError:
                    count = 1
            else:
                count = 1
        elif hasattr(node, 'clauses'):
            count = len([c for c in node.clauses if c])
        return max(count, 1)

    def _calculate_complexity(self, root) -> Dict[str, int]:
        """计算代码复杂度指标"""
        metrics = {
            "cyclomatic_complexity": 1,
            "nesting_depth": 0,
            "if_count": 0,
            "case_count": 0,
            "module_count": len(self.modules)
        }
        visited = set()

        def count(node, depth=0):
            if not node or id(node) in visited:
                return
            visited.add(id(node))

            kind = node.kind if hasattr(node, 'kind') else None
            if kind == SyntaxKind.ConditionalStatement:
                metrics["cyclomatic_complexity"] += 1
                metrics["if_count"] += 1
            elif kind == SyntaxKind.CaseStatement:
                metrics["cyclomatic_complexity"] += 1
                metrics["case_count"] += 1
            elif kind in [SyntaxKind.ForLoopStatement, SyntaxKind.DoWhileStatement]:
                metrics["cyclomatic_complexity"] += 1

            if depth > metrics["nesting_depth"]:
                metrics["nesting_depth"] = depth

            for child in self._get_children(node):
                count(child, depth + 1)

        count(root)
        return metrics

    def _calc_max_depth(self) -> int:
        """计算最大结构深度"""
        if not self.modules:
            return 0
        return max(m["depth"] for m in self.modules.values()) + 1


def analyze_directory(dirpath: str, analyzer: RTLAnalyzer) -> List[Dict]:
    """分析目录中的所有 RTL 文件"""
    results = []
    rtl_extensions = {'.v', '.sv', '.vh', '.svh'}

    for root, dirs, files in os.walk(dirpath):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for file in sorted(files):
            if Path(file).suffix.lower() in rtl_extensions:
                filepath = os.path.join(root, file)
                print(f"📄 分析：{filepath}")
                result = analyzer.analyze_file(filepath)
                results.append(result)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="RTL 静态分析工具 - 基于 pyslang",
        epilog="""
示例:
  python rtl_analyzer.py counter.v
  python rtl_analyzer.py ./src/rtl/ --output analysis.json
        """
    )
    parser.add_argument("path", help="RTL 文件路径或目录")
    parser.add_argument("--output", "-o", help="输出文件路径（JSON 格式）")
    parser.add_argument("--depth", "-d", type=int, default=15, help="最大分析深度")

    args = parser.parse_args()

    if not os.path.exists(args.path):
        print(f"❌ 错误：路径不存在：{args.path}", file=sys.stderr)
        sys.exit(1)

    analyzer = RTLAnalyzer(max_depth=args.depth)
    print(f"🔍 开始分析：{args.path}")
    print("-" * 50)

    if os.path.isfile(args.path):
        results = [analyzer.analyze_file(args.path)]
    else:
        results = analyze_directory(args.path, analyzer)

    # 输出
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\n✅ 结果已保存到：{args.output}")
    else:
        print("\n" + "=" * 50)
        print("📊 分析结果:")
        print("=" * 50)
        print(json.dumps(results, indent=2, ensure_ascii=False))

    # 打印摘要
    print("\n" + "=" * 50)
    print("📋 摘要:")
    print("=" * 50)
    for result in results:
        if "error" in result:
            print(f"❌ {result['file']}: {result['error']}")
        else:
            a = result["analysis"]
            print(f"✅ {result['file']}:")
            print(f"   模块数：{a['module_count']}, 实例数：{a['instance_count']}")
            print(f"   最大深度：{a['max_structure_depth']}")
            print(f"   复杂度：{a['complexity_metrics'].get('cyclomatic_complexity', 'N/A')}")
            if a['timing_bottlenecks']:
                print(f"   ⚠️  时序瓶颈：{len(a['timing_bottlenecks'])} 个")
            if a['combinational_paths']:
                print(f"   🔍 if 嵌套热点：{len(a['combinational_paths'])} 个")


if __name__ == "__main__":
    main()
