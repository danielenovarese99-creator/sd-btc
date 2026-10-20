"""
Notifiche email per le run giornaliere (stesso file in RAPS e in btc_1349).

Cattura tutto cio' che lo script stampa durante la run e, a fine run, manda una email SOLO se
e' successo qualcosa: ordini eseguiti o falliti (posizioni cambiate), errori, eccezioni.
Una run senza novita' non manda niente. Con DRY_RUN=true non manda niente (a meno di NOTIFY_DRY_RUN=true).

Configurazione nel .env della strategia:
    SMTP_HOST=smtp.gmail.com          (default)
    SMTP_PORT=587                     (default, STARTTLS)
    SMTP_USER=tuoindirizzo@gmail.com
    SMTP_PASSWORD=<password per le app di Google, 16 caratteri, NON la password normale>
    EMAIL_TO=tuoindirizzo@gmail.com   (default: SMTP_USER)
    NOTIFY_DRY_RUN=false              (true per provare le email anche in dry-run)

Test: python notify.py test
Un errore nell'invio non interrompe MAI la strategia: viene solo stampato nel log.
"""
import os
import smtplib
import sys
from datetime import datetime, timezone
from email.message import EmailMessage


class _Tee:
    def __init__(self, stream, buf):
        self.stream, self.buf = stream, buf

    def write(self, s):
        self.buf.append(s)
        return self.stream.write(s)

    def flush(self):
        self.stream.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


def start_capture() -> list:
    buf = []
    sys.stdout = _Tee(sys.__stdout__, buf)
    sys.stderr = _Tee(sys.__stderr__, buf)
    return buf


KEY_PREFIXES = ("[OK]", "[FALLITO]", "[FALLBACK]", "[LEVA]", "[REGIME]", "[RIEPILOGO]", "[WARN]", "[ERRORE]",
                "[FATAL]", "[LIVE]", "[DRY-RUN]", "Target di oggi", "Chiudo posizione", "Apro nuova posizione",
                "Posizione attuale", "Ordine:", "Capitale", "Equity", "Asset allocabili", "Oscillatore",
                "Run completata", "Run terminata")


def _send(subject: str, body: str) -> None:
    user = os.environ.get("SMTP_USER", "")
    pwd = os.environ.get("SMTP_PASSWORD", "")
    to = os.environ.get("EMAIL_TO", "") or user
    if not (user and pwd and to):
        print("[NOTIFY] email non configurata (SMTP_USER / SMTP_PASSWORD / EMAIL_TO in .env): nessuna notifica.")
        return
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.set_content(body)
    host, port = os.environ.get("SMTP_HOST", "smtp.gmail.com"), int(os.environ.get("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=30) as s:
        s.starttls()
        s.login(user, pwd)
        s.send_message(msg)
    print(f"[NOTIFY] email inviata a {to}")


def finish(name: str, buf: list, exit_code: int = 0) -> None:
    """Chiamare a fine run. Decide se mandare la mail e la manda. Non solleva mai eccezioni."""
    try:
        sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
        text = "".join(buf)
        lines = text.splitlines()
        dry = "DRY_RUN=True" in text or "[DRY-RUN]" in text and "[LIVE]" not in text
        has_live_ok = any(l.startswith("[OK]") for l in lines)
        has_fail = any(l.startswith(("[FALLITO]", "[FATAL]", "[ERRORE]")) for l in lines) \
            or "Traceback" in text or exit_code != 0
        if dry and os.environ.get("NOTIFY_DRY_RUN", "false").lower() != "true":
            return
        if not (has_live_ok or has_fail):
            return
        now = f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC"
        if has_fail:
            subject = f"[{name}] ERRORE o ordine fallito - {now}"
        else:
            subject = f"[{name}] posizioni cambiate - {now}"
        key = [l for l in lines if l.startswith(KEY_PREFIXES)]
        body = "RIEPILOGO\n" + "\n".join(key[:60]) + "\n\n" + "=" * 40 + "\nLOG COMPLETO\n" + text[-12000:]
        _send(subject, body)
    except Exception as e:  # la notifica non deve mai rompere la strategia
        print(f"[NOTIFY] invio email fallito: {e}")


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        _send("[TEST] notifiche strategia", "Se leggi questa email, le notifiche funzionano.")
    else:
        print("Uso: python notify.py test")
