# plantuml-render — рендеринг PlantUML диаграмм

Утилита для batch-рендеринга `.plantuml` файлов в PNG/SVG через Kroki-compatible API.
По умолчанию используется `https://kroki.io`, но можно переключиться на локальный Kroki в Docker.

## Быстрый старт

```bash
# Рендеринг через endpoint по умолчанию (https://kroki.io)
.tools/plantuml-render/plantuml-render --path docs/requirements/

# Запуск локального Kroki через Docker Compose
docker compose \
  -f .tools/plantuml-render/docker-compose.base.yml \
  -f .tools/plantuml-render/docker-compose.dev.yml \
  up -d

# Рендеринг через локальный Kroki
KROKI_BASE_URL=http://localhost:8000 \
.tools/plantuml-render/plantuml-render --path docs/requirements/
```

## Опции

* `--path`, `-p` — путь к `.plantuml` файлу или директории (default: `.`)
* `--format`, `-f` — формат вывода: `png`, `svg` (default: `png`)
* `--kroki-url` — базовый URL Kroki endpoint (default: `https://kroki.io`)
* `--timeout` — HTTP timeout в секундах (default: `30`)
* `--dry-run` — показать, что будет отрендерено, без записи файлов
* `--help`, `-h` — показать справку

## Конфигурация / ENV

* `KROKI_BASE_URL` — базовый URL Kroki (`https://kroki.io` или `http://localhost:8000`)
* `KROKI_TIMEOUT` — timeout HTTP-запроса в секундах (default: `30`)
* `KROKI_IMAGE` — образ Kroki для Docker Compose (default: `yuzutech/kroki:0.30.1`)
* `KROKI_PORT` — локальный порт публикации сервиса Kroki (default: `8000`)
* `KROKI_MAX_URI_LENGTH` — лимит URI внутри контейнера Kroki (default: `8192`)

Пример файла переменных: `.tools/plantuml-render/.env.example`.

## Входы / Выходы

* **Input:** `.plantuml` файлы в указанной директории (рекурсивно)
* **Output:** изображения (`.png` или `.svg`) рядом с исходными файлами

## Примеры

```bash
# Dry-run с локальным Kroki
KROKI_BASE_URL=http://localhost:8000 \
.tools/plantuml-render/plantuml-render --dry-run --path docs/requirements/

# SVG рендеринг через явно заданный endpoint
.tools/plantuml-render/plantuml-render \
  --format svg \
  --kroki-url http://localhost:8000 \
  --path docs/requirements/архитектура/diagrams/

# Остановка локального Kroki
docker compose \
  -f .tools/plantuml-render/docker-compose.base.yml \
  -f .tools/plantuml-render/docker-compose.dev.yml \
  down
```

## Зависимости

* Python 3.6+ (только стандартная библиотека)
* Docker + Docker Compose (опционально, для локального Kroki)

## Exit codes

* `0` — успех, все файлы отрендерены
* `1` — ошибка (файл не найден, ошибка сети, неверные параметры)
* `2` — warning (`--dry-run`)

## Платформы

* Windows 10+
* Linux
* macOS

## Troubleshooting

**Ошибка сети к `https://kroki.io`:**
используйте локальный Kroki (`http://localhost:8000`) и проверьте, что контейнер поднят.

**Ошибка подключения к локальному Kroki:**
проверьте порт `KROKI_PORT` и статус контейнера:
`docker compose -f .tools/plantuml-render/docker-compose.base.yml -f .tools/plantuml-render/docker-compose.dev.yml ps`.

**Python не найден:**
укажите переменную `PYTHON` в wrapper-скриптах или запускайте через `python .tools/plantuml-render/plantuml_render.py`.

## Ссылки

* Назад к разделу: `../README.md`
* Исходник: `.tools/plantuml-render/plantuml_render.py`
* Compose base: `.tools/plantuml-render/docker-compose.base.yml`
* Compose dev: `.tools/plantuml-render/docker-compose.dev.yml`
