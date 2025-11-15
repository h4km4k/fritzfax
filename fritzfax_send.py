#!/usr/bin/env python3
"""
fritzfax_send.py  -- Variante C: Autologin + multipart upload + start + status polling

Benutzung (kurz):
  python3 fritzfax_send.py --user admin --pass "PASSWORD" --dest 0123456 --src 123456 --from "Mein Absender" --subject "Test" --sff-base64 sff.b64

Optionen: siehe argparse help
"""
import requests
import hashlib
import time
import base64
import argparse
import json
import sys
import os
import random
import string
import subprocess
from typing import Optional

# ---------- Konfiguration (ändern falls nötig) ----------
FRITZBOX_URL = "http://192.168.0.1"  # oder http://fritz.box
LOGIN_SID_PATH = "/login_sid.lua"
DATA_LUA = "/data.lua"
FIRMWARECFG = "/cgi-bin/firmwarecfg"
FONDEV_FAXSEND = "/fon_devices/fax_send.lua"

# Default HTTP headers close to Browser
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Firefox/117.0",
    "Accept": "*/*",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
}

# ---------- Hilfsfunktionen ----------
def dbg(*args, **kwargs):
    if DEBUG:
        print("[DEBUG]", *args, **kwargs)

def random_boundary(prefix="geckoformboundary"):
    suffix = "".join(random.choice("0123456789abcdef") for _ in range(32))
    return "------" + prefix + suffix

def get_sid(session: requests.Session, username: str, password: str) -> str:
    """
    Holt SID via challenge-response. Wir verwenden utf-16le und MD5 wie Fritzbox verlangt.
    """
    url = FRITZBOX_URL.rstrip("/") + LOGIN_SID_PATH
    dbg("Rufe login_sid.lua auf...")
    r = session.get(url, headers=DEFAULT_HEADERS, timeout=10)
    r.raise_for_status()
    xml = r.text
    # einfache XML-Parsing via string ops (sollte für Fritz-XML zuverlässig sein)
    if "<Challenge>" not in xml:
        raise RuntimeError("Login response enthält keine Challenge. Antwort: " + xml[:400])
    challenge = xml.split("<Challenge>")[1].split("</Challenge>")[0]
    # compute MD5 of (challenge + "-" + password) encoded as UTF-16LE
    s_utf16 = f"{challenge}-{password}".encode("utf-16le")
    md5_hash = hashlib.md5(s_utf16).hexdigest()
    response = f"{challenge}-{md5_hash}"
    dbg("Sende Login-Form...")
    post = {"username": username, "response": response}
    r2 = session.post(url, data=post, headers={**DEFAULT_HEADERS, "Content-Type": "application/x-www-form-urlencoded"}, timeout=10)
    r2.raise_for_status()
    xml2 = r2.text
    sid = xml2.split("<SID>")[1].split("</SID>")[0]
    if sid == "0000000000000000":
        raise RuntimeError("Login fehlgeschlagen. Check credentials. Server Antwort: " + xml2[:600])
    dbg("Erhaltene SID:", sid)
    return sid

def open_fax_page(session: requests.Session, sid: str):
    """
    Öffnet/initialisiert die Fax-Seite (wie Browser das beim Start tut).
    """
    url = FRITZBOX_URL.rstrip("/") + DATA_LUA
    data = {
        "xhr": "1",
        "sid": sid,
        "page": "fax"
    }
    r = session.post(url, data=data, headers=DEFAULT_HEADERS, timeout=15)
    dbg("open_fax_page status:", r.status_code)
    dbg("open_fax_page resp (anfang):", r.text[:800])
    r.raise_for_status()
    return True

def send_fax_metadata(session: requests.Session, sid: str, dest_name: str, dest_num: str, from_text: str, src_num: str, subject: str, fax_text: str):
    """
    Sendet die Formular-Metadaten per data.lua (wie browser -> data.lua).
    """
    url = FRITZBOX_URL.rstrip("/") + DATA_LUA
    data = {
        "xhr": "1",
        "fonbooks": "manu",
        "fonbook": "choose",
        "dest_name": dest_name,
        "dest_num": dest_num,
        "from1": from_text,
        "src_num": src_num,
        "subject": subject,
        "fax_text": fax_text,
        "btn_send": "",
        "sid": sid,
        "lang": "de",
        "page": "fax"
    }
    r = session.post(url, data=data, headers=DEFAULT_HEADERS, timeout=15)
    dbg("send_fax_metadata status:", r.status_code)
    dbg("send_fax_metadata resp (anfang):", r.text[:800])
    r.raise_for_status()
    return True

def build_multipart(boundary: str, fields: dict, file_field_name: str, filename: str, file_bytes: bytes, file_content_type="application/octet-stream") -> bytes:
    """
    Baut einen multipart/form-data Body manuell mit vorgegebener boundary.
    fields: dict mit name->value (strings)
    file_field_name, filename, file_bytes -- Datei-Teil
    Rückgabe: bytes Body
    """
    # CRLF
    crlf = "\r\n"
    lines = []
    for name, val in fields.items():
        lines.append(f"{boundary}")
        lines.append(f'Content-Disposition: form-data; name="{name}"')
        lines.append("")  # leere Zeile
        lines.append(val)
    # File part
    lines.append(f"{boundary}")
    lines.append(f'Content-Disposition: form-data; name="{file_field_name}"')
    lines.append("")  # LEERE Zeile vor den Daten
    head = crlf.join(lines).encode("utf-8") + crlf.encode("utf-8")
    tail = (crlf + f"{boundary}--").encode("utf-8")
    body = head + file_bytes + tail
    return body

def send_fax_file(session: requests.Session, sid: str, dest_num: str, src_num: str,
                  sff_bytes: bytes, boundary: Optional[str] = None):

    if boundary is None:
        boundary = random_boundary()

    url = FRITZBOX_URL.rstrip("/") + FIRMWARECFG

    # Felder laut Firefox-Mitschnitt
    fields = {
        "sid": sid,
        "NumDest": dest_num,
        "NumSrc": src_num,
    }

    # Multipart body bauen (roh, ohne Requests-Magic)
    body = build_multipart(
        boundary, fields,
        "FaxUploadFile", "fax.sff",
        sff_bytes,
        file_content_type="application/octet-stream"
    )

    headers = dict(DEFAULT_HEADERS)
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    headers["Content-Length"] = str(len(body))

    # ⭐ WICHTIG: Browser-Sicherheitsheader ergänzen
    headers["Sec-Fetch-Dest"] = "empty"
    headers["Sec-Fetch-Mode"] = "cors"
    headers["Sec-Fetch-Site"] = "same-origin"

    # ⭐ WICHTIG: Chunked transfer verhindern
    headers["Expect"] = ""

    dbg("Sende firmwarecfg (multipart)...")

    # FIX: Wir senden Rohdaten mit exakt definiertem Content-Length
    r = session.post(url, data=body, headers=headers, timeout=60)

    dbg("firmwarecfg status:", r.status_code)
    dbg("firmwarecfg headers:", r.headers)
    dbg("firmwarecfg resp (anfang):", r.text[:1000])
    r.raise_for_status()
    return r


def start_fax(session: requests.Session, sid: str):
    """
    Startet den Faxversand via data.lua mit progress=start
    """
    url = FRITZBOX_URL.rstrip("/") + DATA_LUA
    data = {
        "xhr": "1",
        "sid": sid,
        "progress": "start",
        "page": "fax"
    }
    r = session.post(url, data=data, headers=DEFAULT_HEADERS, timeout=15)
    dbg("start_fax status:", r.status_code)
    dbg("start_fax resp (anfang):", r.text[:800])
    r.raise_for_status()
    return True

def poll_fax_status(session: requests.Session, sid: str, timeout_sec: int = 180, poll_interval: float = 2.0):
    """
    Polling gegen /fon_devices/fax_send.lua?query=refresh
    Timeout und Poll-Intervall einstellbar.
    Gibt das finale JSON zurück.
    """
    dbg("Starte Fax-Statusabfrage...")
    url = FRITZBOX_URL.rstrip("/") + FONDEV_FAXSEND
    start_t = time.time()
    attempt = 0
    while True:
        attempt += 1
        params = {
            "sid": sid,
            "no_sidrenew": "1",
            "myXhr": "1",
            "query": "refresh",
            "useajax": "1",
            "xhr": "1",
            # dynamischer Cache-Buster
            "t": str(int(time.time() * 1000))
        }
        try:
            r = session.get(url, params=params, headers=DEFAULT_HEADERS, timeout=15)
            dbg("Status:", r.status_code)
            r.raise_for_status()
            # Manche FRITZbox-Antworten liefern JSON direkt
            try:
                j = r.json()
            except Exception:
                dbg("Antwort kein JSON, Rohtext (anfang):", r.text[:300])
                j = {}
            dbg(f"[DEBUG] Status: {j}")
        except Exception as e:
            dbg("Fehler beim Abfragen des Status:", e)
            break

        status = j.get("status")
        status_text = j.get("status_text")
        progress = j.get("progress")
        reason = j.get("reason")
        dbg(f"Faxstatus: {status_text} progress: {progress} reason: {reason}")

        # Interpretation der Statuscodes (basierend auf deinem Log)
        if status == 5 or status_text == "FAXSEND_REPORT":
            dbg("Faxsend reported (end). JSON:", j)
            return j
        if status in (3, 4):
            # 3 = connecting, 4 = connected
            # Wir warten weiter, evtl. progress bleibt 0
            pass
        else:
            # Fehler oder unbekannter Status -> brechen
            dbg("Unbekannter/Fehler-Status erhalten, Abbruch. JSON:", j)
            return j

        # timeout check
        if time.time() - start_t > timeout_sec:
            dbg("Timeout beim Polling erreicht.")
            return {"status": -1, "status_text": "TIMEOUT"}
        time.sleep(poll_interval)

# ---------- SFF Loading / Generierung ----------
def load_sff_bytes_from_args(args) -> bytes:
    """
    Akzeptiert entweder:
      - --sff-file path (binär .sff)
      - --sff-base64 string oder path (wenn es eine Datei ist, lesen)
      - --text "..." -> ruft node fax_renderer.js auf (Erwartung: stdout = base64)
    liefert: sff bytes (Base64-encoded, wie --text Version)
    """

    # --- sff-file: Binär einlesen und direkt Base64-encode ---
    if args.sff_file:
        dbg("Lese SFF-Binärdatei:", args.sff_file)
        with open(args.sff_file, "rb") as f:
            data = f.read()
        return base64.b64encode(data)  # als Bytes, wie --text

    # --- sff-base64: Base64-String aus Datei oder Argument ---
    if args.sff_base64:
        # Prüfen, ob es ein Pfad ist
        if os.path.exists(args.sff_base64):
            dbg("Lese SFF-Base64 aus Datei:", args.sff_base64)
            with open(args.sff_base64, "r") as f:
                sff_b64 = f.read().strip()
        else:
            sff_b64 = args.sff_base64.strip()
        # direkt als Bytes zurückgeben (nicht dekodieren!)
        return sff_b64.encode("ascii")

    # --- image: Node.js Renderer ---
    if args.image:
        dbg("Generiere SFF via Node (fax_renderer.js) aus Bild:", args.image)
        try:
            proc = subprocess.run(
                ["node", "fax_renderer.js", args.image],
                capture_output=True,
                text=True,
                timeout=60
            )
        except FileNotFoundError:
            raise RuntimeError("Node.js nicht gefunden. Installiere Node oder liefere --sff-file / --sff-base64 / --text / --image")
        
        if proc.returncode != 0:
            dbg("Node stderr:", proc.stderr)
            raise RuntimeError("fax_renderer.js Fehler. stdout: " + proc.stdout[:400] + " stderr: " + proc.stderr[:400])
        
        sff_b64 = proc.stdout.strip()
        return sff_b64.encode("ascii")
    
    # --- text-file: Node.js Renderer ---
    if args.text_file:
        if not os.path.exists(args.text_file):
            raise RuntimeError(f"Textdatei nicht gefunden: {args.text_file}")
        dbg("Generiere SFF via Node (fax_renderer.js) aus Textdatei:", args.text_file)
        with open(args.text_file, "r", encoding="utf-8") as f:
            text = f.read()
        payload = json.dumps({"text": text})
        try:
            proc = subprocess.run(
                ["node", "fax_renderer.js", text],
                capture_output=True,
                text=True,
                timeout=60
            )
        except FileNotFoundError:
            raise RuntimeError("Node.js nicht gefunden. Installiere Node oder liefere --sff-file / --sff-base64 / --text / --image / --text-file")
        if proc.returncode != 0:
            dbg("Node stderr:", proc.stderr)
            raise RuntimeError("fax_renderer.js Fehler. stdout: " + proc.stdout[:400] + " stderr: " + proc.stderr[:400])
        sff_b64 = proc.stdout.strip()
        return sff_b64.encode("ascii")

    # --- text: Node.js Renderer ---
    if args.text:
        dbg("Generiere SFF via Node (fax_renderer.js) aus Text...")
        payload = json.dumps({"text": args.text})
        try:
            proc = subprocess.run(
                ["node", "fax_renderer.js", args.text],
                capture_output=True,
                text=True,
                timeout=60
            )
        except FileNotFoundError:
            raise RuntimeError("Node.js nicht gefunden. Installiere Node oder liefere --sff-file / --sff-base64 / --text / --image / --text-file")
        if proc.returncode != 0:
            dbg("Node stderr:", proc.stderr)
            raise RuntimeError("fax_renderer.js Fehler. stdout: " + proc.stdout[:400] + " stderr: " + proc.stderr[:400])
        sff_b64 = proc.stdout.strip()
        return sff_b64.encode("ascii")

    # --- kein Argument ---
    raise RuntimeError("Keine SFF-Quelle angegeben. Verwende --sff-file, --sff-base64 oder --text.")

# ---------- CLI / Main ----------
def main():

    global DEBUG

    global FRITZBOX_URL

    p = argparse.ArgumentParser(description="Sende Fax über FRITZ!Box (Variante C: Autologin + multipart + Polling)")
    p.add_argument("--url", default=FRITZBOX_URL, help="Basis-URL der Fritzbox (z.B. http://192.168.0.1 oder http://fritz.box)")
    p.add_argument("--user", required=True, help="Fritzbox Benutzername")
    p.add_argument("--pass", dest="password", required=True, help="Fritzbox Passwort")
    p.add_argument("--dest", required=True, help="Zielnummer (NumDest)")
    p.add_argument("--dest-name", default="FAX", help="Zielname (dest_name)")
    p.add_argument("--src", required=True, help="Quellnummer (NumSrc)")
    p.add_argument("--from", dest="from_text", default="", help="Anzeigename / Absenderzeile (from1)")
    p.add_argument("--subject", default="Fax", help="Betreff")
    p.add_argument("--image", help="Pfad zu einem Bild (PNG/JPG). Wird via Node.js zu SFF konvertiert.")
    p.add_argument("--text", help="Text, falls du node fax_renderer.js verwenden willst (alternativ --sff-file/--sff-base64)")
    p.add_argument("--text-file", help="Pfad zur Textdatei, die als Fax gesendet werden soll (wird via Node.js zu SFF konvertiert)")
    p.add_argument("--sff-file", help="Pfad zur SFF-Binärdatei (statt Node-Generierung)")
    p.add_argument("--sff-base64", help="SFF als Base64-String oder Pfad zu einer Datei mit Base64")
    p.add_argument("--boundary", help="Optional: feste Boundary für multipart (wenn du exakt HAR-Boundary nachbauen willst)")
    p.add_argument("--timeout", type=int, default=240, help="Timeout für Polling in Sekunden")
    p.add_argument("--poll-interval", type=float, default=2.0, help="Polling Intervall in Sekunden")
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()

    FRITZBOX_URL = args.url.rstrip("/")

    DEBUG = args.debug

    sess = requests.Session()

    try:
        sid = get_sid(sess, args.user, args.password)
        # open fax page (initialisiert)
        open_fax_page(sess, sid)
        # send metadata
        send_fax_metadata(sess, sid, args.dest_name, args.dest, args.from_text, args.src, args.subject, args.text or "")
        # prepare SFF bytes
        sff_bytes = load_sff_bytes_from_args(args)
        dbg("SFF Länge (Bytes):", len(sff_bytes))
        # send file (firmwarecfg) - optionally with provided boundary
        boundary = args.boundary if args.boundary else random_boundary()
        resp = send_fax_file(sess, sid, args.dest, args.src, sff_bytes, boundary=boundary)
        dbg("Upload abgeschlossen, response status:", resp.status_code)
        # start fax
        start_fax(sess, sid)
        # poll status
        result = poll_fax_status(sess, sid, timeout_sec=args.timeout, poll_interval=args.poll_interval)
        dbg("Finaler Poll-Result:", result)
        print("=== FERTIG ===")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print("[ERROR] ", e, file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
