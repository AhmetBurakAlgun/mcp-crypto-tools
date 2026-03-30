"""MCP Server — tools.py'den import eder."""
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from mcp.server.fastmcp import FastMCP
import tools as T

mcp = FastMCP("KriptoAraclar")

mcp.tool()(T.fonlama_orani)
mcp.tool()(T.acik_pozisyon)
mcp.tool()(T.long_short_orani)
mcp.tool()(T.basis_analiz)
mcp.tool()(T.premium_index)
mcp.tool()(T.likidasyon_akisi)
mcp.tool()(T.korku_acgozluluk)
mcp.tool()(T.volatilite_endeksi)
mcp.tool()(T.btc_korelasyon)
mcp.tool()(T.balina_pozisyon)
mcp.tool()(T.bsc_tvl)
mcp.tool()(T.fdusd_peg)
mcp.tool()(T.piyasa_ozeti)

if __name__ == "__main__":
    mcp.run()
