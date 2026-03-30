"""
mcp-crypto-tools — Kripto Turev Piyasa & Duyarlilik Araclari
Hem MCP server hem Dashboard bu modulu kullanir.
Tum endpoint'ler ucretsiz ve API key gerektirmez.
"""

import os
import time
import statistics
from datetime import datetime, timezone
from typing import Optional

import httpx

# ─── Cache ────────────────────────────────────────────────────────────────────
_cache: dict[str, tuple[str, float]] = {}

def cache_get(key: str, ttl: int = 300) -> Optional[str]:
    if key in _cache:
        val, ts = _cache[key]
        if time.time() - ts < ttl:
            return val
        del _cache[key]
    return None

def cache_set(key: str, val: str):
    _cache[key] = (val, time.time())

def cache_stats() -> dict:
    now = time.time()
    return {
        "total": len(_cache),
        "entries": [
            {"key": k, "age_sec": round(now - ts)}
            for k, (_, ts) in sorted(_cache.items(), key=lambda x: x[1][1], reverse=True)
        ][:20]
    }

def cache_temizle():
    _cache.clear()


# ═══════════════════════════════════════════════════════════════════════════════
#  KATMAN 1: POZISYONLANMA (Turev Piyasa Verileri)
# ═══════════════════════════════════════════════════════════════════════════════

# ─── 1. Fonlama Orani (3 Borsa) ──────────────────────────────────────────────
async def fonlama_orani(sembol: str = "BNBUSDT") -> str:
    """Binance, Bybit ve OKX fonlama oranlarini karsilastirir."""
    key = f"funding:{sembol}"
    if c := cache_get(key, 120): return c

    async with httpx.AsyncClient(timeout=15) as client:
        results = []

        # Binance
        try:
            r = await client.get(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={sembol}")
            d = r.json()
            fr = float(d["lastFundingRate"])
            mark = float(d["markPrice"])
            index = float(d["indexPrice"])
            settle = float(d.get("estimatedSettlePrice", 0))
            premium = ((mark - index) / index) * 100 if index else 0
            next_ts = int(d["nextFundingTime"]) / 1000
            next_dt = datetime.fromtimestamp(next_ts, tz=timezone.utc).strftime("%H:%M UTC")
            results.append(
                f"**Binance** {sembol}\n"
                f"  Fonlama: {fr*100:.4f}% | Yillik: {fr*100*3*365:.1f}%\n"
                f"  Mark: ${mark:.2f} | Index: ${index:.2f} | Premium: {premium:+.4f}%\n"
                f"  Tahmini Settle: ${settle:.2f}\n"
                f"  Sonraki fonlama: {next_dt}"
            )
        except Exception as e:
            results.append(f"**Binance** hata: {e}")

        # Bybit
        try:
            r = await client.get(
                f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={sembol}"
            )
            d = r.json()["result"]["list"][0]
            fr = float(d["fundingRate"])
            mark = float(d["markPrice"])
            results.append(
                f"**Bybit** {sembol}\n"
                f"  Fonlama: {fr*100:.4f}% | Yillik: {fr*100*3*365:.1f}%\n"
                f"  Mark: ${mark:.2f}"
            )
        except Exception as e:
            results.append(f"**Bybit** hata: {e}")

        # OKX
        try:
            okx_sym = sembol.replace("USDT", "-USDT-SWAP")
            r = await client.get(f"https://www.okx.com/api/v5/public/funding-rate?instId={okx_sym}")
            d = r.json()["data"][0]
            fr = float(d["fundingRate"])
            next_fr = float(d.get("nextFundingRate", 0))
            results.append(
                f"**OKX** {okx_sym}\n"
                f"  Fonlama: {fr*100:.4f}% | Sonraki: {next_fr*100:.4f}%\n"
                f"  Yillik: {fr*100*3*365:.1f}%"
            )
        except Exception as e:
            results.append(f"**OKX** hata: {e}")

    result = "\n\n".join(results)
    cache_set(key, result)
    return result


# ─── 2. Acik Pozisyon (Open Interest) ────────────────────────────────────────
async def acik_pozisyon(sembol: str = "BNBUSDT") -> str:
    """Binance, Bybit, OKX acik pozisyon (OI) verilerini karsilastirir."""
    key = f"oi:{sembol}"
    if c := cache_get(key, 120): return c

    async with httpx.AsyncClient(timeout=15) as client:
        results = []
        total_oi_usd = 0

        # Binance — anlik + son 6 periyot degisim
        try:
            r = await client.get(
                f"https://fapi.binance.com/futures/data/openInterestHist?"
                f"symbol={sembol}&period=5m&limit=6"
            )
            data = r.json()
            if data:
                latest = data[-1]
                oi = float(latest["sumOpenInterest"])
                oi_usd = float(latest["sumOpenInterestValue"])
                total_oi_usd += oi_usd
                # Degisim hesapla
                if len(data) >= 2:
                    prev_oi = float(data[0]["sumOpenInterest"])
                    degisim = ((oi - prev_oi) / prev_oi) * 100 if prev_oi else 0
                else:
                    degisim = 0
                results.append(
                    f"**Binance** {sembol}\n"
                    f"  OI: {oi:,.0f} adet | ${oi_usd/1e6:.1f}M\n"
                    f"  30dk degisim: {degisim:+.2f}%"
                )
        except Exception as e:
            results.append(f"**Binance** hata: {e}")

        # Bybit
        try:
            r = await client.get(
                f"https://api.bybit.com/v5/market/open-interest?"
                f"category=linear&symbol={sembol}&intervalTime=5min&limit=1"
            )
            d = r.json()["result"]["list"][0]
            oi = float(d["openInterest"])
            # Bybit fiyat icin ticker
            r2 = await client.get(
                f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={sembol}"
            )
            price = float(r2.json()["result"]["list"][0]["markPrice"])
            oi_usd = oi * price
            total_oi_usd += oi_usd
            results.append(
                f"**Bybit** {sembol}\n"
                f"  OI: {oi:,.0f} adet | ${oi_usd/1e6:.1f}M"
            )
        except Exception as e:
            results.append(f"**Bybit** hata: {e}")

        # OKX
        try:
            okx_sym = sembol.replace("USDT", "-USDT-SWAP")
            r = await client.get(
                f"https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId={okx_sym}"
            )
            d = r.json()["data"][0]
            oi = float(d["oi"])
            oi_usd = float(d.get("oiUsd", 0))
            total_oi_usd += oi_usd
            results.append(
                f"**OKX** {okx_sym}\n"
                f"  OI: {oi:,.0f} adet | ${oi_usd/1e6:.1f}M"
            )
        except Exception as e:
            results.append(f"**OKX** hata: {e}")

        results.append(f"\n**Toplam OI**: ${total_oi_usd/1e6:.1f}M (3 borsa)")

    result = "\n\n".join(results)
    cache_set(key, result)
    return result


# ─── 3. Long/Short Orani ─────────────────────────────────────────────────────
async def long_short_orani(sembol: str = "BNBUSDT", periyot: str = "5m") -> str:
    """Binance long/short oranlarini gosterir (4 farkli metrik)."""
    key = f"ls:{sembol}:{periyot}"
    if c := cache_get(key, 120): return c

    endpoints = [
        ("Global Hesap L/S", f"https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol={sembol}&period={periyot}&limit=3"),
        ("Top Trader Hesap L/S", f"https://fapi.binance.com/futures/data/topLongShortAccountRatio?symbol={sembol}&period={periyot}&limit=3"),
        ("Top Trader Pozisyon L/S", f"https://fapi.binance.com/futures/data/topLongShortPositionRatio?symbol={sembol}&period={periyot}&limit=3"),
        ("Taker Alim/Satim", f"https://fapi.binance.com/futures/data/takerlongshortRatio?symbol={sembol}&period={periyot}&limit=3"),
    ]

    results = [f"**{sembol} Long/Short Oranlari** (periyot: {periyot})\n"]

    async with httpx.AsyncClient(timeout=15) as client:
        for name, url in endpoints:
            try:
                r = await client.get(url)
                data = r.json()
                if data:
                    latest = data[-1]
                    ratio = float(latest.get("longShortRatio", latest.get("buySellRatio", 0)))
                    long_pct = ratio / (1 + ratio) * 100

                    if "buyVol" in latest:
                        buy_vol = float(latest["buyVol"])
                        sell_vol = float(latest["sellVol"])
                        results.append(
                            f"  **{name}**: {ratio:.4f}\n"
                            f"    Alim hacmi: {buy_vol:.0f} | Satim hacmi: {sell_vol:.0f}"
                        )
                    else:
                        long_a = float(latest.get("longAccount", latest.get("longPosition", 0)))
                        short_a = float(latest.get("shortAccount", latest.get("shortPosition", 0)))
                        results.append(
                            f"  **{name}**: {ratio:.4f} (Long: %{long_pct:.1f})\n"
                            f"    Long: {long_a:.4f} | Short: {short_a:.4f}"
                        )
            except Exception as e:
                results.append(f"  **{name}**: hata — {e}")

    # Divergence analizi
    results.append("\n  **Yorum**: Global hesap orani ile Top pozisyon oranini karsilastir.\n"
                   "  Buyuk fark = perakende bir tarafa yuklu, profesyoneller dengeli.")

    result = "\n".join(results)
    cache_set(key, result)
    return result


# ─── 4. Basis Analizi (Vadeli-Spot Spread) ───────────────────────────────────
async def basis_analiz(sembol: str = "BNBUSDT", periyot: str = "5m") -> str:
    """Binance vadeli-spot basis spread'ini z-score ile analiz eder."""
    key = f"basis:{sembol}:{periyot}"
    if c := cache_get(key, 120): return c

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.get(
                f"https://fapi.binance.com/futures/data/basis?"
                f"pair={sembol}&contractType=PERPETUAL&period={periyot}&limit=200"
            )
            data = r.json()
            if not data:
                return "Basis verisi bulunamadi."

            basis_rates = [float(d["basisRate"]) for d in data]
            latest = data[-1]
            current_rate = float(latest["basisRate"])
            current_basis = float(latest["basis"])
            index_price = float(latest["indexPrice"])
            futures_price = float(latest["futuresPrice"])

            # Z-score hesapla
            mean_rate = statistics.mean(basis_rates)
            stdev_rate = statistics.stdev(basis_rates) if len(basis_rates) > 1 else 0.0001
            z_score = (current_rate - mean_rate) / stdev_rate if stdev_rate else 0

            # Durum yorumu
            if z_score < -2:
                durum = "GUCLU BACKWARDATION — Asiri korku, MR long firsati"
            elif z_score < -1:
                durum = "BACKWARDATION — Piyasa temkinli"
            elif z_score > 2:
                durum = "GUCLU CONTANGO — Asiri cosku, dikkatli ol"
            elif z_score > 1:
                durum = "CONTANGO — Long kalabalik"
            else:
                durum = "NORMAL — Notr alan"

            # Quarterly basis (risk-on/off gostergesi)
            quarterly_info = ""
            try:
                r2 = await client.get(
                    f"https://dapi.binance.com/dapi/v1/premiumIndex"
                )
                dapi = r2.json()
                for item in dapi:
                    if "BNBUSD_" in item["symbol"] and "PERP" not in item["symbol"]:
                        q_mark = float(item["markPrice"])
                        q_index = float(item["indexPrice"])
                        q_prem = ((q_mark - q_index) / q_index) * 100
                        quarterly_info = f"\n  Quarterly ({item['symbol']}): Premium {q_prem:+.3f}%"
                        break
            except Exception:
                pass

            result = (
                f"**Basis Analizi** {sembol} (son {len(basis_rates)} periyot)\n\n"
                f"  Spot (Index): ${index_price:.2f}\n"
                f"  Vadeli (Futures): ${futures_price:.2f}\n"
                f"  Basis: ${current_basis:.3f} ({current_rate*100:.4f}%)\n\n"
                f"  Ortalama basis: {mean_rate*100:.4f}%\n"
                f"  Standart sapma: {stdev_rate*100:.4f}%\n"
                f"  **Z-Score: {z_score:+.2f}**\n"
                f"  Min: {min(basis_rates)*100:.4f}% | Max: {max(basis_rates)*100:.4f}%\n\n"
                f"  Durum: {durum}"
                f"{quarterly_info}"
            )
        except Exception as e:
            result = f"Basis analizi hatasi: {e}"

    cache_set(key, result)
    return result


# ─── 5. Premium Index ────────────────────────────────────────────────────────
async def premium_index(sembol: str = "BNBUSDT") -> str:
    """Mark, index, settle fiyatlarini ve premium durumunu gosterir."""
    key = f"premium:{sembol}"
    if c := cache_get(key, 60): return c

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.get(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={sembol}")
            d = r.json()
            mark = float(d["markPrice"])
            index = float(d["indexPrice"])
            settle = float(d.get("estimatedSettlePrice", 0))
            fr = float(d["lastFundingRate"])
            premium_pct = ((mark - index) / index) * 100
            mark_vs_settle = ((mark - settle) / settle) * 100 if settle else 0

            # Index bilesenleri
            constituents_info = ""
            try:
                r2 = await client.get(f"https://fapi.binance.com/fapi/v1/constituents?symbol={sembol}")
                cd = r2.json()
                if "constituents" in cd:
                    prices = [float(c["price"]) for c in cd["constituents"]]
                    spread = max(prices) - min(prices)
                    lines = []
                    for c in cd["constituents"][:7]:
                        lines.append(f"    {c['exchange']}: ${float(c['price']):.2f} (agirlik: {float(c['weight'])*100:.1f}%)")
                    constituents_info = (
                        f"\n\n  **Index Bilesenleri** ({len(cd['constituents'])} borsa)\n"
                        + "\n".join(lines) +
                        f"\n    Borsalar arasi spread: ${spread:.2f}"
                    )
            except Exception:
                pass

            durum = ""
            if premium_pct < -0.05:
                durum = "ISKONTO — Vadeli spot altinda, korku baskisi"
            elif premium_pct > 0.05:
                durum = "PRIM — Vadeli spot ustunde, spekulatif istah"
            else:
                durum = "NOTR — Vadeli-spot dengede"

            result = (
                f"**Premium Index** {sembol}\n\n"
                f"  Mark Fiyat: ${mark:.2f}\n"
                f"  Index Fiyat: ${index:.2f}\n"
                f"  Tahmini Settle: ${settle:.2f}\n"
                f"  Son Fonlama: {fr*100:.4f}%\n\n"
                f"  Premium: {premium_pct:+.4f}%\n"
                f"  Mark vs Settle: {mark_vs_settle:+.4f}%\n"
                f"  Durum: {durum}"
                f"{constituents_info}"
            )
        except Exception as e:
            result = f"Premium index hatasi: {e}"

    cache_set(key, result)
    return result


# ─── 6. Likidasyon Akisi ─────────────────────────────────────────────────────
async def likidasyon_akisi(sembol: str = "BNBUSDT") -> str:
    """Bybit son likidasyonlari gosterir. (Binance REST kapali, sadece WS)"""
    key = f"liq:{sembol}"
    if c := cache_get(key, 60): return c

    results = [f"**Likidasyon Bilgisi** {sembol}\n"]

    async with httpx.AsyncClient(timeout=15) as client:
        # Binance — REST endpoint kapalı, bilgi notu
        results.append(
            "  **Binance**: REST endpoint kaldirildi.\n"
            "  Canli izleme icin: wss://fstream.binance.com/ws/bnbusdt@forceOrder\n"
        )

        # Bybit — son likidasyonlar (ticker'dan)
        try:
            r = await client.get(
                f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={sembol}"
            )
            d = r.json()["result"]["list"][0]
            results.append(
                f"  **Bybit** {sembol}\n"
                f"    24s Ciro: ${float(d['turnover24h'])/1e6:.1f}M\n"
                f"    24s Hacim: {float(d['volume24h']):,.0f}\n"
                f"    24s Degisim: {float(d['price24hPcnt'])*100:+.2f}%\n"
                f"    Mark: ${float(d['markPrice']):.2f}"
            )
        except Exception as e:
            results.append(f"  **Bybit** hata: {e}")

        # OKX — son likidasyonlar
        try:
            okx_sym = sembol.replace("USDT", "-USDT-SWAP")
            r = await client.get(
                f"https://www.okx.com/api/v5/public/liquidation-orders?"
                f"instType=SWAP&instId={okx_sym}&state=filled&limit=5"
            )
            d = r.json()
            if d.get("data"):
                for liq_group in d["data"][:2]:
                    details = liq_group.get("details", [])
                    for det in details[:3]:
                        side = "LONG liq" if det.get("side") == "sell" else "SHORT liq"
                        px = float(det.get("bkPx", 0))
                        sz = float(det.get("sz", 0))
                        results.append(f"    OKX: {side} | ${px:.2f} | {sz} adet")
            else:
                results.append("  **OKX**: Son likidasyon verisi yok")
        except Exception as e:
            results.append(f"  **OKX** hata: {e}")

    results.append(
        "\n  **Not**: Canli likidasyon izleme icin WebSocket stream gerekli.\n"
        "  market_intel.py entegrasyonunda WS kullanilacak."
    )

    result = "\n".join(results)
    cache_set(key, result)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  KATMAN 2: DUYARLILIK (Sentiment & Volatilite)
# ═══════════════════════════════════════════════════════════════════════════════

# ─── 7. Korku & Acgozluluk Endeksi ───────────────────────────────────────────
async def korku_acgozluluk() -> str:
    """Kripto Korku & Acgozluluk endeksi (Alternative.me)."""
    key = "fng"
    if c := cache_get(key, 600): return c

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.get("https://api.alternative.me/fng/?limit=7")
            data = r.json()["data"]

            lines = ["**Kripto Korku & Acgozluluk Endeksi**\n"]
            for i, d in enumerate(data):
                val = int(d["value"])
                label = d["value_classification"]
                ts = datetime.fromtimestamp(int(d["timestamp"]), tz=timezone.utc)
                tarih = ts.strftime("%Y-%m-%d")

                # Gorsel bar
                bar_len = val // 5
                bar = "█" * bar_len + "░" * (20 - bar_len)

                isaret = " ◀ BUGUN" if i == 0 else ""
                lines.append(f"  {tarih}: [{bar}] {val}/100 {label}{isaret}")

            # MR yorumu
            current = int(data[0]["value"])
            if current <= 20:
                yorum = "ASIRI KORKU — Mean-reversion long firsati yuksek"
            elif current <= 40:
                yorum = "KORKU — Temkinli ortam, dipten alim firsatlari olabilir"
            elif current >= 80:
                yorum = "ASIRI ACGOZLULUK — Duzeltme riski yuksek, dikkatli ol"
            elif current >= 60:
                yorum = "ACGOZLULUK — Piyasa iyimser, MR short firsatlari olabilir"
            else:
                yorum = "NOTR — Belirgin yonelim yok"

            lines.append(f"\n  **Yorum**: {yorum}")
            result = "\n".join(lines)
        except Exception as e:
            result = f"Korku & Acgozluluk hatasi: {e}"

    cache_set(key, result)
    return result


# ─── 8. Volatilite Endeksi (Deribit DVOL + Put/Call) ─────────────────────────
async def volatilite_endeksi() -> str:
    """BTC DVOL (implied volatility), realized vol ve put/call orani."""
    key = "dvol"
    if c := cache_get(key, 300): return c

    async with httpx.AsyncClient(timeout=20) as client:
        results = ["**Volatilite Analizi** (BTC proxy — BNB korelasyonu ~0.90)\n"]

        # DVOL (implied volatility index)
        try:
            r = await client.get(
                "https://www.deribit.com/api/v2/public/get_volatility_index_data?"
                "currency=BTC&resolution=3600&start_timestamp="
                f"{int((time.time() - 86400) * 1000)}&end_timestamp={int(time.time() * 1000)}"
            )
            d = r.json()["result"]["data"]
            if d:
                latest_dvol = d[-1][1]  # [timestamp, open, high, low, close]
                dvol_high = max(row[2] for row in d)
                dvol_low = min(row[3] for row in d)
                results.append(
                    f"  **BTC DVOL** (Implied Volatility Index)\n"
                    f"    Guncel: {latest_dvol:.1f}%\n"
                    f"    24s Aralik: {dvol_low:.1f}% — {dvol_high:.1f}%"
                )
        except Exception as e:
            results.append(f"  **DVOL** hata: {e}")

        # Realized Volatility
        try:
            r = await client.get(
                "https://www.deribit.com/api/v2/public/get_historical_volatility?currency=BTC"
            )
            d = r.json()["result"]
            if d:
                rv = d[-1][1]
                results.append(f"\n  **BTC Realized Volatility**: {rv:.1f}%")

                # IV vs RV spread
                if 'latest_dvol' in dir():
                    spread = latest_dvol - rv
                    if spread > 10:
                        iv_yorum = "IV >> RV: Piyasa asiri korku fiyatliyor, MR icin elverisli"
                    elif spread < -5:
                        iv_yorum = "IV << RV: Piyasa sakin fiyatliyor ama gercek vol yuksek, dikkat"
                    else:
                        iv_yorum = "IV ≈ RV: Normal volatilite fiyatlamasi"
                    results.append(f"  IV-RV Spread: {spread:+.1f}% — {iv_yorum}")
        except Exception as e:
            results.append(f"  **RV** hata: {e}")

        # Put/Call OI Ratio
        try:
            r = await client.get(
                "https://www.deribit.com/api/v2/public/get_book_summary_by_currency?"
                "currency=BTC&kind=option"
            )
            options = r.json()["result"]
            put_oi = sum(o["open_interest"] for o in options if "-P" in o["instrument_name"])
            call_oi = sum(o["open_interest"] for o in options if "-C" in o["instrument_name"])
            pc_ratio = put_oi / call_oi if call_oi else 0
            total_oi = put_oi + call_oi

            if pc_ratio > 1.0:
                pc_yorum = "PUT agirlikli — Hedge/korku baskisi, dip alim firsati olabilir"
            elif pc_ratio < 0.5:
                pc_yorum = "CALL agirlikli — Asiri iyimserlik, tepe riski"
            else:
                pc_yorum = "Dengeli — Normal piyasa kosullari"

            results.append(
                f"\n  **BTC Opsiyon Put/Call Orani**\n"
                f"    Put OI: {put_oi:,.0f} | Call OI: {call_oi:,.0f}\n"
                f"    P/C Orani: {pc_ratio:.3f} | Toplam OI: {total_oi:,.0f}\n"
                f"    Yorum: {pc_yorum}"
            )
        except Exception as e:
            results.append(f"  **P/C** hata: {e}")

    result = "\n".join(results)
    cache_set(key, result)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  KATMAN 3: KORELASYON & CAPRAZ PIYASA
# ═══════════════════════════════════════════════════════════════════════════════

# ─── 9. BTC-BNB Korelasyon ────────────────────────────────────────────────────
async def btc_korelasyon(periyot: int = 100) -> str:
    """BTC-BNB fiyat korelasyonu ve beta hesaplar."""
    key = f"corr:{periyot}"
    if c := cache_get(key, 600): return c

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            # BTC ve BNB saatlik mumlar
            r_btc = await client.get(
                f"https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit={periyot}"
            )
            r_bnb = await client.get(
                f"https://fapi.binance.com/fapi/v1/klines?symbol=BNBUSDT&interval=1h&limit={periyot}"
            )
            btc_closes = [float(k[4]) for k in r_btc.json()]
            bnb_closes = [float(k[4]) for k in r_bnb.json()]

            n = min(len(btc_closes), len(bnb_closes))
            btc_closes = btc_closes[-n:]
            bnb_closes = bnb_closes[-n:]

            # Getiri hesapla
            btc_ret = [(btc_closes[i] - btc_closes[i-1]) / btc_closes[i-1]
                       for i in range(1, n)]
            bnb_ret = [(bnb_closes[i] - bnb_closes[i-1]) / bnb_closes[i-1]
                       for i in range(1, n)]

            # Korelasyon
            mean_btc = statistics.mean(btc_ret)
            mean_bnb = statistics.mean(bnb_ret)
            cov = sum((b - mean_btc) * (n_ - mean_bnb) for b, n_ in zip(btc_ret, bnb_ret)) / len(btc_ret)
            std_btc = statistics.stdev(btc_ret)
            std_bnb = statistics.stdev(bnb_ret)
            correlation = cov / (std_btc * std_bnb) if std_btc and std_bnb else 0

            # Beta
            var_btc = statistics.variance(btc_ret)
            beta = cov / var_btc if var_btc else 0

            # Son 24 saat performans karsilastirmasi
            btc_24h = ((btc_closes[-1] - btc_closes[-24]) / btc_closes[-24]) * 100 if n >= 24 else 0
            bnb_24h = ((bnb_closes[-1] - bnb_closes[-24]) / bnb_closes[-24]) * 100 if n >= 24 else 0
            relative = bnb_24h - btc_24h

            if beta > 1.1:
                beta_yorum = "BNB, BTC'den daha volatil — dususlerde daha cok dusuyor"
            elif beta < 0.9:
                beta_yorum = "BNB, BTC'den daha az volatil — goreceli guvenli"
            else:
                beta_yorum = "BNB ≈ BTC volatilitesi — paralel hareket"

            if relative < -1:
                rel_yorum = "BNB BTC'ye gore asiri zayif — MR long firsati olabilir"
            elif relative > 1:
                rel_yorum = "BNB BTC'ye gore asiri guclu — MR short firsati olabilir"
            else:
                rel_yorum = "BNB-BTC dengede hareket ediyor"

            result = (
                f"**BTC-BNB Korelasyon Analizi** (son {n} saat)\n\n"
                f"  Korelasyon: {correlation:.4f}\n"
                f"  Beta: {beta:.3f} — {beta_yorum}\n\n"
                f"  **Son 24 Saat Performans**\n"
                f"    BTC: {btc_24h:+.2f}% (${btc_closes[-1]:,.0f})\n"
                f"    BNB: {bnb_24h:+.2f}% (${bnb_closes[-1]:.2f})\n"
                f"    Goreceli: {relative:+.2f}% — {rel_yorum}"
            )
        except Exception as e:
            result = f"Korelasyon hatasi: {e}"

    cache_set(key, result)
    return result


# ─── 10. Balina Pozisyonlari (Hyperliquid) ───────────────────────────────────
async def balina_pozisyon(coin: str = "BNB") -> str:
    """Hyperliquid'deki BNB piyasa verisi ve buyuk pozisyonlar."""
    key = f"whale:{coin}"
    if c := cache_get(key, 300): return c

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            # Piyasa verisi
            r = await client.post(
                "https://api.hyperliquid.xyz/info",
                json={"type": "metaAndAssetCtxs"}
            )
            data = r.json()
            meta = data[0]["universe"]
            contexts = data[1]

            # Coin'i bul
            coin_idx = None
            for i, m in enumerate(meta):
                if m["name"].upper() == coin.upper():
                    coin_idx = i
                    break

            if coin_idx is None:
                result = f"{coin} Hyperliquid'de bulunamadi."
            else:
                ctx = contexts[coin_idx]
                mark = float(ctx["markPx"])
                oi = float(ctx["openInterest"])
                funding = float(ctx["funding"])
                vol_24h = float(ctx.get("dayNtlVlm", 0))
                premium = float(ctx.get("premium", 0))

                result = (
                    f"**Hyperliquid {coin} Piyasa Verisi**\n\n"
                    f"  Mark Fiyat: ${mark:.2f}\n"
                    f"  Acik Pozisyon: {oi:,.0f} adet\n"
                    f"  Fonlama (saatlik): {funding*100:.4f}%\n"
                    f"  24s Hacim: ${vol_24h/1e6:.1f}M\n"
                    f"  Premium: {premium*100:.4f}%\n\n"
                    f"  **Not**: Hyperliquid on-chain, tum pozisyonlar acik.\n"
                    f"  Buyuk cuzdan takibi icin adres bazli sorgulama yapilabilir."
                )
        except Exception as e:
            result = f"Hyperliquid hatasi: {e}"

    cache_set(key, result)
    return result


# ─── 11. BSC TVL & DeFi Akisi ────────────────────────────────────────────────
async def bsc_tvl() -> str:
    """BSC (BNB Chain) TVL, stablecoin ve DEX hacim verileri (DeFiLlama)."""
    key = "bsc_tvl"
    if c := cache_get(key, 900): return c

    async with httpx.AsyncClient(timeout=15) as client:
        results = ["**BNB Chain (BSC) DeFi Verileri**\n"]

        # TVL
        try:
            r = await client.get("https://api.llama.fi/v2/chains")
            chains = r.json()
            bsc = next((c for c in chains if c["name"] == "BSC"), None)
            if bsc:
                tvl = bsc["tvl"]
                results.append(f"  TVL: ${tvl/1e9:.2f}B")
        except Exception as e:
            results.append(f"  TVL hata: {e}")

        # Stablecoin
        try:
            r = await client.get("https://stablecoins.llama.fi/stablecoinchains")
            chains = r.json()
            bsc = next((c for c in chains if c["name"] == "BSC"), None)
            if bsc:
                sc = bsc.get("totalCirculatingUSD", {})
                total_sc = sum(sc.values()) if isinstance(sc, dict) else float(sc)
                results.append(f"  Stablecoin: ${total_sc/1e9:.2f}B")
        except Exception as e:
            results.append(f"  Stablecoin hata: {e}")

        # DEX hacmi
        try:
            r = await client.get("https://api.llama.fi/overview/dexs/BSC")
            d = r.json()
            vol_24h = d.get("total24h", 0)
            vol_change = d.get("change_1d", 0)
            results.append(
                f"  DEX 24s Hacim: ${vol_24h/1e6:.0f}M ({vol_change:+.1f}% degisim)"
            )
        except Exception as e:
            results.append(f"  DEX hata: {e}")

        # TVL tarihcesi (son 7 gun trend)
        try:
            r = await client.get("https://api.llama.fi/v2/historicalChainTvl/BSC")
            data = r.json()
            if len(data) >= 7:
                tvl_7d_ago = data[-7]["tvl"]
                tvl_now = data[-1]["tvl"]
                tvl_change = ((tvl_now - tvl_7d_ago) / tvl_7d_ago) * 100
                results.append(f"  7 gunluk TVL degisim: {tvl_change:+.1f}%")

                if tvl_change < -5:
                    results.append("\n  **Yorum**: TVL dusuyor — BSC'den para cikisi, BNB icin baski")
                elif tvl_change > 5:
                    results.append("\n  **Yorum**: TVL artiyor — BSC'ye para girisi, BNB icin destekleyici")
                else:
                    results.append("\n  **Yorum**: TVL stabil")
        except Exception:
            pass

    result = "\n".join(results)
    cache_set(key, result)
    return result


# ─── 12. Piyasa Ozeti (Hepsi Bir Arada) ──────────────────────────────────────
async def piyasa_ozeti(sembol: str = "BNBUSDT") -> str:
    """Tum metriklerin tek ekranda hizli ozeti. Dashboard icin ideal."""
    key = f"ozet:{sembol}"
    if c := cache_get(key, 60): return c

    async with httpx.AsyncClient(timeout=20) as client:
        lines = [f"**PIYASA OZETI** {sembol} — {datetime.now(timezone.utc).strftime('%H:%M UTC')}\n"]

        # 1) Fiyat + Premium
        try:
            r = await client.get(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={sembol}")
            d = r.json()
            mark = float(d["markPrice"])
            index = float(d["indexPrice"])
            fr = float(d["lastFundingRate"])
            prem = ((mark - index) / index) * 100
            lines.append(f"  Fiyat: ${mark:.2f} | Fonlama: {fr*100:.4f}% | Premium: {prem:+.4f}%")
        except Exception:
            lines.append("  Fiyat: veri alinamadi")

        # 2) OI
        try:
            r = await client.get(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={sembol}")
            oi = float(r.json()["openInterest"])
            lines.append(f"  Acik Pozisyon: {oi:,.0f} adet")
        except Exception:
            pass

        # 3) Taker ratio
        try:
            r = await client.get(
                f"https://fapi.binance.com/futures/data/takerlongshortRatio?"
                f"symbol={sembol}&period=5m&limit=1"
            )
            d = r.json()[0]
            ratio = float(d["buySellRatio"])
            lines.append(f"  Taker Alim/Satim: {ratio:.3f}")
        except Exception:
            pass

        # 4) Top trader pozisyon
        try:
            r = await client.get(
                f"https://fapi.binance.com/futures/data/topLongShortPositionRatio?"
                f"symbol={sembol}&period=5m&limit=1"
            )
            d = r.json()[0]
            ratio = float(d["longShortRatio"])
            long_pct = ratio / (1 + ratio) * 100
            lines.append(f"  Top Trader L/S: {ratio:.3f} (Long: %{long_pct:.0f})")
        except Exception:
            pass

        # 5) Basis
        try:
            r = await client.get(
                f"https://fapi.binance.com/futures/data/basis?"
                f"pair={sembol}&contractType=PERPETUAL&period=5m&limit=1"
            )
            d = r.json()[0]
            basis = float(d["basisRate"]) * 100
            lines.append(f"  Basis: {basis:.4f}%")
        except Exception:
            pass

        # 6) F&G
        try:
            r = await client.get("https://api.alternative.me/fng/?limit=1")
            d = r.json()["data"][0]
            val = d["value"]
            label = d["value_classification"]
            lines.append(f"  Korku/Acgozluluk: {val}/100 ({label})")
        except Exception:
            pass

        # Genel yorum
        lines.append("\n  Detay icin: fonlama_orani, basis_analiz, long_short_orani, volatilite_endeksi")

    result = "\n".join(lines)
    cache_set(key, result)
    return result
