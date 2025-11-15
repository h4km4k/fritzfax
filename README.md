# FritzFax Python Sender

Ein Python-Skript zum automatisierten Senden von Faxen über die integrierte Faxfunktion der FRITZ!Box.

**Features:**

* Authentifizierung via FRITZ!Box Challenge-Response (MD5).
* Unterstützung für Text-Faxe, Bilder und SFF-Dateien.
* Automatischer Multipart-Upload der Faxdaten (`/cgi-bin/firmwarecfg`).
* Start und Statusabfrage des Faxversands über die Web-API (`data.lua`, `fax_send.lua`).
* Flexible Eingabe: Text direkt, Textdateien, SFF-Binärdateien, Base64-codierte SFFs, Bilder über Node.js-Konvertierung.
* Polling des Versandstatus mit Timeout und Fortschrittsanzeige.

**Voraussetzungen:**

* Python 3
* `requests`-Modul
* Node.js (für Text- und Bild-zu-SFF-Konvertierung)

**Beispielaufruf:**

```bash
python3 fritzfax_send.py --user faxuser --pass "PASSWORD" --dest 0123456 --src 123456 --from "Mein Absender" --subject "Test" --text "Hallo Welt"
python3 fritzfax_send.py --user faxuser --pass "PASSWORD" --dest 0123456 --src 123456 --text-file message.txt
python3 fritzfax_send.py --user faxuser --pass "PASSWORD" --dest 0123456 --src 123456 --image faxpage.png
python3 fritzfax_send.py --user faxuser --pass "PASSWORD" --dest 0123456 --src 123456 --sff-file fax.sff
python3 fritzfax_send.py --user faxuser --pass "PASSWORD" --dest 0123456 --src 123456 --sff-base64 fax.b64
```

**Ziel:**
Automatisierter Faxversand ohne manuelle Bedienung der FRITZ!Box-Weboberfläche, mit Unterstützung für Text, Bilder und SFF-Faxe.
