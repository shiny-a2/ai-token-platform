"""Automatic on-chain verification of crypto payments by TxID.

Networks (all via public, key-less APIs):
- BTC          blockstream.info
- USDT TRC20   TronGrid public endpoint
- USDT BEP20 / BNB   BSC public JSON-RPC
- USDT ERC20 / ETH   Ethereum public JSON-RPC

Rules: transaction must exist and be confirmed, pay OUR wallet (from the
encrypted payment_methods table), and its USD value must cover the package
price within TOLERANCE. TxIDs are single-use (dedupe against receipts).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt
from app.models import PaymentMethod, PaymentReceipt

log = logging.getLogger("crypto_verify")

TOLERANCE = 0.93  # accept >= 93% of price (fees/slippage)
TIMEOUT = httpx.Timeout(20.0)

USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
USDT_BEP20_CONTRACT = "0x55d398326f99059ff775485246999027b3197955"  # 18 decimals
USDT_ERC20_CONTRACT = "0xdac17f958d2ee523a2206206994597c13d831ec7"  # 6 decimals
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

BSC_RPCS = ["https://bsc-dataseed.binance.org", "https://bsc-dataseed1.defibit.io"]
ETH_RPCS = ["https://eth.llamarpc.com", "https://cloudflare-eth.com"]


@dataclass
class VerifyResult:
    verified: bool
    network: str = ""
    amount_usd: float = 0.0
    note: str = ""


async def _get_rates(client: httpx.AsyncClient) -> dict[str, float]:
    try:
        r = await client.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin,ethereum,binancecoin", "vs_currencies": "usd"},
        )
        d = r.json()
        return {
            "btc": float(d["bitcoin"]["usd"]),
            "eth": float(d["ethereum"]["usd"]),
            "bnb": float(d["binancecoin"]["usd"]),
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("rates fetch failed: %s", exc)
        return {}


async def _our_wallets(db: AsyncSession) -> dict[str, str]:
    rows = (
        await db.execute(
            select(PaymentMethod).where(PaymentMethod.is_active.is_(True))
        )
    ).scalars().all()
    out: dict[str, str] = {}
    for m in rows:
        if m.type in ("btc", "usdt_trc20", "usdt_bnb", "eth", "bnb"):
            out[m.type] = decrypt(m.encrypted_value).strip()
    return out


async def txid_already_used(db: AsyncSession, txid: str, receipt_id: str) -> bool:
    row = (
        await db.execute(
            select(PaymentReceipt).where(
                PaymentReceipt.txid == txid,
                PaymentReceipt.id != receipt_id,
                PaymentReceipt.status.in_(("pending", "approved")),
            )
        )
    ).scalars().first()
    return row is not None


# ---------------- BTC ----------------
async def _verify_btc(
    client: httpx.AsyncClient, txid: str, addr: str, rate: float
) -> VerifyResult | None:
    try:
        r = await client.get(f"https://blockstream.info/api/tx/{txid}")
        if r.status_code != 200:
            return None
        tx = r.json()
        if not tx.get("status", {}).get("confirmed"):
            return VerifyResult(False, "BTC", 0, "تراکنش هنوز تایید نشده")
        sats = sum(
            out.get("value", 0)
            for out in tx.get("vout", [])
            if out.get("scriptpubkey_address") == addr
        )
        if sats <= 0:
            return VerifyResult(False, "BTC", 0, "مقصد تراکنش، کیف‌پول ما نیست")
        usd = (sats / 1e8) * rate
        return VerifyResult(True, "BTC", usd)
    except Exception as exc:  # noqa: BLE001
        log.warning("btc verify error: %s", exc)
        return None


# ---------------- TRON (USDT TRC20) ----------------
async def _verify_tron_events(
    client: httpx.AsyncClient, txid: str, addr: str
) -> VerifyResult | None:
    try:
        r = await client.get(
            f"https://api.trongrid.io/v1/transactions/{txid}/events"
        )
        if r.status_code != 200:
            return None
        events = r.json().get("data", [])
        for ev in events:
            if ev.get("event_name") != "Transfer":
                continue
            if ev.get("contract_address") != USDT_TRC20_CONTRACT:
                continue
            res = ev.get("result", {})
            if res.get("to") and res["to"].lower() == addr.lower():
                usd = int(res.get("value", "0")) / 1e6  # USDT 6 decimals
                return VerifyResult(True, "USDT-TRC20", usd)
        return VerifyResult(False, "USDT-TRC20", 0, "انتقالی به کیف‌پول ما در این تراکنش نیست")
    except Exception as exc:  # noqa: BLE001
        log.warning("tron events error: %s", exc)
        return None


# ---------------- EVM (BSC / ETH) ----------------
async def _rpc(client: httpx.AsyncClient, urls: list[str], method: str, params: list):
    for url in urls:
        try:
            r = await client.post(
                url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
            )
            if r.status_code == 200 and "result" in r.json():
                return r.json()["result"]
        except Exception:  # noqa: BLE001
            continue
    return None


async def _verify_evm(
    client: httpx.AsyncClient, txid: str, addr: str, chain: str, rates: dict
) -> VerifyResult | None:
    urls = BSC_RPCS if chain == "bsc" else ETH_RPCS
    usdt = USDT_BEP20_CONTRACT if chain == "bsc" else USDT_ERC20_CONTRACT
    usdt_dec = 1e18 if chain == "bsc" else 1e6
    native = "bnb" if chain == "bsc" else "eth"
    label = "BSC" if chain == "bsc" else "ETH"
    addr_l = addr.lower()

    receipt = await _rpc(client, urls, "eth_getTransactionReceipt", [txid])
    if receipt is None:
        return None
    if receipt.get("status") != "0x1":
        return VerifyResult(False, label, 0, "تراکنش ناموفق است")

    # 1) USDT transfer log to our address?
    for lg in receipt.get("logs", []):
        if (lg.get("address", "").lower() == usdt
                and len(lg.get("topics", [])) >= 3
                and lg["topics"][0].lower() == TRANSFER_TOPIC):
            to = "0x" + lg["topics"][2][-40:]
            if to.lower() == addr_l:
                amount = int(lg.get("data", "0x0"), 16) / usdt_dec
                return VerifyResult(True, f"USDT-{label}", amount)

    # 2) native transfer?
    tx = await _rpc(client, urls, "eth_getTransactionByHash", [txid])
    if tx and (tx.get("to") or "").lower() == addr_l:
        value = int(tx.get("value", "0x0"), 16) / 1e18
        usd = value * rates.get(native, 0)
        return VerifyResult(usd > 0, label.upper(), usd,
                            "" if usd > 0 else "نرخ ارز در دسترس نیست")
    return VerifyResult(False, label, 0, "انتقالی به کیف‌پول ما در این تراکنش نیست")


# ---------------- entry point ----------------
async def verify_txid(
    db: AsyncSession, txid: str, expected_usd: float
) -> VerifyResult:
    """Try all plausible networks for this TxID and check amount coverage."""
    txid = txid.strip()
    wallets = await _our_wallets(db)
    is_evm = txid.lower().startswith("0x") and len(txid) == 66
    is_hex64 = len(txid) == 64

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        rates = await _get_rates(client)
        candidates: list[VerifyResult | None] = []

        if is_evm:
            evm_addr = wallets.get("usdt_bnb") or wallets.get("bnb") or wallets.get("eth")
            if evm_addr:
                candidates.append(await _verify_evm(client, txid, evm_addr, "bsc", rates))
                candidates.append(await _verify_evm(client, txid, evm_addr, "eth", rates))
        elif is_hex64:
            if wallets.get("usdt_trc20"):
                candidates.append(
                    await _verify_tron_events(client, txid, wallets["usdt_trc20"])
                )
            if wallets.get("btc") and rates.get("btc"):
                candidates.append(
                    await _verify_btc(client, txid, wallets["btc"], rates["btc"])
                )
        else:
            return VerifyResult(False, "", 0, "فرمت TxID نامعتبر است")

        found = [c for c in candidates if c is not None]
        paid = [c for c in found if c.verified]
        if paid:
            best = max(paid, key=lambda c: c.amount_usd)
            if best.amount_usd >= expected_usd * TOLERANCE:
                return best
            return VerifyResult(
                False, best.network, best.amount_usd,
                f"مبلغ ناکافی: {best.amount_usd:.2f}$ از {expected_usd:.2f}$",
            )
        if found:
            return found[0]
        return VerifyResult(False, "", 0, "تراکنش در شبکه‌ها یافت نشد")
