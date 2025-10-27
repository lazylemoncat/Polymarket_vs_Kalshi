# Polymarket vs. Kalshi 套利监控系统 PRD

## 1. 核心目标

本项目的**唯一目标**是**观察和验证**，而非交易执行。我们需要通过一个 MVP（最小可行产品）来回答以下核心问题：

- 在真实的、实时的市场环境下，扣除所有的交易成本后，**是否存在净利润为正的套利窗口？**
- 如果存在，这样的窗口**通常能持续多久？**出现的**频率**如何？
- 窗口出现时，两个平台的**订单簿深度**（流动性）大致如何？

---

## 2. 核心功能 (Functional Requirements)

### FR1: 市场对匹配

- 系统应能从一个外部配置文件（如 `config.json`）中读取需要监控的市场对列表。
- 配置文件格式为 `{'POLY_TOKEN_ID': 'KALSHI_TICKER'}` 的键值对，方便随时增删和修改。

⚠️ **全部配对需人工审查**

---

### FR2: 实时数据拉取与验证

#### FR2.0 轮询机制

- **轮询频率**：默认为 **2秒** 一次，并在 `config.json` 中可配置 (`polling_interval_seconds`)。
- **API 限速保护：**
  - 首次遇到 `429`: 等待 30秒，轮询间隔 × 1.5
  - 30分钟内再次遇到 `429`: 等待 60秒，轮询间隔 × 2
  - 30分钟内第三次遇到 `429`: 等待 120秒，轮询间隔 × 2，并触发告警（若配置）
  - 冷却机制：若连续 30分钟无 `429` 错误，轮询间隔每 10分钟自动恢复 10%，直至回到配置的初始值
  - 所有退避操作均以结构化 JSON 格式记录到 `errors.log`

#### FR2.1 数据有效性验证

每次 API 响应必须通过以下检查，否则该数据点将被丢弃：

1. HTTP 状态码为 200
2. 价格字段 (`bid`, `ask`) 存在且非空
3. 价格在合理区间：`0.01 ≤ price ≤ 0.99`
4. `Bid ≤ Ask`
5. API 响应中的时间戳与本地 UTC 时间差小于 10秒

**错误处理：**
- 如果某个市场连续 3次 拉取数据失败，将在终端 UI 中标记为 `🔴 ERROR`，并记录到 `errors.log`，同时在本次计算中跳过该市场。

---

### FR3: 成本与净价差计算

#### FR3.1 Kalshi 手续费精确计算

- **taker 费率模型**：假设所有即时套利操作均为吃单（taker）
- **费用公式**：
  ```
  taker_fees = round up(0.07 x C x P x (1-P))
  ```
  其中 `P` 为执行价格，结果向上取整到美分

- **maker 费率模型**：
- **费用公式**：
  ```
  maker_fees = round up(0.0175 x C x P x (1-P))
  ```
  其中 `P` 为执行价格，结果向上取整到美分  
- **总费用**：套利操作涉及开仓和平仓，因此总费用为
  ```
  total_kalshi_fee = taker_fees + maker_fees
  ```

#### FR3.2 净价差方向明确化

**方向1（做多 Kalshi，做空 Polymarket）：**
- **操作**：在 Kalshi 买入 @Ask，在 Polymarket 卖出 @Bid
- **净价差**：
  ```
  net_spread_buy_K_sell_P = Poly_Bid - Kalshi_Ask - Cost_Total
  ```

**方向2（做空 Kalshi，做多 Polymarket）：**
- **操作**：在 Kalshi 卖出 @Bid，在 Polymarket 买入 @Ask
- **净价差：**
  ```
  net_spread_buy_P_sell_K = Kalshi_Bid - Poly_Ask - Cost_Total
  ```

#### FR3.3 总成本 (`Cost_Total`)

```
Cost_Total = total_kalshi_fee + (Poly_Ask - Poly_Bid) + (gas_fee_per_trade_usd × 2)
```

---

### FR4: 机会窗口定义与日志记录

#### FR4.1 机会窗口状态管理

系统将在内存中维护一个状态机来跟踪每个市场对的"机会窗口"。

- **窗口开始**：当一个市场对首次从 `Net_Spread ≤ 0` 变为 `Net_Spread > 0` 时，创建一个新的窗口记录，标记"窗口开始"时间和 `window_id`
- **窗口持续**：在后续轮询中，若 `Net_Spread` 持续 > 0，则更新该窗口的"最后观测时间"、"峰值价差"和"平均价差"
- **窗口结束**：当 `Net_Spread` 首次从 > 0 变为 ≤ 0 时，标记"窗口结束"，计算最终的持续时长等统计数据，并将完整的窗口记录写入 `opportunity_windows.csv`

#### FR4.2 双日志系统

**1. `price_snapshots.csv`（原始数据日志）**
- 每次轮询都记录一行，用于完整回放和调试
- **字段**：
  - `timestamp`
  - `market_pair`
  - `kalshi_bid`
  - `kalshi_ask`
  - `poly_bid`
  - `poly_ask`
  - `total_cost`
  - `net_spread_buy_K_sell_P`
  - `net_spread_buy_P_sell_K`

**2. `opportunity_windows.csv`（机会窗口日志）**
- 仅在"窗口结束"时记录一行，用于核心统计分析
- **字段：**
  - `window_id`
  - `market_pair`
  - `start_time`
  - `end_time`
  - `duration_seconds`
  - `peak_spread`
  - `avg_spread`
  - `direction`
  - `observation_count`

---

### FR5: 终端实时展示

每次轮询后，使用 `rich` 或类似库刷新终端 UI，显示如下格式的表格：

| Market Pair | Status         | Kalshi      | Polymarket  | Direction | Net Spread | Updated  |
|-------------|----------------|-------------|-------------|-----------|------------|----------|
| TRUMP-24    | 🟢 OPPORTUNITY | 0.48/0.50   | 0.53/0.55   | K→P       | +$0.023    | 14:32:05 |
| FED-DEC     | ⚪ MONITORING   | 0.72/0.74   | 0.71/0.73   | -         | -          | 14:32:04 |
| NBA-LAKERS  | 🔴 ERROR       | N/A         | N/A         | -         | -          | 14:31:58 |

**Status 列定义：**
- `🟢 OPPORTUNITY`：当前价差 > 0
- `⚪ MONITORING`：正常监控中
- `🔴 ERROR`：数据错误

---

### FR6: 状态持久化与恢复

#### FR6.1 状态检查点

- 每隔 **5分钟**，系统将所有当前"进行中"的窗口状态，自动保存到 `window_state.json` 文件中

#### FR6.2 启动时恢复逻辑

- 脚本启动时，首先检查 `window_state.json` 文件
- 如果文件存在且 `last_updated` 时间戳在 5分钟内，则加载所有 `active_windows` 到内存中，并继续监控
- 如果 `last_updated` 已超时，则将这些窗口标记为"强制结束"，并备注 `interrupted` 后写入 `opportunity_windows.csv`

---

## 3. 关键指标与成功标准

在 **48小时** 监控期内，满足以下任一条件即视为"**初步验证存在套利机会**"：

### 场景 A（频繁小机会）
- 出现 **≥ 5次** 净价差 > $0.03 的窗口
- 其中至少 **70%** 的窗口持续时长 **≥ 10秒**
- 且峰值价差的平均值 **> $0.04**（确保有足够安全边际）

### 场景 B（稀有大机会）
- 出现 **≥ 3次** 净价差 > $0.05 的窗口
- 其中至少 **2次** 持续时长 **≥ 30秒**
- 且峰值价差的最大值 **> $0.08**

### 场景 C（无机会）
- 不满足以上任何一种场景

---

## 4. 交付物

1. 可执行的 Python 脚本（`monitor.py`）
2. 配置文件（`config.example.json`）
3. 一份简单的 `README.md` 文件，说明如何配置环境、安装依赖以及运行脚本
4. 脚本运行后生成的日志文件：
   - `price_snapshots.csv`
   - `opportunity_windows.csv`
   - `errors.log`（采用结构化的 JSON Lines 格式）

---

## 5. 配置文件示例

### `config.example.json`

```json
{
  "market_pairs": [
    {
      "id": "pair_001",
      "polymarket_token": "0x1234...",
      "kalshi_ticker": "PRES24-TRUMP",
      "market_name": "Trump 2024 Win",
      "settlement_date": "2024-11-05T23:59:00Z",
      "manually_verified": true,
      "notes": "Both platforms use AP call as resolution source."
    }
  ],
  "monitoring": {
    "polling_interval_seconds": 2,
    "monitoring_duration_hours": 48
  },
  "cost_assumptions": {
    "gas_fee_per_trade_usd": 0.10
  },
  "alerting": {
    "telegram_bot_token": "YOUR_TOKEN",
    "telegram_chat_id": "YOUR_CHAT_ID"
  }
}
```

---

## 6. 启动前检查清单

在正式启动 48小时监控前，必须完成以下验证：

- [ ] **配置验证**：`config.json` 中所有市场对都经过人工核对，确保两平台结算标准和时间一致
- [ ] **API 连通性测试**：手动调用两个平台 API 各 10次，确认平均响应时间 < 500ms 且无权限错误
- [ ] **成本公式验证**：选择 3个价格点（0.30、0.50、0.70）手动计算 Kalshi 费用，与代码输出比对
- [ ] **日志输出测试**：运行脚本 5分钟，检查 `price_snapshots.csv` 和 `opportunity_windows.csv` 格式与字段正确
- [ ] **终端 UI 测试**：确认表格能正常刷新，并能通过注入假数据正确显示 `🟢 OPPORTUNITY` 和 `🔴 ERROR` 状态

---

# 项目进度计划

| 阶段 | 日期 | 负责人 | 任务 |
|------|------|--------|------|
| **准备阶段** | 2025年10月13日 | Helios | PRD文档 |
| | | 文钊 | 环境搭建与依赖确认<br>API文档研究<br>市场对匹配 |
| **核心开发** | 2025年10月14日 | 文钊 | 完成数据拉取、计算、日志记录三大核心模块 |
| | | Helios | 校队市场对匹配 |
| **集成开发** | 2025年10月15日 | 文钊 | 组装所有模块，实现完整监控流程 |
| **测试验证** | 2025年10月16日 → 2025年10月17日 | Helios、文钊 | 全面测试，汇报结果 |

---

## 每日同步机制

每天 **18:30** 进行15分钟快速同步：

**同步格式：**
- ✅ **今天完成：** XXX
- ⚠️ **遇到的问题：** XXX  
- 🎯 **明天重点：** XXX
- 🚫 **阻塞问题：** XXX（需要对方协助）

---

[代码仓库](https://github.com/lazylemoncat/Polymarket_vs_Kalshi)

---

