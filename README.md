# AZTEC Reader

Offline-ready aplikacja do dekodowania kodów 2D (priorytet: AZTEC) z plików PDF. Projekt działa lokalnie w Dockerze i nie wymaga zewnętrznych usług ani CDN.

## Uruchomienie

```bash
docker compose up --build
```

UI jest dostępne pod `http://localhost:8000/`.

## Limity i time-outy

- Max rozmiar pliku: **30MB** (`MAX_FILE_SIZE_MB`).
- Max stron PDF: **120** (`MAX_PAGES`).
- Timeout joba: **300s** (`JOB_TIMEOUT_SECONDS`).

Wszystkie wartości można nadpisać zmiennymi środowiskowymi w `docker-compose.yml`.

## API

### Tworzenie jobów

```bash
curl -F "files=@example.pdf" -F "only_aztec=true" http://localhost:8000/api/jobs
```

### Status joba

```bash
curl http://localhost:8000/api/jobs/<job_id>
```

### Pobranie wyników

```bash
curl "http://localhost:8000/api/jobs/<job_id>/download?fmt=json"
curl "http://localhost:8000/api/jobs/<job_id>/download?fmt=csv"
```

## Bezpieczeństwo

- PDF-y są zapisywane tylko tymczasowo w katalogu `/tmp` na czas przetwarzania joba i usuwane po zakończeniu.
- Aplikacja nie loguje treści zakodowanych w kodach 2D.
- Brak zewnętrznych API, CDN i usług chmurowych — wszystko działa lokalnie.

## Fallback ZXing CLI

Domyślnie używany jest `zxing-cpp`. Jeśli potrzebujesz fallbacku, ustaw `ZXING_JAR_PATH` na ścieżkę do lokalnego pliku `zxing-cli.jar` w kontenerze.

Przykład (mount z hosta):

```yaml
services:
  worker:
    volumes:
      - ./tools/zxing-cli.jar:/opt/zxing-cli.jar
    environment:
      ZXING_JAR_PATH: /opt/zxing-cli.jar
```
