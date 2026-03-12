# RTL Analyzer

🔧 **RTL 静态时序分析工具** - 基于 pyslang 的 SystemVerilog/Verilog 代码分析技能

## 📦 安装

### 方法 1：Git 克隆（推荐）

```bash
cd ~/.openclaw/workspace/skills
git clone https://github.com/lansongfu/rtl-analyzer.git
```

### 方法 2：ClawHub（即将支持）

```bash
clawhub install rtl-analyzer
```

### 方法 3：手动下载

1. 下载 [rtl-analyzer.zip](https://github.com/lansongfu/rtl-analyzer/archive/refs/heads/main.zip)
2. 解压到 `~/.openclaw/workspace/skills/rtl-analyzer/`

## 🔧 依赖安装

```bash
# 安装 Python 依赖
pip3 install pyslang

# 验证安装
python3 -c "import pyslang; print(pyslang.__version__)"
```

## 🚀 使用方法

### 基本用法

```bash
cd ~/.openclaw/workspace/skills/rtl-analyzer

# 分析单个文件
python3 rtl_analyzer.py design.v

# 分析目录
python3 rtl_analyzer.py ./src/rtl/

# 生成 JSON 报告
python3 rtl_analyzer.py design.v --output report.json
```

### 输出示例

```
✅ test/counter.v:
   模块数：3, 实例数：3
   最大深度：2
   复杂度：4
   🔍 if 嵌套热点：1 个
```

## 📋 功能特性

- ✅ 模块/实例检测
- ✅ if 嵌套深度分析（>3 层报警）
- ✅ case 分支数检查（>128 报警）
- ✅ 逻辑深度估算
- ✅ 代码复杂度指标
- ✅ JSON/文本报告输出

## 📖 详细文档

查看 [SKILL.md](SKILL.md) 获取完整使用说明。

## 🧪 测试

```bash
cd ~/.openclaw/workspace/skills/rtl-analyzer
python3 rtl_analyzer.py test/counter.v
```

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License

---

**作者:** 克劳 (木叶村)
**版本:** v1.0
**更新时间:** 2026-03-12
