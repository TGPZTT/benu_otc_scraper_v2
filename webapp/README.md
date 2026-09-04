# BENU OTC webapp

Statikus, lokális összehasonlító felület a scraper exportjára.

Indítás a projekt gyökeréből:

```powershell
.\.venv\Scripts\python.exe -m http.server 8000
```

Megnyitás:

```text
http://localhost:8000/webapp/
```

Az app ezt az adatfájlt olvassa:

```text
data/exports/grouped_catalog.json
```

Ha újraépíted az exportokat, a webapp automatikusan az új adatot használja.

Ha csak a normalizálás vagy a csoportosítás változott, scraping nélkül elég:

```powershell
.\.venv\Scripts\python.exe scripts\build_normalized_catalog.py
```

A felület hatóanyagcsalád -> erősség/forma -> termék bontásban dolgozik. A bal oldali menü fő kategóriára, alkategóriára és hatóanyagra is tud szűrni.
