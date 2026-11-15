# 目标岗位表与项目证据映射（2026-11）

日期：2026-11-15  
目的：不再泛泛看市场，直接回答三个问题：

1. 投哪些岗位？
2. 每个岗位要什么？
3. 现有项目能证明什么、还缺什么？

数据来源：京东招聘官方 API、腾讯招聘官方 API、Amazon Jobs、NVIDIA 官方 JD。  
BOSS直聘被风控，未抓取；本表不伪造 BOSS 数据。

---

## 0. 先定策略

**主攻：国内电商/物流供应链算法（OR 方向）**

- 京东物流、阿里/菜鸟、美团、拼多多/Temu、字节电商、顺丰；
- 岗位名多为“算法开发/算法工程师”，不是 “Operations Research”。

**次选：Data Scientist / OR Analyst / 供应链规划**

- 更现实，但技术深度和薪资天花板低一些。

**参考：Amazon SCOT / NVIDIA**

- 当能力标杆，不当第一目标；PhD/年限门槛高。

**不投：**

- Agent Post-Training、FDE、纯大模型算法；
- Senior/Principal（PhD + 5–10 年）。

---

## 1. 20 个目标岗位

匹配度说明：

- **A**：现有项目能讲 60% 以上，补齐 1–2 个技能可投；
- **B**：方向匹配，但年限/domain/工程有硬缺口，适合冲刺；
- **C**：方向或门槛不匹配，只作参考。

| # | 公司 | 岗位 | 地点 | 门槛 | 核心要求 | 匹配 |
|---:|---|---|---|---|---|---|
| 1 | 京东物流 | [算法开发](https://zhaopin.jd.com/web/job-info-detail?requementId=227467) | 北京 | 3+ 年，硕士优先 | 路径/调度/网络优化；LP/IP/启发式；Gurobi/CPLEX；Python+Java/Go/C++；SQL；ML；LLM 必须了解 | **B+** |
| 2 | 京东物流 | [运筹优化/机器学习算法工程师](https://zhaopin.jd.com/web/job-info-detail?requementId=225705) | 北京 | 硕士 + 3 年 OR | 网点/配送范围/任务调度/ETA；Spark/Flink；C++/Java/Python | **B+** |
| 3 | 京东 | [算法开发（供应链预测/诊断/运筹）](https://zhaopin.jd.com/web/job-info-detail?requementId=227030) | 北京 | 供应链算法体系经验 | 预测、诊断、运筹；库存/履约/成本；大模型辅助诊断 | **C+**（偏 lead） |
| 4 | 京东物流 | [路线推荐/ETA 算法](https://zhaopin.jd.com/web/job-info-detail?requementId=226181) | 北京 | 路线/地图经验 | 轨迹挖掘、路径规划、ETA、线上服务 | **B-**（routing 缺口） |
| 5 | 京东物流 | [仓储机器人调度](https://zhaopin.jd.com/web/job-info-detail?requementId=223742) | 北京 | 调度系统经验 | 路径规划、任务分配、交通管制、异构设备 | **C**（robotics） |
| 6 | 京东物流 | [地图路线/ETA](https://zhaopin.jd.com/web/job-info-detail?requementId=221928) | 北京 | 2+ 年地图算法 | 算路/排序/ETA；Java/Python/C++/Go；Spark/Flink | **B-** |
| 7 | 京东物流 | [网络规划](https://zhaopin.jd.com/web/job-info-detail?requementId=227814) | 北京 | 网络规划经验 | 仓网/揽派网络、SQL/Excel、成本分析 | **C+**（domain） |
| 8 | 京东健康 | [供应链规划岗](https://zhaopin.jd.com/web/job-info-detail?requementId=226822) | 北京 | 医药/即时零售规划 | 仓配方案、BOM、库存周转、现货率 | **C**（业务规划） |
| 9 | 京东零售 | [供应链规划](https://zhaopin.jd.com/web/job-info-detail?requementId=223752) | 北京 | 大件仓网经验 | 仓网、库存布局、履约成本 | **C**（业务规划） |
| 10 | 京东零售 | [供应链AI算法](https://zhaopin.jd.com/web/job-info-detail?requementId=227618) | 北京 | 大模型/Agent 经验 | 后训练、Agent、补货/定价/调拨 | **C**（AI-heavy） |
| 11 | 腾讯 | [AI for Systems 调度算法](https://careers.tencent.com/jobdesc.html?postId=2118244734064570368) | 北京 | OR/调度经验 | 资源调度、容量规划、启发式/ML、Python | **C+**（非供应链） |
| 12 | Amazon | [Applied Scientist, Modeling & Optimization](https://www.amazon.jobs/en/jobs/10540608) | Bellevue | PhD 或 Master+4；论文 | 数值优化、ML、供应链网络、Python/Java/C++ | **C+**（论文/年限） |
| 13 | Amazon | [Senior Applied Scientist, Optimization](https://www.amazon.jobs/en/jobs/10559787) | Bellevue | PhD OR + 5 年 | LP/非线性优化、履约网络、团队 | **C** |
| 14 | Amazon | [Senior Applied Scientist, Strategic Sourcing](https://www.amazon.jobs/en/jobs/10569174) | Bellevue | PhD OR + 5 年 | 库存、随机优化、RL/因果 | **C** |
| 15 | Amazon | [Research Scientist, SCOT First Inbound](https://www.amazon.jobs/en/jobs/10593798) | New York | PhD | 因果、A/B、准实验、ML/统计 | **C** |
| 16 | Amazon | [Applied Scientist, SCOT](https://www.amazon.jobs/en/jobs/10537551) | Bellevue | PhD 或 Master+4；论文 | 数值优化、ML、选品/库存 | **C+** |
| 17 | Amazon | [Data Scientist, SCOT](https://www.amazon.jobs/en/jobs/10554991) | Bengaluru | 2+ 年 | SQL/Python、ML/统计、forecasting/buying/placement | **B**（更现实） |
| 18 | Amazon | [Senior Applied Scientist, Last Mile](https://www.amazon.jobs/en/jobs/10551517) | Bengaluru | 5+ 年 | 调度/路径/ML、PhD/Master+5 | **C** |
| 19 | Amazon | [Applied Scientist, SCOT FO](https://www.amazon.jobs/en/jobs/10556295) | Barcelona | PhD/Master；论文 | 数值优化、预测/ML、履约 | **C+** |
| 20 | NVIDIA | [Modeling Engineer, Supply Chain Optimization](https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/US-CA-Santa-Clara/Modeling-Engineer--Supply-Chain-Optimization_JR2025602) | Santa Clara | 8+ 年 | LP/MIP、dual、BOM/产能/lead time | **C**（标杆） |

---

## 2. 先投哪几个

### 冲刺（B+）

1. **京东物流 算法开发（#1）**
   - 最匹配你的 OR 背景；
   - 缺口：3 年经验、Gurobi/CPLEX、Java/Go/C++、路径/调度 domain。

2. **京东物流 运筹优化/ML（#2）**
   - OR + ML + 末端履约；
   - 缺口：Spark/Flink、ETA/调度经验、3 年。

### 现实（B）

3. **Amazon Data Scientist, SCOT（#17）**
   - 2+ 年、SQL/Python/ML；
   - 更适合硕士，但地点在印度，需考虑 relocation。

### 校招/初级

- 京东校招：https://campus.jd.com/
- 阿里/菜鸟、美团、拼多多、字节电商校招入口；
- 关键词：供应链算法、运筹优化、物流算法、调度算法、库存算法。

---

## 3. 项目证据映射：京东物流 算法开发（#1）

| JD 要求 | 你现在的证据 | 缺口 | 动作 |
|---|---|---|---|
| 路径规划 | 项目有 dispatch/wave/routing 相关模块 | 大规模 VRP/时窗经验不足 | 做一个 100–500 点 VRPTW benchmark |
| 动态调度 | 日级 rolling + recovery | 实时调度/异常恢复证据弱 | 用 rolling + re-optimization 做 30 seeds |
| 网络优化 | DC 布点 + joint MILP | 网络规模小 | 做 3 DC → 10 DC 扩展实验 |
| LP/IP/启发式 | CP-SAT/MILP | 缺 LP 对偶/敏感性 | 加 LP relaxation + dual/shadow price |
| Gurobi/CPLEX | 目前 OR-Tools | 缺商业求解器 API | 用 Gurobi 免费版跑同一模型 |
| Python + Java/Go/C++ | Python 强 | Java/C++ 弱 | 选 Java，刷基础 + 写一个小 solver |
| SQL | pandas 为主 | SQL 工程证据弱 | 用 DuckDB/SQL 重写数据层 |
| ML | LightGBM/回测 | 预测指标不是决策指标 | 加决策指标：OTIF/成本/积压 |
| LLM 必须了解 | Agent v2/RAG 有基础 | 无生产 LLM 证据 | 了解 API/eval，不深挖训练 |
| 3+ 年 | 项目 + 测试/CI | 年限硬缺口 | 校招/初级岗；社招需内推 |

**结论**：技术方向匹配，但 **年限 + 求解器 + Java/C++ + SQL + 路径/调度 domain** 是硬缺口。

---

## 4. 项目证据映射：京东物流 运筹优化/ML（#2）

| JD 要求 | 证据 | 缺口 |
|---|---|---|
| 网点选择/配送范围 | DC 布点/分配 | 末端网点粒度不足 |
| 任务调度 | rolling/recovery | 快递员级调度没有 |
| ETA | 项目有 transit/arrival | ETA 模型没有 |
| Spark/Flink | 无 | 需补概念 + demo |
| C++/Java/Python | Python | 需补一门 |
| 3 年 OR | 项目 | 年限 |

**结论**：比 #1 更偏末端履约；如果你补一个 **ETA + 任务调度** 小模块，匹配度会上升。但不要再加新大模块。

---

## 5. 项目证据映射：Amazon Data Scientist SCOT（#17）

| JD 要求 | 证据 | 缺口 |
|---|---|---|
| SQL | pandas | 补 SQL |
| Python | 强 | OK |
| ML/统计 | LightGBM/回测 | OK |
| forecasting/buying/placement/inventory | 项目全链路 | 强 |
| 业务影响 | OTIF/成本 | 需要更清楚的 business narrative |
| 2+ 年 | 项目 | 年限 |

**结论**：这是硕士最现实的 Amazon 入口；但地点/签证/英语要评估。

---

## 6. 技能补齐顺序（只补缺口）

| 优先级 | 技能 | 目标 | 时间 |
|---:|---|---|---|
| 1 | Gurobi/CPLEX | 跑通同一 MILP，输出 dual/shadow price | 1 周 |
| 2 | SQL | 用 SQL 重写数据层，能讲窗口函数/聚合 | 1 周 |
| 3 | Java 或 C++ | 基础语法 + 数据结构 + 一个小 solver | 3 周 |
| 4 | 路径/调度 | VRPTW / rolling dispatch benchmark | 2 周 |
| 5 | Spark/Flink | 概念 + 本地 demo | 3 天 |
| 6 | LLM/Agent | API + eval 概念，不做训练 | 3 天 |

---

## 7. 8 周执行表

| 周 | 产出 | 验收 |
|---|---|---|
| W1 | 20 个 JD 表 + 简历初稿 | 每个岗位有链接/要求/差距 |
| W2 | Gurobi/CPLEX 对比 | 同一模型，dual/shadow price |
| W3 | SQL 数据层 | 不依赖 pandas 也能跑 |
| W4 | VRPTW/调度 benchmark | 100+ 点，30 seeds |
| W5 | 项目 README 改成 OR 叙事 | 一页能讲清问题/模型/结果 |
| W6 | 简历终稿 + 项目一页纸 | 针对 #1/#2/#17 三版 |
| W7 | 投 30 家 + 2 内推/家 | 投递表 |
| W8 | OR/ML/案例面试 | mock 3 次 |

---

## 8. BOSS 直聘怎么用

BOSS 抓不了，不爬。每天手动 10 分钟：

1. 搜：`供应链算法`、`运筹优化`、`物流算法`、`调度算法`、`库存算法`、`履约算法`；
2. 城市：北京/上海/杭州/深圳/广州；
3. 筛：校招/1–3 年/硕士；
4. 保存 5–10 个 JD，填入本表；
5. 官网/内推投递，BOSS 只用来聊天确认 HC。

---

## 9. 一句话

**你的主线不是“再学一个技术”，而是把现有项目变成“京东物流算法开发”能追问 30 分钟的 OR 案例。**

先补：**Gurobi/CPLEX、SQL、Java/C++、路径/调度**。  
不要再加：Agent、RL、TSFM、更多预测模型。
