#!/usr/bin/env python3
"""
RTL Analyzer - 基于 pyslang 的静态时序分析工具

使用 pyslang 解析 SystemVerilog/Verilog 代码，进行静态结构分析和时序热点估算。

Usage:
    python rtl_analyzer.py <rtl_file_or_directory> [--output output.json]
"""

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple

try:
    import pyslang
    from pyslang import SyntaxTree, SyntaxKind
except ImportError:
    print("❌ 错误：pyslang 未安装", file=sys.stderr)
    print("请运行：pip install pyslang", file=sys.stderr)
    sys.exit(1)


# ============================================================================
# 逻辑深度估算规则表（可维护，可配置）
# ============================================================================
LOGIC_DEPTH_RULES = {
    # === 0 级深度 - 连线类 ===
    'wire': 0,           # 连线
    'bit_select': 0,     # 位选 [i]
    'part_select': 0,    # 部分选择 [i+:w]
    'concat': 0,         # 拼接 {a, b}
    'replication': 0,    # 复制 {3{a}}
    
    # === 1 级深度 - 简单并行运算 ===
    'bitwise_and': 1,    # &
    'bitwise_or': 1,     # |
    'bitwise_xor': 1,    # ^
    'bitwise_not': 1,    # ~
    'shift_l': 1,        # <<
    'shift_r': 1,        # >>
    'shift_ar': 1,       # >>> 算术移位
    'mux2to1': 1,        # 2 选 1 MUX (三元运算符 ?:)
    
    # === log2(n) 深度 - 进位链/比较树 ===
    'adder': 'log2(n)',      # 加减法
    'subtractor': 'log2(n)', # 减法器
    'eq': 'log2(n)+1',       # 等于 ==
    'neq': 'log2(n)+1',      # 不等于 !=
    'lt': 'log2(n)+1',       # 小于 <
    'le': 'log2(n)+1',       # 小于等于 <=
    'gt': 'log2(n)+1',       # 大于 >
    'ge': 'log2(n)+1',       # 大于等于 >=
    
    # === 2*log2(n) 深度 - 乘法树 ===
    'multiplier': '2*log2(n)',   # 乘法 *
    
    # === 4*log2(n) 深度 - 复杂运算 ===
    'divider': '4*log2(n)',      # 除法 /
    'modulo': '4*log2(n)',       # 取模 %
    
    # === log2(w) 深度 - 多路选择器 ===
    'mux': 'log2(w)',    # w 选 1 MUX (case 语句)
}


class LogicDepthEstimator:
    """逻辑深度估算器 - 基于 AST 和操作符类型"""
    
    def __init__(self, rules: Dict = None):
        self.rules = rules or LOGIC_DEPTH_RULES
        self._signal_widths: Dict[str, int] = {}  # 信号位宽缓存
    
    def _calc_log2_depth(self, n: int, multiplier: float = 1.0, offset: float = 0) -> int:
        """计算 log2(n) 类型的深度"""
        if n <= 1:
            return int(offset)
        return int(math.ceil(multiplier * math.log2(n) + offset))
    
    def _get_bit_width_from_type(self, type_node) -> int:
        """从类型节点提取位宽"""
        if not type_node:
            return 32  # 默认 32 位
        
        # 检查是否是向量类型 (logic [7:0])
        if hasattr(type_node, 'range'):
            range_node = type_node.range
            if range_node:
                # 尝试从 range 提取位宽
                if hasattr(range_node, 'left') and hasattr(range_node, 'right'):
                    try:
                        left = self._eval_constant(range_node.left)
                        right = self._eval_constant(range_node.right)
                        if left is not None and right is not None:
                            return abs(left - right) + 1
                    except:
                        pass
                return 32
        
        # 检查是否是 packed array
        if hasattr(type_node, 'dimensions'):
            dims = type_node.dimensions
            if dims:
                try:
                    total = 1
                    for dim in dims:
                        if hasattr(dim, 'range'):
                            r = dim.range
                            if hasattr(r, 'left') and hasattr(r, 'right'):
                                l = self._eval_constant(r.left)
                                r_val = self._eval_constant(r.right)
                                if l is not None and r_val is not None:
                                    total *= abs(l - r_val) + 1
                    return total
                except:
                    pass
        
        return 32
    
    def _eval_constant(self, node) -> Optional[int]:
        """尝试计算常量表达式的值"""
        if not node:
            return None
        
        kind = node.kind if hasattr(node, 'kind') else None
        
        # 整数常量
        if kind == SyntaxKind.IntegerLiteral:
            try:
                if hasattr(node, 'value'):
                    return int(node.value)
            except:
                pass
            # 尝试从文本解析
            if hasattr(node, 'text'):
                try:
                    text = str(node.text).strip()
                    # 处理带位宽的常量：8'd255, 4'b1010
                    if "'" in text:
                        parts = text.split("'")
                        if len(parts) == 2:
                            val_part = parts[1]
                            if val_part.startswith('b'):
                                return int(val_part[1:], 2)
                            elif val_part.startswith('h'):
                                return int(val_part[1:], 16)
                            elif val_part.startswith('o'):
                                return int(val_part[1:], 8)
                            else:
                                return int(val_part)
                    return int(text)
                except:
                    pass
            return None
        
        # 一元表达式（如 -5, ~3）
        if kind == SyntaxKind.UnaryExpression:
            if hasattr(node, 'operand'):
                val = self._eval_constant(node.operand)
                if val is not None:
                    op = node.operator if hasattr(node, 'operator') else None
                    if op and 'Minus' in str(op):
                        return -val
                    return val
        
        # 二元表达式（如 8-1, 2+3）
        if kind == SyntaxKind.BinaryExpression:
            left = self._eval_constant(getattr(node, 'left', None))
            right = self._eval_constant(getattr(node, 'right', None))
            if left is not None and right is not None:
                op = node.operator if hasattr(node, 'operator') else None
                op_str = str(op) if op else ''
                try:
                    if 'Add' in op_str:
                        return left + right
                    elif 'Subtract' in op_str:
                        return left - right
                    elif 'Multiply' in op_str:
                        return left * right
                    elif 'Divide' in op_str:
                        return left // right if right != 0 else None
                except:
                    pass
        
        return None
    
    def _infer_signal_width(self, node, context_depth: int = 0) -> int:
        """推断信号位宽"""
        if not node or context_depth > 10:
            return 32
        
        kind = node.kind if hasattr(node, 'kind') else None
        
        # 标识符 - 查找已知的位宽
        if kind == SyntaxKind.IdentifierName:
            if hasattr(node, 'text'):
                name = str(node.text).strip()
                if name in self._signal_widths:
                    return self._signal_widths[name]
            return 32  # 未知信号默认 32 位
        
        # 常量 - 从值推断位宽
        if kind == SyntaxKind.IntegerLiteral:
            val = self._eval_constant(node)
            if val is not None:
                if val == 0:
                    return 1
                return val.bit_length()
            return 32
        
        # 位选 - 从选择范围推断
        if kind == SyntaxKind.RangeSelectExpression:
            if hasattr(node, 'left') and hasattr(node, 'right'):
                left = self._eval_constant(node.left)
                right = self._eval_constant(node.right)
                if left is not None and right is not None:
                    return abs(left - right) + 1
            return 1
        
        # 拼接 - 位宽是各部分之和
        if kind == SyntaxKind.ConcatenationExpression:
            total = 0
            if hasattr(node, 'expressions'):
                try:
                    for expr in node.expressions:
                        if expr:
                            total += self._infer_signal_width(expr, context_depth + 1)
                except:
                    pass
            return max(total, 1)
        
        # 一元表达式 - 位宽不变
        if kind == SyntaxKind.UnaryExpression:
            if hasattr(node, 'operand'):
                return self._infer_signal_width(node.operand, context_depth + 1)
        
        # 二元表达式 - 位宽取两边最大值
        if kind == SyntaxKind.BinaryExpression:
            left_width = 0
            right_width = 0
            if hasattr(node, 'left'):
                left_width = self._infer_signal_width(node.left, context_depth + 1)
            if hasattr(node, 'right'):
                right_width = self._infer_signal_width(node.right, context_depth + 1)
            return max(left_width, right_width, 1)
        
        return 32
    
    def _get_operator_type(self, node) -> Optional[str]:
        """获取操作符类型"""
        if not hasattr(node, 'operator'):
            return None
        
        op = node.operator
        # 映射 pyslang 操作符到规则表
        op_map = {
            'Add': 'adder',
            'Subtract': 'subtractor',
            'Multiply': 'multiplier',
            'Divide': 'divider',
            'Modulo': 'modulo',
            'BinaryAnd': 'bitwise_and',
            'BinaryOr': 'bitwise_or',
            'BinaryXor': 'bitwise_xor',
            'BinaryAndAssignment': 'bitwise_and',
            'BinaryOrAssignment': 'bitwise_or',
            'BinaryXorAssignment': 'bitwise_xor',
            'ShiftLeft': 'shift_l',
            'ShiftRight': 'shift_r',
            'ArithmeticShiftLeft': 'shift_ar',
            'ArithmeticShiftRight': 'shift_ar',
            'Equal': 'eq',
            'NotEqual': 'neq',
            'LessThan': 'lt',
            'LessThanEqual': 'le',
            'GreaterThan': 'gt',
            'GreaterThanEqual': 'ge',
        }
        
        op_name = str(op).replace('BinaryOperator.', '') if hasattr(op, '__str__') else str(op)
        return op_map.get(op_name)
    
    def estimate_expression_depth(self, node, bit_width: int = None) -> Tuple[int, int]:
        """
        估算表达式的逻辑深度
        返回：(depth, bit_width)
        """
        if not node:
            return (0, 32)
        
        kind = node.kind if hasattr(node, 'kind') else None
        
        # 先推断位宽
        if bit_width is None:
            bit_width = self._infer_signal_width(node)
        
        # 二元表达式（加减乘除、位运算等）
        if kind == SyntaxKind.BinaryExpression:
            op_type = self._get_operator_type(node)
            
            # 递归计算子表达式
            left_depth, left_width = self.estimate_expression_depth(getattr(node, 'left', None))
            right_depth, right_width = self.estimate_expression_depth(getattr(node, 'right', None))
            max_child_depth = max(left_depth, right_depth)
            result_width = max(left_width, right_width)
            
            if op_type:
                rule = self.rules.get(op_type)
                if rule:
                    if isinstance(rule, int):
                        # 固定深度（0 或 1）
                        return (max_child_depth + rule, result_width)
                    elif 'log2(n)' in rule:
                        # 基于位宽的深度
                        if rule == 'log2(n)':
                            op_depth = self._calc_log2_depth(result_width, 1.0, 0)
                        elif rule == '2*log2(n)':
                            op_depth = self._calc_log2_depth(result_width, 2.0, 0)
                        elif rule == '4*log2(n)':
                            op_depth = self._calc_log2_depth(result_width, 4.0, 0)
                        elif rule == 'log2(n)+1':
                            op_depth = self._calc_log2_depth(result_width, 1.0, 1)
                        else:
                            op_depth = 1
                        return (max_child_depth + op_depth, result_width)
            
            # 未知操作符，默认深度 1
            return (max_child_depth + 1, result_width)
        
        # 三元运算符（MUX）
        elif kind == SyntaxKind.ConditionalExpression:
            cond_depth, _ = self.estimate_expression_depth(getattr(node, 'condition', None))
            left_depth, left_width = self.estimate_expression_depth(getattr(node, 'left', None))
            right_depth, right_width = self.estimate_expression_depth(getattr(node, 'right', None))
            
            mux_depth = self.rules.get('mux2to1', 1)
            max_data_depth = max(left_depth, right_depth)
            result_width = max(left_width, right_width)
            
            return (max(cond_depth, max_data_depth) + mux_depth, result_width)
        
        # 位选、部分选择（连线类，深度 0）
        elif kind in [SyntaxKind.ElementSelectExpression, SyntaxKind.RangeSelectExpression]:
            base_depth = 0
            base_width = 32
            if hasattr(node, 'expression'):
                base_depth, base_width = self.estimate_expression_depth(node.expression)
            
            # 计算选择后的位宽
            if kind == SyntaxKind.RangeSelectExpression:
                if hasattr(node, 'left') and hasattr(node, 'right'):
                    left = self._eval_constant(node.left)
                    right = self._eval_constant(node.right)
                    if left is not None and right is not None:
                        base_width = abs(left - right) + 1
            
            return (base_depth, base_width)  # 选择操作本身深度为 0
        
        # 拼接（深度 0）
        elif kind == SyntaxKind.ConcatenationExpression:
            max_child = 0
            total_width = 0
            if hasattr(node, 'expressions'):
                try:
                    for expr in node.expressions:
                        if expr:
                            d, w = self.estimate_expression_depth(expr)
                            max_child = max(max_child, d)
                            total_width += w
                except:
                    pass
            return (max_child, max(total_width, 1))  # 拼接本身深度为 0
        
        # 一元表达式（取反、负号等）
        elif kind == SyntaxKind.UnaryExpression:
            child_depth, child_width = self.estimate_expression_depth(getattr(node, 'operand', None))
            return (child_depth + 1, child_width)  # 一元操作符深度为 1
        
        # 标识符、常量（深度 0）
        elif kind in [SyntaxKind.IdentifierName, SyntaxKind.IntegerLiteral, 
                      SyntaxKind.StringLiteral]:
            return (0, bit_width)
        
        # 默认：递归子节点
        max_depth = 0
        for attr in ['expression', 'operand', 'left', 'right']:
            if hasattr(node, attr):
                child = getattr(node, attr)
                if child:
                    d, w = self.estimate_expression_depth(child)
                    max_depth = max(max_depth, d)
                    if bit_width is None:
                        bit_width = w
        
        return (max_depth, bit_width or 32)
    
    def estimate_case_mux_depth(self, case_items_count: int) -> int:
        """估算 case 语句的 MUX 深度（多路选择器）"""
        if case_items_count <= 1:
            return 0
        # log2(w) 深度
        return self._calc_log2_depth(case_items_count, 1.0, 0)


class RTLAnalyzer:
    """RTL 静态分析器 - 基于 pyslang SyntaxTree API"""

    def __init__(self, max_depth: int = 15):
        self.max_depth = max_depth
        self.modules: Dict[str, Dict] = {}
        self.instances: List[Dict] = []
        self.combinational_paths: List[Dict] = []
        self.timing_bottlenecks: List[Dict] = []
        self.logic_depth_estimator = LogicDepthEstimator()

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
            result["analysis"]["logic_depth"] = self._calculate_logic_depth(root)

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
            if items > 128:
                self.timing_bottlenecks.append({
                    "location": location,
                    "type": "large_case_statement",
                    "severity": "high" if items > 256 else "warning",
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
    
    def _calculate_logic_depth(self, root) -> Dict[str, Any]:
        """计算逻辑深度估算"""
        result = {
            "max_combinational_depth": 0,
            "deepest_path": None,
            "module_depths": {}
        }
        
        # 遍历所有模块，估算每个模块的逻辑深度
        for module_name, module_info in self.modules.items():
            module_result = {
                "estimated_max_depth": 0,
                "expressions_analyzed": 0,
                "bit_width_range": [1, 32]
            }
            
            # 在语法树中找到这个模块的节点并分析
            max_depth, max_width, expr_count = self._analyze_module_expressions(root, module_name)
            
            module_result["estimated_max_depth"] = max_depth
            module_result["expressions_analyzed"] = expr_count
            module_result["bit_width_range"] = [1, max_width]
            
            result["module_depths"][module_name] = module_result
            
            if max_depth > result["max_combinational_depth"]:
                result["max_combinational_depth"] = max_depth
                result["deepest_path"] = f"{module_name}.<combinational_logic>"
        
        return result
    
    def _analyze_module_expressions(self, root, target_module: str) -> Tuple[int, int, int]:
        """分析模块内所有表达式的逻辑深度"""
        max_depth = 0
        max_width = 32
        expr_count = 0
        
        # pyslang 的表达式类型列表
        EXPR_KINDS = [
            SyntaxKind.ConditionalExpression,  # ?: 三元运算符
            SyntaxKind.ConcatenationExpression, # 拼接
            SyntaxKind.ElementSelectExpression, # 位选
            SyntaxKind.SimpleRangeSelect,       # 部分选择
            # 二元运算符
            SyntaxKind.AddExpression,
            SyntaxKind.SubtractExpression,
            SyntaxKind.MultiplyExpression,
            SyntaxKind.DivideExpression,
            SyntaxKind.ModExpression,
            SyntaxKind.BinaryAndExpression,
            SyntaxKind.BinaryOrExpression,
            SyntaxKind.BinaryXorExpression,
            SyntaxKind.BinaryXnorExpression,
            SyntaxKind.ArithmeticShiftLeftExpression,
            SyntaxKind.ArithmeticShiftRightExpression,
            SyntaxKind.LogicalShiftLeftExpression,
            SyntaxKind.LogicalShiftRightExpression,
            SyntaxKind.EqualityExpression,
            SyntaxKind.CaseEqualityExpression,
            SyntaxKind.CaseInequalityExpression,
            SyntaxKind.LessThanExpression,
            SyntaxKind.LessThanEqualExpression,
            SyntaxKind.GreaterThanExpression,
            SyntaxKind.GreaterThanEqualExpression,
            SyntaxKind.LogicalAndExpression,
            SyntaxKind.LogicalOrExpression,
            # 一元运算符
            SyntaxKind.UnaryMinusExpression,
            SyntaxKind.UnaryPlusExpression,
            SyntaxKind.UnaryBitwiseNotExpression,
            SyntaxKind.UnaryBitwiseAndExpression,
            SyntaxKind.UnaryBitwiseOrExpression,
            SyntaxKind.UnaryBitwiseXorExpression,
            SyntaxKind.UnaryBitwiseNorExpression,
            SyntaxKind.UnaryBitwiseNandExpression,
            SyntaxKind.UnaryBitwiseXnorExpression,
            SyntaxKind.UnaryLogicalNotExpression,
        ]
        
        def traverse(node, in_target_module: bool):
            nonlocal max_depth, max_width, expr_count
            
            if not node:
                return
            
            kind = node.kind if hasattr(node, 'kind') else None
            
            # 检查是否进入目标模块
            if kind == SyntaxKind.ModuleDeclaration:
                name = self._get_name(node)
                in_target_module = (name == target_module)
            
            if in_target_module:
                # 分析表达式
                if kind in EXPR_KINDS:
                    try:
                        depth, width = self.logic_depth_estimator.estimate_expression_depth(node)
                        if depth > max_depth:
                            max_depth = depth
                        if width > max_width:
                            max_width = width
                        expr_count += 1
                    except Exception as e:
                        pass  # 跳过分析失败的表达式
            
            # 递归遍历
            for attr in ['members', 'statements', 'items', 'clauses']:
                if hasattr(node, attr):
                    val = getattr(node, attr)
                    if val:
                        # pyslang 的 items/members 等可能是单个节点或节点列表
                        # 需要特殊处理
                        if hasattr(val, '__iter__') and not isinstance(val, str):
                            try:
                                # 尝试迭代
                                items_list = list(val)
                                for item in items_list:
                                    if item:
                                        traverse(item, in_target_module)
                            except (TypeError, Exception):
                                # 迭代失败，当作单个节点
                                traverse(val, in_target_module)
                        else:
                            traverse(val, in_target_module)
            
            for attr in ['statement', 'body', 'condition', 'elseClause', 'clause']:
                if hasattr(node, attr):
                    val = getattr(node, attr)
                    if val:
                        traverse(val, in_target_module)
        
        traverse(root, False)
        return (max_depth, max_width, expr_count)


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
