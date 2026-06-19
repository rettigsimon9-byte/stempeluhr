# ⏱️ Stempeluhr (NFC-Zeiterfassung)

Antippen eines NFC-Stickers stempelt automatisch ein/aus. Pro Tag eine Zeile
(Kommen / Gehen / Stunden). Zeiten lassen sich in der App nachträglich
bearbeiten, hinzufügen und löschen.

## Wie es funktioniert

Der NFC-Sticker enthält die URL `…/s/<TOKEN>`:
- **1. Scan am Tag** → *Kommen* (neue Tageszeile mit Startzeit)
- **2. Scan am Tag** → *Gehen* (Endzeit + berechnete Stunden in derselben Zeile)
- **3. Scan am Tag** → ignoriert (Tag bereits vollständig)

Übersicht & Bearbeiten: `…/?t=<TOKEN>`

## Konfiguration (Umgebungsvariablen)

| Variable | Zweck |
|---|---|
| `STAMP_TOKEN` | geheimer Token in der URL (Schutz vor Fremd-Stempeln) |
| `TZ` | Zeitzone, Standard `Europe/Berlin` |
| `DATABASE_URL` | Postgres-URL (Railway). Ohne diese → lokale SQLite-Datei `stempeluhr.db` |

## Lokal starten

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
STAMP_TOKEN=test ./venv/bin/uvicorn app:app --reload
# http://localhost:8000/?t=test
```

## Deployment

Auf **Railway**: Repo verbinden, Postgres-Service hinzufügen (liefert `DATABASE_URL`),
`STAMP_TOKEN` setzen. Start-Befehl steht im `Procfile`.
