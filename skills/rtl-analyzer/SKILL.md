# RTL Analyzer - 基于 pyslang 的静态时序分析

使用 pyslang 解析 SystemVerilog/Verilog 代码，进行静态结构分析和时序热点估算。

## 功能

- ✅ 模块层次分析（模块名、实例化深度）
- ✅ 模块实例检测（实例名、位置）
- ✅ if 嵌套检测（>3 层报警）
- ✅ case 语句检测（>8 分支报警）
- ✅ 代码复杂度指标（环路复杂度、嵌套深度）

## 触发词

- rtl 分析
- 时序分析
- 关键路径
- 静态分析
- pyslang
- verilog 分析
- systemverilog 分析
- 代码复杂度

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
