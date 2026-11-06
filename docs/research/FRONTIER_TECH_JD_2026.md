# 前沿技术扫描与岗位 JD 调研（2026-11）

面向：供应链决策、运筹优化、Agent / Applied Scientist 方向  
调研日期：2026-11-06

这份调研只回答三个问题：

1. 现在什么技术算前沿，什么只是成熟工程；
2. 前沿岗位的 JD 到底要什么；
3. 当前项目最值得补哪一块，才能从“完整”变成“有技术纵深”。

---

## 1. 结论先行

1. **2026 年的前沿不是某个单点模型，而是“在不确定性下做决策，并能验证决策”的系统。**  
   LightGBM、CP-SAT、RAG、Prompt Chain 都是成熟工程，不是前沿。

2. **JD 里最值钱的组合是：优化 + 机器学习 + 不确定性 / 因果 / RL + 生产落地。**  
   Amazon SCOT、NVIDIA 供应链优化、OpenAI Agent 岗位都指向这个组合，而不是“会调一个大模型”。

3. **前沿岗位分两类：**
   - 研究型：PhD、论文、RL / post-training / causal / decision-focused learning；
   - 应用型：Master/PhD，能建模、能写生产代码、能拿业务指标。

4. **对 985 本硕，最现实的差异化不是“再做一个完整系统”，而是“在一个点上做到可辩护”。**  
   当前项目已经证明了工程完整度；下一步应该补一个方法层 contribution。

5. **最推荐补的方向：Conformal Prediction + CVaR / 两阶段随机优化。**  
   它和现有预测、库存、分单链路天然咬合，能讲清楚数学保证、baseline、ablation 和业务指标，投入产出比最高。

---

## 2. 调研范围与方法

调研对象分三组：

- 前沿技术：2024–2026 年的论文、官方工程博客、开源模型；
- 岗位 JD：Amazon、NVIDIA、OpenAI 的官方招聘页面 / 招聘 API；
- 国内岗位：公开岗位的共性画像，不冒充某一封 JD 的逐字原文。

说明：

- JD 会随招聘周期变化，链接和日期以抓取时为准；
- “匹配度”按当前项目能讲出来的证据判断，不是面试结论；
- “前沿”按研究前沿、早期生产、成熟生产分层，不按营销词汇分层。

---

## 3. 技术分层：什么真前沿，什么只是成熟

| 技术 | 2026 状态 | 供应链里的用法 | JD 信号 | 难度 | 建议 |
|---|---|---|---|---|---|
| Agentic AI / tool-using agents | 早期生产 | 规划、调用工具、校验、失败重规划 | 极强 | 中高 | 值得做，但要做可靠性评测 |
| Test-time compute / reasoning | 研究转产品 | 复杂排程、约束推理、多步决策 | 强 | 高 | 适合当 Agent 内核，不适合单独讲故事 |
| 时序基础模型（TSFM） | 早期生产 / pilot | 零样本预测、稀疏 SKU、概率预测 | 中强 | 中 | 适合做一章 ablation |
| Decision-focused learning | 研究前沿 | 预测直接优化下游库存/分单成本 | 中 | 高 | 研究型，风险高 |
| Conformal prediction / UQ | 早期生产 | 需求区间、服务水平、鲁棒约束 | 中 | 中 | **最推荐** |
| 随机 / 鲁棒 / CVaR 优化 | 成熟生产 | 库存、网络、分单、履约 | 极强 | 中 | 必须补 |
| Offline RL / 序贯决策 | 研究 / pilot | 补货、定价、动态分配 | 中 | 高 | 可选，数据要求高 |
| 因果推断 / A-B 实验 | 成熟生产 | 促销、履约策略、网络调整 | 强 | 中 | 有业务实验再加 |
| Digital twin / 离散事件仿真 | 成熟生产 | 仓网、波次、发车 | 强 | 中 | 已有，继续用 |
| Graph neural networks | 早期 | 网络关系、SKU 关联 | 弱 | 中 | 不必硬加 |
| 量子优化 | 研究 / 炒作 | 组合优化理论 | 极弱 | 极高 | 不建议碰 |
| Embodied AI / 仓储机器人 | 早期生产 | 拣选、搬运、AMR | 强但独立 | 高 | 另一个赛道 |

### 一句话版本

- **Tier S（研究前沿）**：Agent post-training / computer use、RL reasoning、decision-focused learning、TSFM。
- **Tier A（前沿边缘、可落地）**：Conformal + stochastic optimization、Agent verifier / replan、causal + experimentation。
- **Tier B（成熟但值钱）**：LP/MIP、LightGBM、DES、RAG。
- **Tier C（不要碰）**：供应链量子优化、没有工具的“AI 大脑”、纯 Prompt 堆叠。

---

## 4. 五条最值得关注的技术线

### 4.1 Agentic AI：从“会聊天”到“会执行、会验证”

OpenAI 的 Agent Post-Training 岗位把方向写得很清楚：训练模型操作电脑、浏览器、桌面、工具，处理长程任务，做 evals、graders、reward signal、synthetic data、multi-agent coordination。关键不是“接一个大模型”，而是：

- 工具调用是否可靠；
- 失败能否被发现；
- 长程任务能否保持状态；
- 评测是否可复现；
- 成本、延迟、false success 是否可接受。

Anthropic 的工程文章把 workflow 和 agent 区分开：workflow 是预定义代码路径，agent 是模型自己决定流程。多数业务不需要 agent，只有开放、步骤不可预知、需要环境反馈的任务才需要。

> 对你的项目：现在的 Plan DAG + Verifier + Replan 是对的方向，但默认 planner 是脚本，30 个任务也太小。要变成前沿证据，需要真实 LLM、更多任务、多模型方差、成本/延迟、对抗输入。

### 4.2 时序基础模型：零样本预测进入可用区间

三类代表工作：

- **Chronos**：把时间序列缩放、量化成 token，用 T5 类模型做概率预测；42 个数据集上零样本接近或超过专门训练的模型（arXiv:2403.07815）。
- **TimesFM**：decoder-only 的 patched attention，在大量时序上预训练，零样本接近监督模型（arXiv:2310.10688）。
- **Moirai**：在 27B+ 观测的 LOTSA 上预训练，统一跨频率、多变量预测（arXiv:2402.02592）。

它们的价值不是“一定比 LightGBM 准”，而是稀疏 SKU、短历史、冷启动、概率预测和减少逐数据集调参。

> 对你的项目：拿 Chronos-Bolt / TimesFM 和现有 LightGBM 做零样本对比，成本不高。但大概率是 mixed result，适合做诚实 ablation，不适合当主线。

### 4.3 Decision-focused learning：预测为决策服务

传统做法是“先把预测做准，再优化”。Decision-focused learning 直接优化下游决策损失：

- Donti 等（NIPS 2017）在库存补货、电网调度、储能套利上证明，任务导向的端到端学习可以优于“先预测再优化”（arXiv:1703.04529）。
- 2026 年这个方向仍然活跃，应用扩展到电池调度、EV 路径、微网等。

> 对你的项目：这是最研究型的升级，但实现难、复现难、收益不稳定。除非你准备读论文、做凸优化层或 SPO+，否则不要一上来就选它。

### 4.4 Conformal + 随机优化：最值得补的前沿边缘

Conformal prediction 给的是分布无关、非渐近的覆盖率保证：给定 90% 目标，构造出来的区间在可交换性假设下至少覆盖 90% 真值，不需要假设误差服从正态分布（arXiv:2107.07511）。

在供应链里可以这样用：

1. 对每个 SKU / 仓库做 rolling-origin 回测，得到残差；
2. 用 split conformal 或 CQR 校准 80/90/95% 区间；
3. 用区间/残差生成需求场景；
4. 做两阶段随机库存/分单，或 CVaR 鲁棒优化；
5. 比较：点预测 + 安全系数、确定性 MILP、robust box、stochastic / CVaR。

为什么它适合你：

- 现有项目已有 Week-14 两阶段 CVaR 布点，但场景是过去 6 周等权、总量已知；缺的是校准场景和与 allocation 的联合优化；
- 数学上能讲清楚 coverage guarantee；
- 业务上能讲“同样服务水平下库存/积压/尾部缺货”；
- 评测上能做 30 seeds、ablation、oracle gap；
- 不需要 GPU，不需要重写系统。

### 4.5 因果、RL、Digital Twin：大厂 JD 的第二层

Amazon 的 SCOT 岗位把第二层写得很直白：

- Research Scientist, SCOT First Inbound：PhD；因果建模、A/B 测试、准实验、ML/统计；
- Senior Applied Scientist, Strategic Sourcing：PhD OR；库存控制、随机优化、RL、因果推断；
- Senior Applied Scientist, Optimization：PhD OR；LP/NLP、大规模优化、生产落地。

这说明：预测只是入口，真正的前沿在“决策 + 因果 + 序贯 + 仿真”。你的 DES 已经是 digital twin 的雏形，但还没有和因果/RL 结合。

---

## 5. JD 拆解

### 5.1 Amazon：Applied Scientist, SCOT, Specialized Selection

- 地点：Bellevue, WA
- 发布：2026-09-11
- 链接：https://www.amazon.jobs/en/jobs/10537551

关键要求：

- 3+ 年业务建模经验；
- **PhD，或 Master + 4 年** CS/CE/ML 相关经验；
- 顶会/期刊论文或专利；
- Java / C++ / Python；
- 算法、数值优化、数据挖掘、分布式/高性能计算之一。

岗位内容：在 SCOT 里做 assortment / selection，用 ML + optimization 在有限仓容下选品，服务最快履约、生鲜等场景。

**信号**：这是 ML + OR + 业务的典型 Applied Scientist，不是纯算法岗。  
**匹配度**：你的项目有 ML + OR + 真实数据，但缺论文、缺 4 年经验；适合作为 2–3 年后的目标，或先走 Data Scientist / Algorithm Engineer。

### 5.2 Amazon：Senior Applied Scientist - Optimization, Fulfillment Planning

- 地点：Bellevue, WA
- 发布：2026-09-24
- 链接：https://www.amazon.jobs/en/jobs/10559787

关键要求：

- 5+ 年应用研究；
- **PhD in OR / Statistics / Applied Math / Engineering / CS**；
- 5+ 年 LP / 非线性优化；
- 复杂问题建模、算法设计、复杂度分析；
- 带团队、带新人。

岗位内容：SCOT 的 FPX Science，做全球履约计划与执行、运输网络优化。

**信号**：这是 Senior/Principal 路线，PhD + 多年经验是硬门槛。  
**匹配度**：技术方向高度匹配（MILP、网络、履约），但资历不匹配；不要用它当应届目标。

### 5.3 Amazon：Senior Applied Scientist, Strategic Sourcing Science

- 地点：Bellevue, WA
- 发布：2026-10-05
- 链接：https://www.amazon.jobs/en/jobs/10569174

关键要求：

- 5+ 年应用研究；
- **PhD OR / Applied Math / TCS + 5 年工业经验**；
- 供应链管理、库存控制、**随机优化**；
- 数学优化、**因果推断**、随机建模、**序贯决策**之一；
- 生产级科学代码；
- 论文加分。

岗位内容：全球寻源与 inbound flow，优化库存来源、供应商策略、入仓路径。

**信号**：这是 OR + 库存 + RL/因果的复合岗位，和你的库存/分单链路最接近。  
**匹配度**：方向最接近，但 Senior 门槛高；可以作为技术路线图，不是投递目标。

### 5.4 Amazon：Research Scientist, SCOT First Inbound

- 地点：New York, NY
- 发布：2026-10-30
- 链接：https://www.amazon.jobs/en/jobs/10593798

关键要求：

- **PhD** in engineering / CS / ML / robotics / OR / statistics / math；
- 定量研究经验；
- Python / Java / C++；
- 加分：因果图模型、贝叶斯网络、潜在结果、A/B 测试、准实验、ML/统计/深度学习。

岗位内容：SCOT inbound placement / capacity management，设计新策略、做仿真、评估效果。

**信号**：研究型岗位，因果推断是明确加分项。  
**匹配度**：你的 DES 可以对应策略仿真，但缺因果识别和 PhD 研究经历。

### 5.5 NVIDIA：Modeling Engineer, Supply Chain Optimization

- 地点：Santa Clara, CA
- 发布：2026-10-30
- 链接：https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/US-CA-Santa-Clara/Modeling-Engineer--Supply-Chain-Optimization_JR2025602

关键要求：

- 定量领域硕士/博士，或同等经验；
- **8+ 年**高教/建模/工程/数据科学经验；
- 强 LP / MIP 建模：目标函数、约束、dual variables；
- 约束优化数学基础：duality、shadow price、sensitivity、degeneracy、数值条件、solver 行为；
- MATLAB / Julia / R / Python；
- 供应链建模：BOM、产能、lead time、yield、分配、多期计划；
- 加分：Gurobi / CPLEX、半导体/电子供应链、NVIDIA cuOpt / GPU 加速优化。

岗位内容：维护和扩展生产级 LP 模型，把晶圆、封装、PCB、功率器件等约束转成数学模型，分析 shadow price，支持高层规划、采购、供应商谈判。

**信号**：这是运筹建模深度最高的 JD 之一，强调 dual/sensitivity，不是调包。  
**匹配度**：你的 CP-SAT/MILP 经验能对上建模，但缺 LP 对偶分析、8 年经验、半导体 domain。  
**启发**：如果走 OR 路线，应该补 LP 对偶、敏感性分析、生产级建模，而不是再加一个预测模型。

### 5.6 OpenAI：Agent Post-Training, Computer Use Research

- 地点：San Francisco
- 发布：2026-10-19
- 链接：https://jobs.ashbyhq.com/openai/34c2ed3f-840f-4a68-9a00-0a0606660abf

关键要求：

- ML / 软件工程 / 系统 / 统计强基础；
- 实操经验：LLM、RL、RLHF/RLAIF、post-training、evals、graders、synthetic data、coding agents、tool-using agents、production ML；
- 能把模糊行为问题转成假设、实验、分析；
- 关注产品影响、agent 的可靠性/诚实性/可用性；
- 跨研究、产品、基础设施、数据、评测、安全协作。

岗位内容：训练模型操作电脑、浏览器、桌面，做长程任务、多智能体协作、factuality、calibration、tool use。

**信号**：这是前沿 Agent 研究岗位，不是 Prompt Engineer。  
**匹配度**：你的 Agent v2 是很好的种子，但缺真实 LLM 训练/评测、规模、post-training 经验。  
**启发**：如果走 AI 路线，应该把 verifier + replan + eval 做成可复现的 agent reliability benchmark，而不是再堆工具。

### 5.7 JD 对比总结

| 岗位 | 核心能力 | 前沿信号 | 你现在的差距 |
|---|---|---|---|
| Amazon SCOT Applied Scientist | ML + OR + 业务 | 大规模选品/库存 | 论文、年限 |
| Amazon Senior Optimization | PhD OR + LP/NLP | 全球履约网络 | 资历、对偶/大规模 |
| Amazon Strategic Sourcing | OR + 库存 + 随机/RL/因果 | 寻源与 inbound | 随机优化、因果、资历 |
| Amazon Research Scientist | PhD + 因果/实验 | 策略仿真与因果 | 因果、PhD |
| NVIDIA Modeling Engineer | LP/MIP + dual + 供应链 | 生产级优化模型 | 对偶分析、domain |
| OpenAI Agent Post-Training | LLM/RL/post-training/evals | 前沿 agent | 真实 LLM、规模、训练 |

**共同点**：

- Python/Java/C++ 是底线；
- 优化不是“会调 solver”，而是能写目标/约束、解释对偶、做敏感性；
- ML 不是“会调包”，而是能设计实验、评估、上线；
- 研究岗看论文，应用岗看生产影响；
- Agent 岗看 evals / reliability，不看 Prompt 花活。

---

## 6. 国内岗位画像（不是逐字 JD）

国内大厂的岗位名通常是：

- 供应链算法工程师
- 运筹优化算法工程师
- 决策智能算法工程师
- 履约/配送算法工程师
- 大模型 Agent 算法工程师

公开岗位的共性要求：

| 公司类型 | 常见岗位 | 关键词 | 官方入口 |
|---|---|---|---|
| 阿里 / 淘天 / 菜鸟 | 供应链算法、运筹优化 | 库存、补货、网络规划、LP/MIP、ML | https://talent.alibaba.com/ |
| 字节 / 抖音电商 | 供应链算法、履约算法 | 履约、分单、时效、因果、RL、LLM | https://jobs.bytedance.com/ |
| 美团 | 配送 / 供应链算法 | 路径、调度、仿真、OR + ML | https://zhaopin.meituan.com/ |
| 京东 / 物流 | 供应链算法、库存算法 | 补货、仓网、库存、OR + ML | https://zhaopin.jd.com/ |
| 华为 | 供应链算法 / 运筹 | 计划、排产、网络、OR + ML | https://career.huawei.com/ |

上表是岗位画像，不是某一封 JD 的原文；具体以官网为准。国内面试通常更强调：

- 业务建模：能不能把补货/分单/履约讲成数学问题；
- 工程：Python/Java、SQL、Spark、在线服务；
- 优化深度：LP/MIP、对偶、敏感性、启发式；
- ML/LLM：不只看 AUC/WMAPE，看决策指标；
- 论文/竞赛：顶会、INFORMS、数学建模、Kaggle 是加分。

---

## 7. 当前项目的 gap 分析

### 已经很强的部分

- 真实数据 + 端到端链路：预测 → 库存 → 布点 → 分单 → 波次 → 发车；
- OR + ML 结合：LightGBM、CP-SAT、MILP、DES；已有 Week-14 两阶段 CVaR 布点（`stochastic.py`）和 Week-13 joint MILP（`joint.py`）；
- 评测纪律：30 seeds、baseline、OTIF/成本/积压；
- Agent 工程：Plan DAG、Verifier、Replan、false success 统计；
- 可复现：345 tests、CI、Dockerfile、benchmark JSON。

这些在 985 本硕项目里已经不差，说明能交付。

### 会被前沿岗位追问的部分

| 缺口 | 面试官会怎么问 | 当前回答的风险 |
|---|---|---|
| 没有概率预测 / UQ | 安全库存怎么定？覆盖率怎么保证？ | “乘 1.4/1.6”像拍脑袋 |
| 随机场景未校准 | 场景从哪来？覆盖率怎么保证？ | 已有 CVaR 布点，但场景=历史周等权、未联合 allocation |
| 两层分解 | 为什么不做联合优化？ | 知道不是最优，但没量化 gap |
| Agent 默认脚本 planner | 这算 Agent 吗？真实 LLM 呢？ | 容易被质疑规则引擎 |
| 30 个任务 | 统计显著性？多模型方差？ | 样本太小，难以下结论 |
| 单数据集 / 单周 | 外部有效性？ | 只能算 case study |
| 没有论文 / 因果 | 研究贡献是什么？ | 工程强，研究弱 |

---

## 8. 推荐路线：一个前沿楔子，不是一堆模块

### 方案 A（首选）：Conformal + CVaR 随机库存/分单

**研究问题**：在分布无关的不确定性集合下，库存/分单的 service-cost 前沿能否优于“点预测 + 安全系数”？

**实现**：

1. 用现有 rolling-origin 回测，按时间切 calibration / test；
2. 对 200 个主 SKU 做 split conformal / CQR，目标 coverage 80/90/95%；
3. 用残差 / 区间生成需求场景，做 scenario reduction；
4. 两阶段随机 MILP 或 CVaR 鲁棒模型：第一阶段库存/布点，第二阶段分单/缺货；
5. 对比：point + safety factor、deterministic MILP、robust box、stochastic / CVaR；
6. 评估：coverage、interval width、OTIF、成本、积压、最坏场景、oracle gap；
7. 30 seeds + ablation：conformal vs 正态假设、scenario 数、CVaR α。

**可写的 claim**：

> 在相同目标 OTIF 下，conformal-CVaR 将积压/库存降低 X%，尾部缺货降低 Y%，且经验覆盖率与目标偏差小于 Z 个百分点。

**为什么适合你**：不需要重写系统；数学清楚；和现有库存/分单直接咬合；面试可深挖。

### 方案 B（研究型）：Decision-focused learning

把预测模型训练目标从 WMAPE 换成下游库存/分单成本，用 SPO+ / 可微优化 / 黑盒梯度。

- 优点：研究信号强；
- 缺点：实现难、收益不稳定、需要论文阅读和凸优化基础；
- 建议：除非准备投入 2–3 个月，否则不要作为第一优先。

### 方案 C（低成本）：TSFM 零样本对比

Chronos-Bolt / TimesFM / Moirai 零样本 vs LightGBM / Seasonal Naive：

- SKU 级 WMAPE；
- 仓库总量 WMAPE；
- 概率指标：CRPS、coverage；
- 稀疏 SKU / 冷启动子集；
- 推理成本。

**预期**：大概率 mixed result。不要怕 negative result；关键是解释为什么零样本在某类 SKU 不行。

### 方案 D（AI 路线）：Agent reliability benchmark

把默认 planner 换成真实 LLM，做：

- 100+ 任务，分 easy / medium / hard / adversarial；
- 多模型（至少 2 个）、多温度、多次重复；
- 指标：success、verified success、false success、abstain、replan、cost、latency；
- Verifier 作为 test-time compute：best-of-N、self-consistency、tree search；
- 失败分类：工具误用、参数错误、依赖错误、幻觉、越权。

**可写的 claim**：

> Verifier + replan 把 false success 从 X 降到 0，但代价是 Y% 的 abstain 和 Z 倍延迟；在 hard 任务上，test-time compute 的收益随任务难度变化。

### 方案选择

| 你的目标 | 选 |
|---|---|
| 供应链 / OR / 量化 | **A**，C 作为 ablation |
| AI Agent / 应用科学家 | **D**，A 作为业务背景 |
| 研究型硕士 / 申博 | A + B 的一部分，或 C 的概率校准 |
| 只想让简历更强 | A，最快 3–4 周有结果 |

---

## 9. 四周执行计划（方案 A）

### Week 1：不确定性校准

- 复用 `backtest_predictions.csv` 或重跑 rolling backtest；
- 按时间切 calibration / test，避免泄漏；
- 实现 split conformal、CQR；
- 输出：每个 SKU 的 80/90/95% 区间、覆盖率、宽度。

### Week 2：场景与优化

- 从残差/区间采样，生成 50–200 个需求场景；
- 场景缩减（k-means / Wasserstein）；
- 两阶段随机 MILP 或 CVaR；
- 先在小实例跑通，再接现有库存/分单。

### Week 3：评测

- 30 seeds；
- baseline：point + factor、deterministic、robust、stochastic；
- 指标：OTIF、成本、积压、最坏场景、coverage、oracle gap；
- ablation：conformal vs normal、scenario 数、CVaR α、校准集大小。

### Week 4：写作与面试材料

- 一张 service-cost 前沿图；
- 一张 coverage/width 图；
- 一张 ablation 表；
- README / PORTFOLIO 各加一段；
- 准备 3 个追问：
  - 为什么 conformal 的 coverage 在这里成立？
  - 场景相关性怎么处理？
  - 为什么不是 joint optimization？

---

## 10. 简历与面试表达

不要把项目写成“我做了预测、库存、分单、波次、Agent、RAG、CI”。  
写成“我提出了一个决策问题，并用一个方法打穿它”：

> 把现有 Week-14 CVaR 布点升级为 conformal 校准场景 + 两阶段随机联合优化；在 30 seeds 上与点预测 + 安全系数、经验场景 CVaR、确定性 joint 上界对比，验证覆盖率诊断、尾部服务和分解代价。

Agent 部分：

> Plan DAG + Verifier + Replan；在 30 个任务上把 false success 从 1 降到 0，adaptive 把 recovery 从 0/3 提到 3/3；但真实 LLM 的方差和成本尚未评估。

**不要说的话**：

- “我用了最前沿的 LLM Agent”：默认是脚本 planner，会被追问穿；
- “我做了端到端优化”：实际是两层分解，不是联合最优；
- “WMAPE 73% 很好”：要看业务基线，且仓库总量上 Seasonal Naive 更好。

---

## 11. Sources

### JD

- Amazon Applied Scientist, SCOT, Specialized Selection：  
  https://www.amazon.jobs/en/jobs/10537551
- Amazon Senior Applied Scientist, Optimization：  
  https://www.amazon.jobs/en/jobs/10559787
- Amazon Senior Applied Scientist, Strategic Sourcing：  
  https://www.amazon.jobs/en/jobs/10569174
- Amazon Research Scientist, SCOT First Inbound：  
  https://www.amazon.jobs/en/jobs/10593798
- NVIDIA Modeling Engineer, Supply Chain Optimization：  
  https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/US-CA-Santa-Clara/Modeling-Engineer--Supply-Chain-Optimization_JR2025602
- OpenAI Agent Post-Training, Computer Use Research：  
  https://jobs.ashbyhq.com/openai/34c2ed3f-840f-4a68-9a00-0a0606660abf

### 技术与论文

- Chronos: Learning the Language of Time Series：  
  https://arxiv.org/abs/2403.07815
- TimesFM: A decoder-only foundation model for time-series forecasting：  
  https://arxiv.org/abs/2310.10688
- Moirai: Unified Training of Universal Time Series Forecasting Transformers：  
  https://arxiv.org/abs/2402.02592
- A Gentle Introduction to Conformal Prediction：  
  https://arxiv.org/abs/2107.07511
- Task-based End-to-end Model Learning in Stochastic Optimization：  
  https://arxiv.org/abs/1703.04529
- Scaling LLM Test-Time Compute Optimally：  
  https://arxiv.org/abs/2408.03314
- Anthropic, Building effective agents：  
  https://www.anthropic.com/engineering/building-effective-agents

### 国内入口

- 阿里巴巴招聘：https://talent.alibaba.com/
- 字节跳动招聘：https://jobs.bytedance.com/
- 美团招聘：https://zhaopin.meituan.com/
- 京东招聘：https://zhaopin.jd.com/
- 华为招聘：https://career.huawei.com/

---

## 12. 最后一句

你现在的项目是“完整”，不是“前沿”。  
但这不代表要推倒重来：完整是底座，前沿是楔子。  
选一个点，把它从“我做了”变成“我证明了”，比再加十个模块更有用。
