"""
Dashboard — FastAPI ile web UI.
tools.py'deki fonksiyonlari HTTP uzerinden calistirir.
Calistir: uvicorn dashboard:app --host 0.0.0.0 --port 8766
"""

import json
import traceback
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import tools as T

app = FastAPI(title="MCP Crypto Tools Dashboard")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

# ─── API Endpoint'leri ────────────────────────────────────────────────────────

@app.get("/api/cache/stats")
async def cache_stats():
    return T.cache_stats()

@app.post("/api/cache/clear")
async def cache_clear():
    T.cache_temizle()
    return {"ok": True}

async def run_tool(fn, *args, **kwargs):
    try:
        import asyncio, inspect
        if inspect.iscoroutinefunction(fn):
            result = await fn(*args, **kwargs)
        else:
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: fn(*args, **kwargs)
            )
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e),
                             "trace": traceback.format_exc()}, status_code=500)

@app.post("/api/fonlama_orani")
async def api_fonlama(r: Request):
    d = await r.json()
    return await run_tool(T.fonlama_orani, d.get("sembol", "BNBUSDT"))

@app.post("/api/acik_pozisyon")
async def api_oi(r: Request):
    d = await r.json()
    return await run_tool(T.acik_pozisyon, d.get("sembol", "BNBUSDT"))

@app.post("/api/long_short_orani")
async def api_ls(r: Request):
    d = await r.json()
    return await run_tool(T.long_short_orani, d.get("sembol", "BNBUSDT"), d.get("periyot", "5m"))

@app.post("/api/basis_analiz")
async def api_basis(r: Request):
    d = await r.json()
    return await run_tool(T.basis_analiz, d.get("sembol", "BNBUSDT"), d.get("periyot", "5m"))

@app.post("/api/premium_index")
async def api_premium(r: Request):
    d = await r.json()
    return await run_tool(T.premium_index, d.get("sembol", "BNBUSDT"))

@app.post("/api/likidasyon_akisi")
async def api_liq(r: Request):
    d = await r.json()
    return await run_tool(T.likidasyon_akisi, d.get("sembol", "BNBUSDT"))

@app.post("/api/korku_acgozluluk")
async def api_fng(r: Request):
    return await run_tool(T.korku_acgozluluk)

@app.post("/api/volatilite_endeksi")
async def api_vol(r: Request):
    return await run_tool(T.volatilite_endeksi)

@app.post("/api/btc_korelasyon")
async def api_corr(r: Request):
    d = await r.json()
    return await run_tool(T.btc_korelasyon, int(d.get("periyot", 100)))

@app.post("/api/balina_pozisyon")
async def api_whale(r: Request):
    d = await r.json()
    return await run_tool(T.balina_pozisyon, d.get("coin", "BNB"))

@app.post("/api/bsc_tvl")
async def api_bsc(r: Request):
    return await run_tool(T.bsc_tvl)

@app.post("/api/piyasa_ozeti")
async def api_ozet(r: Request):
    d = await r.json()
    return await run_tool(T.piyasa_ozeti, d.get("sembol", "BNBUSDT"))

# ─── Dashboard HTML ───────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return Path("dashboard.html").read_text(encoding="utf-8")
