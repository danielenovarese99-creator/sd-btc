"""Esecuzione su Hyperliquid: porta la posizione BTC al livello target (pieno / ridotto dopo il TP / ingresso / flip)."""

import math

from eth_account import Account as EthAccount
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants

import config as cfg


def base_url() -> str:
    return constants.TESTNET_API_URL if cfg.USE_TESTNET else constants.MAINNET_API_URL


def get_info() -> Info:
    return Info(base_url(), skip_ws=True)


def get_exchange() -> Exchange:
    wallet = EthAccount.from_key(cfg.AGENT_PRIVATE_KEY)
    return Exchange(wallet, base_url(), account_address=cfg.ACCOUNT_ADDRESS, vault_address=cfg.VAULT_ADDRESS)


def trading_address() -> str:
    """Indirizzo di cui leggere posizioni e saldo: il sub-account se configurato, altrimenti l'account."""
    return cfg.VAULT_ADDRESS or cfg.ACCOUNT_ADDRESS


def get_position_size(info: Info, coin: str) -> float:
    """Size firmata sul perp (>0 long, <0 short, 0 flat)."""
    state = info.user_state(trading_address())
    for p in state.get("assetPositions", []):
        if p["position"]["coin"] == coin:
            return float(p["position"]["szi"])
    return 0.0


def get_sz_decimals(info: Info, coin: str) -> int:
    for a in info.meta()["universe"]:
        if a["name"] == coin:
            return int(a["szDecimals"])
    raise RuntimeError(f"{coin} non trovato in meta()")


def get_mid(info: Info, coin: str) -> float:
    return float(info.all_mids()[coin])


def round_size(x: float, sz_decimals: int) -> float:
    f = 10 ** sz_decimals
    return math.floor(x * f) / f


def round_price(x: float, sz_decimals: int, max_decimals: int = 6) -> float:
    """
    Arrotonda il PREZZO secondo le regole ufficiali di Hyperliquid:
    - al massimo 5 cifre significative
    - al massimo (max_decimals - sz_decimals) decimali (max_decimals=6 per i perp)
    - i prezzi interi sono sempre validi, a prescindere dalle cifre significative
    Porting fedele della logica RoundOrderPrice usata dagli SDK ufficiali.
    """
    if x <= 0:
        return x
    if x == int(x):
        return float(int(x))

    max_sig_figures = 5
    allowed_decimals = max_decimals - sz_decimals
    int_part_digits = len(str(int(x)))

    if int_part_digits >= max_sig_figures:
        return round_size(x, 0)

    allowed_sig_figures = max_sig_figures - int_part_digits

    if x < 1:
        # sotto l'unita' gli zeri dopo il punto non contano come cifre significative
        text = f"{round_size(x, allowed_decimals):.{allowed_decimals}f}"
        sig_count = 0
        started = False
        for i, ch in enumerate(text):
            if ch in (".", "0") and not started:
                if ch == "0":
                    continue
                if ch == ".":
                    continue
            started = True
            sig_count += 1
            if sig_count == allowed_sig_figures:
                return float(text[: i + 1])
        return float(text)
    else:
        decimals = min(allowed_sig_figures, allowed_decimals)
        return round_size(x, max(decimals, 0))


def parse_order_result(result) -> tuple:
    """(ok, errore, size_eseguita). ok=True solo se risulta un fill."""
    try:
        if not isinstance(result, dict) or result.get("status") != "ok":
            return False, f"risposta non ok: {result}", 0.0
        st = result["response"]["data"]["statuses"][0]
        if "error" in st:
            return False, st["error"], 0.0
        if "filled" in st:
            return True, None, float(st["filled"]["totalSz"])
        if "resting" in st:
            return False, "ordine rimasto 'resting' (inatteso per un IOC)", 0.0
        return False, f"status inatteso: {st}", 0.0
    except Exception as e:  # noqa: BLE001
        return False, f"risposta non interpretabile ({e}): {result}", 0.0


def send_ioc(exchange: Exchange, coin: str, is_buy: bool, size: float, mid: float,
             sz_decimals: int, reduce_only: bool = False) -> dict:
    size = round_size(size, sz_decimals)
    px = round_price(mid * (1 + cfg.IOC_SLIPPAGE_BUFFER) if is_buy else mid * (1 - cfg.IOC_SLIPPAGE_BUFFER),
                     sz_decimals)
    side = "BUY" if is_buy else "SELL"
    if size <= 0:
        print(f"[SKIP] {coin}: size arrotondata a 0")
        return {"ok": False, "error": "size 0"}
    if cfg.DRY_RUN:
        print(f"[DRY-RUN] {side} {coin} size={size} limit_px={px} reduce_only={reduce_only}")
        return {"ok": True, "error": None, "filled": size}
    result = exchange.order(coin, is_buy, size, px, {"limit": {"tif": "Ioc"}}, reduce_only=reduce_only)
    print(f"[LIVE] {side} {coin} size={size} limit_px={px} -> {result}")
    ok, err, filled = parse_order_result(result)
    if ok:
        print(f"[OK] {coin}: eseguito {filled} (richiesto {size})")
        if filled < size * 0.99:
            print(f"[WARN] fill parziale: {filled} su {size}")
    else:
        print(f"[FALLITO] {coin}: {err}")
    return {"ok": ok, "error": err, "filled": filled}


def get_position(info: Info, coin: str) -> tuple:
    """(size firmata, prezzo medio di ingresso)."""
    state = info.user_state(trading_address())
    for p in state.get("assetPositions", []):
        if p["position"]["coin"] == coin:
            return float(p["position"]["szi"]), float(p["position"]["entryPx"] or 0)
    return 0.0, 0.0


def sync_position(info: Info, exchange: Exchange, coin: str, pos: int, flip: bool, tp_done: bool) -> bool:
    """
    pos     = direzione della strategia (+1 / -1 / 0)
    flip    = True se sulla barra appena chiusa c'e' stato un incrocio (nuovo trade)
    tp_done = True se nel trade corrente lo z-score ha gia' raggiunto la soglia (TP parziale da prendere/preso)
    Stateless: lo stato si deduce dalla posizione reale (notional di ingresso rispetto al notional pieno).
    Ritorna False se un ordine e' fallito.
    """
    actual, entry_px = get_position(info, coin)
    mid = get_mid(info, coin)
    sz_dec = get_sz_decimals(info, coin)
    sign = (actual > 0) - (actual < 0)
    notional = cfg.STRAT_CAPITAL_USD * cfg.LEVERAGE_FACTOR
    print(f"Posizione attuale {coin}: {actual} (notional ~${abs(actual) * mid:,.2f}, entry {entry_px}) | "
          f"strategia: dir={pos:+d} flip={flip} tp_done={tp_done}")

    if pos == 0:
        print("Strategia non ancora in trade (warm-up): nessuna azione.")
        return True
    if cfg.STRAT_CAPITAL_USD <= 0:
        print("[ERRORE] STRAT_CAPITAL_USD non impostato in .env: non posso calcolare la size.")
        return False

    # 1) incrocio sulla barra appena chiusa, oppure posizione assente/opposta -> ingresso/flip a size piena
    if sign != pos:
        if sign == 0 and cfg.WAIT_FOR_FLIP and not flip:
            print("WAIT_FOR_FLIP attivo: aspetto il prossimo incrocio, nessun ingresso ora.")
            return True
        target_size = pos * notional / mid
        delta = target_size - actual                      # flip = chiusura + apertura in un solo ordine
        if abs(delta) * mid < cfg.MIN_NOTIONAL_USD:
            print(f"[SKIP] differenza di ${abs(delta) * mid:.2f} sotto il minimo.")
            return True
        print(f"Ordine: {'compro' if delta > 0 else 'vendo'} {abs(delta):.6f} {coin} (da {sign:+d} a {pos:+d}, "
              f"notional target ${notional:,.2f})")
        return bool(send_ioc(exchange, coin, delta > 0, abs(delta), mid, sz_dec)["ok"])

    # 2) stessa direzione: se il TP e' scattato e la posizione e' ancora piena, riduci al residuo
    if cfg.TP_FRACTION > 0 and tp_done:
        entry_notional = abs(actual) * (entry_px or mid)
        if entry_notional > notional * (1 - cfg.TP_FRACTION / 2):          # ancora "piena"
            reduce_sz = abs(actual) * cfg.TP_FRACTION
            if reduce_sz * mid < cfg.MIN_NOTIONAL_USD:
                print(f"[SKIP] TP: quantita' da chiudere (${reduce_sz * mid:.2f}) sotto il minimo.")
                return True
            print(f"TAKE PROFIT parziale: chiudo {cfg.TP_FRACTION:.0%} ({reduce_sz:.6f} {coin})")
            return bool(send_ioc(exchange, coin, actual < 0, reduce_sz, mid, sz_dec, reduce_only=True)["ok"])
        print("TP gia' preso (posizione gia' ridotta): nessuna azione.")
        return True

    print("Nessuna azione.")
    return True
