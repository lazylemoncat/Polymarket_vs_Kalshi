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
1. 将事件对写入`Kalshi vs Polymarket 候选对.xlsx`中,或直接写入`config.json`
2. 运行`read_excel_config.py`将`Kalshi vs Polymarket 候选对.xlsx`中的配置写入`config.json`中.
3. 运行 uv run python src/monitor.py --config config.json --log-dir . 启动监控；日志文件将生成在指定目录