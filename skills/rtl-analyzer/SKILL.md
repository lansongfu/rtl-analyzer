# RTL Analyzer - 基于 pyslang 的静态时序分析

使用 pyslang 解析 SystemVerilog/Verilog 代码，进行静态结构分析和时序热点估算。

## 功能

### 基础分析
- ✅ 模块层次分析（模块名、实例化深度）
- ✅ 模块实例检测（实例名、位置）
- ✅ if 嵌套检测（>3 层报警）
- ✅ case 语句检测（>128 分支报警）
- ✅ 代码复杂度指标（环路复杂度、嵌套深度）

### 逻辑深度估算（基于 AST）
- ✅ 连线/位选/拼接：0 级深度
- ✅ 位运算/移位：1 级深度
- ✅ 2 选 1 MUX：1 级深度
- ✅ 加减法：ceil(log2(n)) 级深度
- ✅ 比较运算：ceil(log2(n)+1) 级深度
- ✅ 乘法：2*ceil(log2(n)) 级深度
- ✅ 多路 MUX：ceil(log2(w)) 级深度
- ✅ 除法/取模：4*ceil(log2(n)) 级深度

**n = 信号位宽（默认 32），w = MUX 分支数**

## 触发词

- rtl 分析
- 时序分析
- 关键路径
- 静态分析
- pyslang
- verilog 分析
- systemverilog 分析
- 代码复杂度

---

## 🤖 AI Agent 调用指南

### 方式 1：识别触发词自动调用

当用户消息包含触发词时，AI Agent 应：
1. 提取 RTL 文件路径（如未提供则询问）
2. 执行命令：`python3 rtl_analyzer.py <文件路径> [-o 输出.json]`
3. 解析 JSON 结果并返回摘要

**示例对话：**
```
用户："帮我分析一下这个 RTL 代码的复杂度"
AI："好的，请提供 RTL 文件路径"
用户："./design.sv"
AI：执行命令 → 返回摘要
```

### 方式 2：直接命令行调用

```bash
# 任何 AI agent 都可以执行
cd /root/.openclaw/workspace/skills/rtl-analyzer
python3 rtl_analyzer.py <RTL 文件路径> [-o 输出.json]
```

### 方式 3：Python API 集成

```python
from rtl_analyzer import RTLAnalyzer

def analyze_rtl(filepath: str) -> dict:
    """分析 RTL 文件"""
    analyzer = RTLAnalyzer()
    result = analyzer.analyze_file(filepath)
    return result['analysis']

# 使用示例
report = analyze_rtl('design.sv')
print(f"模块数：{report['module_count']}")
print(f"if 嵌套热点：{len(report['combinational_paths'])}")
```

### 方式 4：CI/CD 集成

```yaml
# GitHub Actions 示例
- name: RTL Analysis
  run: |
    pip install pyslang
    python3 rtl_analyzer.py ./src/rtl/ -o report.json
```

---

## 📋 输出解读指南

### 关键指标阈值

| 指标 | 正常 | 警告 | 危险 |
|------|------|------|------|
| if 嵌套深度 | ≤3 | 4-5 | >5 |
| case 分支数 | ≤128 | 129-256 | >256 |
| 逻辑深度 | ≤5 | 6-10 | >10 |
| 环路复杂度 | ≤10 | 11-20 | >20 |

### 典型建议话术

- **if 嵌套过深：** "第 X 行 if 嵌套 Y 层，建议拆分为多个小函数或使用状态机"
- **case 分支过多：** "case 语句有 X 个分支，考虑使用独热编码或优先级编码优化"
- **逻辑深度过大：** "组合逻辑路径过长（X 级），建议插入流水线寄存器"

## 安装

```bash
cd ~/.openclaw/workspace/skills/rtl-analyzer
pip install -r requirements.txt
```

## 使用方法

### 方式 1：直接调用 Python 脚本

```bash
python rtl_analyzer.py <rtl_file_or_directory>
```

### 方式 2：通过 AI Agent 调用

```bash
cd ~/.openclaw/workspace/skills/rtl-analyzer
python rtl_analyzer.py /path/to/your/rtl
```

### 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `path` | RTL 文件路径（支持 .v, .sv）或目录 | 必填 |
| `--output` | 输出文件路径（可选，默认 stdout） | - |
| `--top` | 顶层模块名（可选，自动推断） | - |
| `--depth` | 最大分析深度 | 10 |

## 输出格式

```json
{
  "file": "counter.v",
  "top_module": "counter",
  "analysis": {
    "max_structure_depth": 5,
    "module_count": 1,
    "instance_count": 3,
    "combinational_paths": [
      {
        "path": "counter.always_block[0].assignment",
        "depth": 3,
        "type": "combinational",
        "hotspot_reason": "嵌套 if-else 层级过深"
      }
    ],
    "timing_bottlenecks": [
      {
        "location": "counter.v:15",
        "type": "large_case_statement",
        "severity": "medium",
        "suggestion": "考虑使用编码优化或流水线"
      }
    ],
    "complexity_metrics": {
      "cyclomatic_complexity": 8,
      "nesting_depth": 4,
      "operator_count": 25
    }
  }
}
```

## 输出字段说明

| 字段 | 说明 |
|------|------|
| `max_structure_depth` | 模块实例化层次的最大深度 |
| `combinational_paths` | 组合逻辑路径估算（基于语法树） |
| `timing_bottlenecks` | 时序瓶颈热点（case/if 嵌套、大运算链） |
| `complexity_metrics` | 代码复杂度指标 |

## 依赖

- pyslang >= 2.0.0
- Python >= 3.8

## 限制

⚠️ **重要：** 本工具进行的是**静态结构分析**，不是真正的时序分析。

- ✅ 可以：模块层次分析、代码复杂度、结构深度估算
- ❌ 不能：真正的关键路径延迟、建立/保持时间检查（需要综合工具和工艺库）

## 示例

```bash
# 分析单个文件
python rtl_analyzer.py ./test/counter.v

# 分析整个目录
python rtl_analyzer.py ./src/rtl/

# 输出到文件
python rtl_analyzer.py ./src/rtl/ --output analysis.json
```

## 作者

Created for 木叶村 - 火影大人的芯片设计工具链

## 版本

v1.0.0
