from rich.console import Console
from rich.table import Table

def render_table(data):
    table = Table(title="Polymarket vs Kalshi Arbitrage Monitor")
    table.add_column("Market Pair")
    table.add_column("Status")
    table.add_column("Kalshi")
    table.add_column("Polymarket")
    table.add_column("Direction")
    table.add_column("Net Spread")
    table.add_column("Updated")
    for row in data:
        table.add_row(*row)
    Console().clear()
    Console().print(table)
