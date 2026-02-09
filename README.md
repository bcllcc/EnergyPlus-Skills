# EnergyPlus-Skill

一个面向 EnergyPlus 工作流的 Agent Skill，提供从 IDF 编辑、仿真执行、输出解析到校准与参数化研究的完整工程化能力。

本 Skill 的核心目标是：
- 提供可复用的 SOP（而不是一次性 prompt）
- 将高频且确定性的操作沉淀为脚本
- 在不同开发机上尽可能自动发现 EnergyPlus 安装路径
- 支持手动覆盖路径，降低“环境差异导致不可用”的风险

---

## 1. 功能总览

支持以下能力：
- IDF 文件校验、摘要、对象提取、输出变量注入
- Design-Day / Annual 仿真执行
- `.err/.sql/.csv/.html` 输出解析
- 预设图表生成与自定义可视化
- EPW 文件摘要、注入、比对、校验、统计
- 基准校准（RMSE / CV(RMSE) / NMBE / R2）
- 校准迭代记录与汇总
- 参数化批量仿真（多变体对比）
- 建筑几何查询与修改
- IDD 对象查询（避免直接加载完整 IDD）

---

## 2. 目录结构

```text
energyplus-skill/
├─ SKILL.md
├─ README.md
├─ scripts/
│  ├─ run_simulation.py
│  ├─ idd_lookup.py
│  ├─ idf_helper.py
│  ├─ parse_outputs.py
│  ├─ visualize_results.py
│  ├─ epw_helper.py
│  ├─ calibration.py
│  ├─ calibration_tracker.py
│  ├─ parametric_runner.py
│  └─ geometry_helper.py
└─ references/
   ├─ IDF-EDITING-GUIDE.md
   ├─ SIMULATION-GUIDE.md
   ├─ OUTPUT-ANALYSIS-GUIDE.md
   ├─ COMMON-ERRORS.md
   ├─ OBJECT-QUICK-REF.md
   ├─ EPW-FORMAT-GUIDE.md
   ├─ CALIBRATION-TRACKING-GUIDE.md
   └─ VISUALIZATION-STYLE-GUIDE.md
```

---

## 3. 环境要求

- Python 3.9+（建议 3.11+）
- 已安装 EnergyPlus（建议 23.x 及以上）
- `matplotlib`（用于图表）
- Windows / Linux / macOS 均可使用（路径发现已做平台分支）

说明：
- 脚本本身不依赖额外复杂框架，主要使用标准库 + `matplotlib`
- 推荐将 EnergyPlus 安装目录加入 PATH，或设置环境变量以获得更稳定的行为

---

## 4. 自动发现与手动覆盖

### 4.1 自动发现策略

`run_simulation.py` 会按如下优先级发现 `energyplus` 与 `Energy+.idd`：

1. CLI 手动参数
2. 环境变量（`ENERGYPLUS_EXE` / `ENERGYPLUS_IDD`）
3. 环境变量（`ENERGYPLUS_HOME` / `EPLUS_HOME`）
4. PATH 中的可执行文件
5. 常见安装目录扫描
6. IDD 额外回退：IDF 同目录 / 当前目录（`run_simulation.py`）

`idd_lookup.py` 的 `Energy+.idd` 发现策略：

1. CLI `--idd`
2. `ENERGYPLUS_IDD`
3. `ENERGYPLUS_HOME` / `EPLUS_HOME`
4. `ENERGYPLUS_EXE` 或 PATH 命中可执行文件的同目录
5. 当前目录
6. 常见安装目录扫描

### 4.2 手动覆盖（推荐生产环境固定）

- `run_simulation.py`：
  - `--energyplus-exe "path/to/energyplus[.exe]"`
  - `--idd "path/to/Energy+.idd"`
- `idd_lookup.py`：
  - `--idd "path/to/Energy+.idd"`

---

## 5. Doctor / Check-Env

为了解决“换电脑就翻车”的问题，两个入口都支持环境诊断。

### 5.1 run_simulation 环境诊断

```bash
python scripts/run_simulation.py --check-env
python scripts/run_simulation.py --doctor
```

可选手动覆盖诊断：

```bash
python scripts/run_simulation.py --check-env \
  --energyplus-exe "C:\EnergyPlusV23-2-0\energyplus.exe" \
  --idd "C:\EnergyPlusV23-2-0\Energy+.idd"
```

输出内容包含：
- 逐步发现链路（每步 `MISS`/`OK`）
- 最终命中的路径
- 失败时的一键修复命令（PowerShell/bash）

### 5.2 idd_lookup 环境诊断

```bash
python scripts/idd_lookup.py --doctor
python scripts/idd_lookup.py --check-env
```

可选手动覆盖诊断：

```bash
python scripts/idd_lookup.py --doctor --idd "C:\EnergyPlusV23-2-0\Energy+.idd"
```

---

## 6. 快速开始

### 6.1 第一步：确认环境可用

```bash
python scripts/run_simulation.py --check-env
python scripts/idd_lookup.py --doctor
```

### 6.2 第二步：校验 IDF

```bash
python scripts/idf_helper.py validate path/to/model.idf
python scripts/idf_helper.py check-hvactemplate path/to/model.idf
```

### 6.3 第三步：执行仿真

Design-Day：

```bash
python scripts/run_simulation.py \
  --idf path/to/model.idf \
  --design-day \
  --output-dir path/to/output
```

Annual：

```bash
python scripts/run_simulation.py \
  --idf path/to/model.idf \
  --weather path/to/weather.epw \
  --output-dir path/to/output
```

如果模型包含 `HVACTemplate:*`，必须增加：

```bash
--expand-objects
```

### 6.4 第四步：先查 err 再看结果

```bash
python scripts/parse_outputs.py errors path/to/output
python scripts/parse_outputs.py summary path/to/output
```

---

## 7. 脚本命令总表

| 脚本 | 主要子命令 / 参数 | 作用 |
|---|---|---|
| `run_simulation.py` | `--check-env` `--doctor` `--idf` `--weather` `--design-day` `--expand-objects` `--energyplus-exe` `--idd` | 仿真执行与环境诊断 |
| `idd_lookup.py` | `--doctor` `--check-env` `--list-objects` `--search` `--fields` `--idd` | IDD 查询与环境诊断 |
| `idf_helper.py` | `validate` `list-objects` `get-object` `summary` `add-output` `check-hvactemplate` | IDF 编辑辅助 |
| `parse_outputs.py` | `errors` `summary` `timeseries` `sql` `available-vars` `available-meters` | 输出解析 |
| `visualize_results.py` | `--type` `--data` `--output` | 预设图可视化 |
| `epw_helper.py` | `summary` `read` `write` `inject` `validate` `stats` `create` `compare` | EPW 处理 |
| `calibration.py` | `compare` `metrics` | 校准指标计算与对比图 |
| `calibration_tracker.py` | `record` `summary` | 校准迭代追踪 |
| `parametric_runner.py` | `run` `generate-template` `report` | 参数化批量对比 |
| `geometry_helper.py` | `list-surfaces` `summary` `scale` `set-height` `move-wall` `create-box` `create-l-shape` `add-window` | 几何建模辅助 |

---

## 8. 常见工作流

### 8.1 IDF 编辑与安全校验

```bash
python scripts/idd_lookup.py --fields "WindowMaterial:SimpleGlazingSystem"
python scripts/idf_helper.py validate path/to/model.idf
```

### 8.2 输出摘要与时序抽取

```bash
python scripts/parse_outputs.py summary path/to/output
python scripts/parse_outputs.py timeseries path/to/output \
  --variable "Zone Mean Air Temperature"
```

### 8.3 EPW 注入与对比

```bash
python scripts/epw_helper.py inject \
  --epw base.epw \
  --csv measured_weather.csv \
  --output merged.epw

python scripts/epw_helper.py compare --epw-a base.epw --epw-b merged.epw
```

### 8.4 基准校准

```bash
python scripts/calibration.py compare \
  --simulated path/to/eplusout.sql \
  --measured path/to/measured.csv \
  --variable "Zone Mean Air Temperature" \
  --output-dir path/to/calibration
```

### 8.5 参数化研究

```bash
python scripts/parametric_runner.py run \
  --base path/to/base.idf \
  --variants path/to/variants.json \
  --weather path/to/weather.epw \
  --output-dir path/to/parametric
```

---

## 9. 设计约束与质量规则

请遵守以下规则以保证稳定性：
- 每次仿真后立即检查 `.err`
- 不要直接整文件加载 IDD，优先用 `idd_lookup.py`
- 不要“全量读 IDF”，按对象类分段处理
- 年仿真必须提供 `--weather`
- `HVACTemplate` 模型必须 `--expand-objects`
- 校准每一轮必须记录参数变化和版本标签

---

## 10. 常见问题（FAQ）

### Q1：自动发现失败怎么办？

先运行：

```bash
python scripts/run_simulation.py --check-env
```

如果失败，优先使用以下方式之一：
- 方式 A：设置 `ENERGYPLUS_EXE` / `ENERGYPLUS_IDD`
- 方式 B：命令行显式传入 `--energyplus-exe` 与 `--idd`

### Q2：仿真立即失败，提示 HVACTemplate？

在命令中加入：

```bash
--expand-objects
```

### Q3：为什么 `idd_lookup.py` 在项目根目录和其它目录命中路径不同？

因为其发现链路包含“当前目录回退”。在项目根目录若存在 `Energy+.idd`，会优先命中该文件。

---

## 11. 安全与开源发布建议

- 不要提交 `__pycache__/` 与本机缓存
- 不要在代码中写死个人路径
- 不要提交任何密钥、令牌、私有数据文件
- 发布前建议做一次扫描：

```bash
rg -n --hidden "C:\\\\Users|api[_-]?key|secret|token|password|__pycache__" .
```

---

## 12. 与官方文档的关系

本 Skill 用于工程流程编排与工具封装，不替代 EnergyPlus 官方规范。  
涉及 API 行为、参数细节、边界条件时，应以官方文档为准

---

## 13. License

本项目已采用 MIT 许可证，详见仓库根目录的 [`LICENSE`](./LICENSE) 文件。  
当前许可证版权声明为：`Copyright (c) 2026 杨家文`。

