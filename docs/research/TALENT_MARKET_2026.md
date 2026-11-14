# 2026 供应链算法 / 运筹优化招聘市场扫描

日期：2026-11-15  
范围：供应链算法、运筹优化、决策科学、库存/网络/履约优化  
方法：Amazon Jobs、NVIDIA 官方 JD、京东招聘官方 API、腾讯招聘官方 API；阿里/字节/美团/拼多多入口做定性补充。  
说明：这是**岗位需求信号**，不是劳动力市场普查；岗位数量会随招聘周期变化。

---

## 0. 一句话结论

供应链算法市场最缺的不是“会调模型”的人，而是：

> **能把业务问题写成优化模型，能用 ML 处理不确定性，能把解放进生产系统的人。**

具体是三类组合：

1. **OR + ML + 生产**：LP/MIP、随机/鲁棒优化、预测、Python/Java/C++；
2. **OR + 供应链 domain**：库存、网络、履约、运输、BOM/产能；
3. **OR + 因果/实验**：策略评估、A/B、准实验。

AI/Agent 不是这个岗位族的主线；在这个方向里，AI 只是工具。

---

## 1. 官方岗位快照

### Amazon（官方搜索 API）

| 搜索词 | 命中岗位数 | 说明 |
|---|---:|---|
| supply chain optimization | 134 | 供应链优化大类 |
| inventory optimization | 45 | 库存/补货/计划 |
| fulfillment optimization | 42 | 履约/分单/网络 |
| demand planning scientist | 19 | 预测/计划 |
| supply chain scientist | 3 | 精确标题少，更多藏在 Applied Scientist 里 |
| operations research scientist | 1 | 标题少，不代表需求少 |

这说明：**OR 岗位不总叫“Operations Research”**，更多叫 Applied Scientist / Data Scientist / Optimization / Decision Science。  
搜标题会低估需求，应该搜技能。

### NVIDIA

代表岗位：

- [Modeling Engineer, Supply Chain Optimization (JR2025602)](https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/US-CA-Santa-Clara/Modeling-Engineer--Supply-Chain-Optimization_JR2025602)

要求重点：

- 定量硕士/博士，或同等经验；
- **8+ 年**建模/工程/数据科学经验；
- 强 LP/MIP：目标、约束、dual variables；
- duality、shadow price、sensitivity、degeneracy、数值条件、solver 行为；
- MATLAB/Julia/R/Python；
- 供应链：BOM、产能、lead time、yield、分配、多期计划；
- 加分：Gurobi/CPLEX、半导体/电子供应链、cuOpt/GPU 加速。

这是“运筹建模深度”最高的 JD 之一，不是调包岗。

---

## 2. 最核心的五类岗位

### 2.1 Applied Scientist, Supply Chain Optimization（Amazon SCOT）

代表：

- [Applied Scientist, SCOT Specialized Selection](https://www.amazon.jobs/en/jobs/10537551)
- [Applied Scientist, Modeling and Optimization](https://www.amazon.jobs/en/jobs/10540608)
- [Applied Scientist, SCOT FO - SnT](https://www.amazon.jobs/en/jobs/10556295)

典型要求：

- **PhD，或 Master + 4 年**；
- 顶会/期刊论文或专利；
- Python/Java/C++；
- 数值优化、算法、数据挖掘、分布式/HPC 之一；
- 业务建模：库存、选品、履约、网络；
- 生产级科学代码。

**信号**：这是供应链算法最核心的岗位族，也是你当前项目最匹配的方向。  
**难点**：论文、年限、生产影响，不是“项目完整”就能过。

### 2.2 Senior Applied Scientist, Optimization（Amazon SCOT / Fulfillment）

代表：

- [Senior Applied Scientist - Optimization, Fulfillment Planning](https://www.amazon.jobs/en/jobs/10559787)
- [Senior Applied Scientist, Strategic Sourcing](https://www.amazon.jobs/en/jobs/10569174)

典型要求：

- **PhD in OR / Statistics / Applied Math / Engineering / CS**；
- 5+ 年 LP/非线性优化；
- 随机优化、库存控制、RL/因果之一；
- 复杂问题建模、算法设计、复杂度分析；
- 带团队/带新人。

**信号**：这是 Senior/Principal 路线；对硕士应届不现实，但可以作为技术路线图。

### 2.3 Data Scientist, SCOT

代表：[Data Scientist, SCOT RoW Tech](https://www.amazon.jobs/en/jobs/10554991)

典型要求：

- 2+ 年 data scientist；
- SQL/Python/R；
- ML/统计建模、参数影响；
- 把理论模型应用到业务环境；
- 业务：forecasting、buying、placement、inventory health。

**信号**：这是硕士更现实的入口。  
**关键差异**：它不要求顶会论文，但要求 SQL、业务指标、跨团队沟通。

### 2.4 Optimization / Modeling Engineer（NVIDIA 及制造业）

代表：NVIDIA JR2025602。

典型要求：

- LP/MIP 建模深度；
- 对偶、敏感性、数值稳定性；
- 供应链 domain（BOM、产能、lead time、yield）；
- 生产级模型维护。

**信号**：这是“运筹 + 工程 + domain”的岗位；比纯算法更看重建模正确性和可解释性。

### 2.5 Research Scientist, Causal / Experimentation

代表：[Research Scientist, SCOT First Inbound](https://www.amazon.jobs/en/jobs/10593798)

典型要求：

- PhD；
- 因果建模、A/B、准实验、潜在结果；
- ML/统计；
- 策略仿真与评估。

**信号**：这是供应链策略评估的高端岗位；不是“跑回归”，而是识别因果效应。

---

## 3. 市场最缺什么

### 3.1 OR + ML + 生产

岗位要的不是：

- 只会调 LightGBM；
- 只会调 Gurobi；
- 只会写 notebook。

而是：

- 能把补货/分单/网络问题写成 LP/MIP/随机规划；
- 能解释 dual、sensitivity、约束；
- 能用 ML 做预测/场景；
- 能把模型放进生产，控制时延、失败率、成本。

这类人比纯 ML 和纯 OR 都少。

### 3.2 供应链 domain

JD 反复出现：

- inventory、placement、fulfillment、network；
- transportation、last mile、middle mile；
- BOM、capacity、lead time、yield；
- forecasting、planning、sourcing。

**domain 不是加分项，是硬门槛。**  
只会通用 ML、不懂库存/网络的人，面试很难讲深。

### 3.3 因果 / 实验

Amazon Research Scientist 明确要：

- causal modeling、A/B、quasi-experiment；
- 策略评估，而不是相关性。

这是供应链策略岗位的稀缺技能。

### 3.4 生产工程能力

- Python/Java/C++；
- SQL；
- 分布式/HPC；
- 求解器工程；
- 代码审查、上线、监控。

很多 OR 候选人卡在“模型能写，系统上不了”。

---

## 4. 岗位技能矩阵

| 岗位族 | 必备 | 加分 | 你当前差距 |
|---|---|---|---|
| Applied Scientist SCOT | 优化、ML、Python、论文 | 供应链、生产、C++/Java | 论文、年限、生产规模 |
| Data Scientist SCOT | SQL/Python、ML/统计、业务 | 因果、实验、OR | SQL/业务指标表达 |
| Optimization Engineer | LP/MIP、dual、domain | Gurobi/CPLEX、GPU | 对偶/敏感性、行业 domain |
| Research Scientist | PhD、因果/实验、ML | 策略仿真 | 因果识别、PhD |
| OR Analyst / Manager | OR、业务、沟通 | 网络/库存 | 业务落地经验 |

---

## 5. 对 985 本硕的现实判断

### 不建议直接瞄准

- Senior/Principal Applied Scientist：PhD + 5–10 年硬门槛；
- NVIDIA Modeling Engineer：8+ 年 + 半导体 domain；
- Research Scientist：PhD + 因果研究经历。

### 可以瞄准

- **Data Scientist, SCOT**：硕士 + 强项目 + SQL/业务表达；
- **Applied Scientist I**：硕士 + 论文/强项目（部分公司接受）；
- **国内供应链算法 / 运筹优化算法工程师**：京东物流、阿里/菜鸟、美团、拼多多、字节电商更匹配；
- **OR Analyst / Decision Scientist**：企业计划、网络、库存方向。

### 最现实的定位

> **Decision-centric Applied Scientist / Algorithm Engineer**  
> 不是“通用 AI 研究员”，而是“能把不确定性、优化、业务指标接起来的人”。

---

## 6. 市场偏好 → 项目主线

市场证据支持的不是“再加 Agent/RL”，而是：

> **可验证的决策质量：不确定性 → 服务水平 → 成本。**

对应技术主线：

- Conformal risk control / DRO；
- 两阶段库存/布点/分单；
- 30 seeds；
- price of robustness；
- 业务指标：OTIF、成本、积压、尾部风险。

Agent、RL-0、TSFM 保留为工具/附录，不再扩主线。

---

## 7. 12 周证明计划（供应链算法版）

| 周 | 产出 | 对应岗位信号 |
|---|---|---|
| W1–2 | conformal risk constraint + 形式化 | Applied Scientist / OR |
| W3–4 | 两阶段 CVaR/risk-controlled 模型 | SCOT / MOP |
| W5–6 | 真实回测 + 漂移模拟 | Data Scientist |
| W7–8 | 30 seeds + price of robustness | 生产影响 |
| W9–10 | 一页 paper + 3 图 | 论文/面试 |
| W11–12 | 简历/面试叙事 + 代码清理 | 投递 |

---

## 8. 国内公司：实际 JD 信号

### 8.1 京东（官方招聘 API，2026-11 快照）

京东是这次能拿到**完整 JD 原文**的国内样本，且物流/零售场景和你的项目最接近。

| 岗位 | 部门/日期 | 关键要求 | 信号 |
|---|---|---|---|
| [算法开发](https://zhaopin.jd.com/web/job-info-detail?requementId=227467) | 京东物流 · 快快规划算法组 · 2026-11-03 | 路径规划、动态调度、负载均衡、网络优化；3+ 年；硕士优先；Python + Java/Go/C++；LP/IP/启发式；Gurobi/CPLEX；SQL；ML；LLM 必须了解，Agent 加分 | **最匹配的国内 OR 岗** |
| [运筹优化/机器学习算法工程师](https://zhaopin.jd.com/web/job-info-detail?requementId=225705) | 京东物流 · 2026-09-23 | 硕士 + 3 年 OR；网点选择、配送范围、任务调度、ETA；Spark/Flink；C++/Java/Python；物流/外卖优先 | OR + ML + 末端履约 |
| [供应链AI算法工程师](https://zhaopin.jd.com/web/job-info-detail?requementId=227618) | 京东零售 · 2026-11-10 | 大模型后训练、Agent 架构、补货/定价/调拨；AI 为主 | AI-heavy，不是纯 OR |
| 供应链规划 / 网络规划 | 京东物流/健康 · 2026-10/11 | 仓网规划、库存布局、SQL/Excel、运营指标；不一定写代码 | domain/analytics，不是算法研发 |

**关键发现**：

- 国内 OR 岗常叫 **“算法开发/算法工程师”**，不叫 Operations Research；
- 京东物流的“算法开发”明确写：**运筹优化 + 路径/调度/网络 + Gurobi/CPLEX + Python/Java/C++ + SQL + ML**；
- 同一岗位也写：**必须了解 LLM 原理/API，Agent 是加分项**。  
  这说明国内 OR 岗不是“不许碰 AI”，而是 **AI 是辅助技能，OR 是核心**；
- 纯“供应链规划”更偏业务/数据分析，不是建模研发。

### 8.2 腾讯（官方招聘 API）

腾讯公开 API 里，供应链相关岗位更多是运营/安全，不是零售供应链算法。可参考的 OR 相邻岗：

- **AI for Systems 算法工程师（智能调度与性能优化）**，TEG，2026-11-05  
  资源调度、容量规划、运筹优化/启发式/ML、Python；是云资源调度，不是供应链。
- **供应链效率优化经理**，2026-10-20  
  更偏运营管理，不是算法研发。

**信号**：不是所有大厂都有“零售供应链算法”；**电商/物流公司（京东、阿里/菜鸟、美团、拼多多、字节电商）才是主战场**。

### 8.3 阿里 / 字节 / 美团 / 拼多多 / 菜鸟 / 顺丰

这些公司的官方入口：

- 阿里：https://talent.alibaba.com/
- 字节：https://jobs.bytedance.com/
- 美团：https://zhaopin.meituan.com/
- 京东：https://zhaopin.jd.com/
- 华为：https://career.huawei.com/

这些站点的岗位检索依赖登录/JS/风控，当前环境拿不到稳定的机器可读 JD；本报告**不伪造**它们的岗位原文。  
从公开岗位结构看，常见标题仍是：

- 供应链算法工程师
- 运筹优化算法工程师
- 履约/配送算法工程师
- 库存/补货算法工程师
- 决策智能算法工程师

### 8.4 国内 JD 的共性

1. **3+ 年经验**很常见，硕士优先；应届要投“校招/初级算法”，不要拿社招 3 年岗硬套；
2. **Python + Java/Go/C++**，不是只会 Python；
3. **SQL + Spark/Flink** 是物流大数据岗的硬要求；
4. **OR 理论 + Gurobi/CPLEX + 业务建模** 是核心；
5. **LLM/Agent 正在变成 OR 岗的“必须了解/加分”**，但不会替代 OR；
6. 国内更看 **项目落地/业务指标**，论文是加分，不是唯一门槛（研究型岗位除外）。

---

## 9. 结论

**最热**：供应链优化、履约/网络、库存/计划。  
**最缺**：OR + ML + 生产、供应链 domain、因果/实验、求解器工程。  
**国内主战场**：京东物流、阿里/菜鸟、美团、拼多多、字节电商；不是所有大厂都有零售供应链算法。  
**最适合你**：不是追 AI 热点，而是占住 **OR + ML + 可验证决策** 这个交集。

一句话：

> 企业不缺会讲 AI 的人，缺的是**能把库存/网络/履约问题写成优化模型、证明服务水平、并上线的人**。  
> 国内 JD 也证明了这一点：OR 是核心，LLM/Agent 只是加分/必须了解的辅助项。
