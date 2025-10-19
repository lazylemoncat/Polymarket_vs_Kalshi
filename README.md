# 环境设置（使用 uv）

本项目使用 uv来管理 Python 环境与依赖。

1. 安装 uv

如果你还没有安装 uv： `pip install uv`

2. 创建虚拟环境

在项目根目录下执行： `uv venv`

3. 激活虚拟环境

macOS / Linux: `source .venv/bin/activate`

Windows (PowerShell): `.venv\Scripts\Activate.ps1`

4. 安装依赖: `uv sync`

这将根据 pyproject.toml 和 uv.lock 安装完全一致的依赖版本。

5. 运行项目: `uv run python test.py`

# 使用
1. 将事件对写入`Kalshi vs Polymarket 候选对.xlsx`中.如:

    | 类型 | Kalshi 标题                       | Polymarket 标题                            | 状态              | Kalshi 市场 | Polymarket 市场 | Kalshi URL                                                   | Polymarket URL                                               | 验证备注                        |
    | ---- | --------------------------------- | ------------------------------------------ | ----------------- | ----------- | --------------- | ------------------------------------------------------------ | ------------------------------------------------------------ | ------------------------------- |
    | 天气 | Highest temperature in NYC today? | Highest temperature in NYC on  October 15? | ✅ Confirmed Match | 65° to 66°  | 65-66°F         | https://kalshi.com/markets/kxhighny/highest-temperature-in-nyc/kxhighny-25oct15 | https://polymarket.com/event/highest-temperature-in-nyc-on-october-15?tid=1760517554638 | 结算源不一致     截止时间不一致 |
    |      |                                   |                                            |                   |             |                 |                                                              |                                                              |                                 |



2. 运行`read_excel_config.py`将`Kalshi vs Polymarket 候选对.xlsx`中的配置写入`config.json`中.

3. 运行 `uv run python src/monitor.py` 启动监控；日志文件将生成在指定目录