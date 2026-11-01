# 最终审计与面试要点

> 目的：把“哪些结论能说、哪些不能说”写清楚，避免作品集在面试中被追问时过度承诺。
>
> 当前：56 层评测、6 份 model card、47 个测试文件；本地 `pytest` **342 passed**（6 个依赖弃用 warning）。

## 1. 证据等级

| 等级 | 内容 | 可以怎么用 |
|---|---|---|
| A. 真实数据 + 样本外回测 | UCI Online Retail II 周需求；LightGBM/基线滚动起点回测 | 可讲预测方法与误差，不声称生产精度 |
| A. 真实订单 + 可复现实验 | 400 张真实发票的端到端履约、库存、布点、成本 | 可讲实验设计、配对比较、负结果 |
| B. 真实订单 + 显式假设 | DC 库存、网络、时效、拣选、门位、报价 | 必须同时讲假设，不能把绝对 OTIF 当生产水平 |
| C. 反事实 / 上界 | oracle 库存、oracle 分单、完美信息 | 只能作为上界或分解工具，不能当策略 |
| D. 工程骨架 | Agent v2 的默认 planner、Mock 检索 | 可讲 runtime/verifier，不冒充真实 LLM 能力 |

## 2. 可以安全说的六个结论

1. **预测**：SKU 级 LightGBM WMAPE 73.3%，Naive 89.4%；但仓库总量口径 Seasonal Naive 21.1% 最好，LightGBM 31.9%。两个口径必须并列。
2. **布点不是主杠杆**：固定总量下重摆 DC 份额，baseline target 只动 0.1–0.3pp；加库存的效应更大但不稳健。
3. **oracle 库存上界**：Weeks 45–48 的库存乘的是目标周实际需求；历史均值 140% 只有 target 70%，200% 82.5%。
4. **总量补不上结构**：同 44,824 单位，实际 SKU 结构 target 100.0%、历史结构 70.0%；历史结构加到 64,039 也只 82.5%。
5. **结构预测很难**：固定总量下，LightGBM 份额 70.0%、前一周份额 49.2%、目的国 DC 结构 71.7%；只有目标周实际结构 100%。简单结构外推和目的国代理都失败。
6. **成本前沿是区域不是锐线**：in-sample `p/h` break-even 71.9/90.3/1,646，OOS 56.7/176.9；成本档位跨周不稳。

## 3. 不能说的六件事

1. **不能说“生产可用”**：库存、网络、时效、门位、报价都是声明假设，不是观测。
2. **不能说“布点优化带来显著收益”**：0.1–0.3pp 在求解噪声附近，且库存总量主导。
3. **不能说“加库存能解决履约”**：历史 200%、安全 223% 覆盖、预测 160% 都远低于 oracle；结构才是缺口。
4. **不能说“LightGBM 结构更好”**：同总量 70.0% = 历史 70.0%，all 反而更低。
5. **不能说“Agent 有真实 LLM 规划能力”**：默认 planner 是脚本 DAG；真实模型评测未做。
6. **不能说“多周生产补货已验证”**：已有 inventory 的 52 周 replay/MILP，但没有和本 E2E 的 DC/拣选/发车完整闭环。

## 4. 面试可讲的五个点

1. **先证伪自己的指标**：发现 Week45–48 的库存是目标周实际需求 oracle，主动推翻自己的前沿结论。
2. **控制变量**：Week52 固定总量只换 SKU 结构；Week53/54 固定总量只换预测/前一周结构。
3. **不把噪声当收益**：同库存重跑 target 差 3.3pp，所以 Week51 的 +2.5pp 不算稳健。
4. **优化 + 仿真 + 统计**：CP-SAT/MILP 求解，事件仿真执行，配对种子/CI 判断稳健性。
5. **工程边界**：Agent v2 用 Plan DAG + Verifier + Replan，把“模型说的”与“工具算的”分开。

## 5. 复现与验证

```bash
export PYTHONPATH=src:.
python -m pytest -q                      # 342 passed
python tests/test_e2e_access.py          # 14 passed
python scripts/run_e2e_access.py --stock-basis last_week_share --stock-factor 1.4 \
  --load-aware --load-basis covered --repeats 3 --stem ACCESS_LAST_WEEK14 --week 54
python scripts/build_access_last_week.py
```

## 6. 下一步（按价值排序）

1. **SKU×DC 需求模型**：当前只有 SKU 总量和 DC 固定份额；需要 destination/DC 级标签、促销/新品/缺货信号。
2. **真实 LLM planner 评测**：需要 API Key，报告方差、成本、工具调用正确率。
3. **多周 E2E 闭环**：把库存结转、前置期、补货和分单/拣选/发车放进同一个滚动时域。
4. **成本财务化**：COGS、lost sales、资金占用、跌价、运费；当前 `h=€0.10` 只是示例。

完整一页版：[`../PORTFOLIO.md`](../PORTFOLIO.md)。主要模型卡：[`model_cards/access_placement.md`](model_cards/access_placement.md)。
