# plantuml-render — рендеринг PlantUML, BPMN и Graphviz-диаграмм

Утилита пакетно рендерит файлы `.plantuml`, `.bpmn` и `.dot` в PNG или SVG через Kroki-compatible API. Тип диаграммы определяется по расширению: PlantUML передаётся в endpoint `plantuml`, BPMN — в endpoint `bpmn`, DOT — в endpoint `graphviz`.

Endpoint задаётся через `KROKI_BASE_URL` в `.tools/plantuml-render/.env` или параметр `--kroki-url`. Можно использовать публичный `https://kroki.io`. Kroki рендерит BPMN только в SVG, поэтому для PNG локальный Docker-стек дополнительно запускает rasterizer-сервис на основе `kroki-bpmn` и встроенного Chromium.

Локальный стек передает PlantUML ограничение `PLANTUML_LIMIT_SIZE=8192`. Это максимальный размер стороны изображения, а не фиксированный размер холста: PNG создается по фактическому содержимому без принудительных пустых полей. При необходимости значение можно изменить в `.tools/plantuml-render/.env`.

## Быстрый старт

Перед первым запуском создайте рабочую конфигурацию из `.env.example`:

```bash
cp .tools/plantuml-render/.env.example .tools/plantuml-render/.env
```

```bash
# Рендеринг всех поддерживаемых диаграмм в директории
.tools/plantuml-render/plantuml-render --path docs/requirements/

# Рендеринг одной BPMN-диаграммы через публичный Kroki
.tools/plantuml-render/plantuml-render \
  --path .source/техкарты/diagrams/TK-002-разгрузка-и-приемка.bpmn

# Запуск локального Kroki с поддержкой BPMN
docker compose \
  --env-file .tools/plantuml-render/.env \
  -f .tools/plantuml-render/docker-compose.base.yml \
  -f .tools/plantuml-render/docker-compose.dev.yml \
  up -d

# Рендеринг BPMN через локальный Kroki
.tools/plantuml-render/plantuml-render \
  --path .source/техкарты/diagrams/TK-002-разгрузка-и-приемка.bpmn
```

На Windows используйте `plantuml-render.bat` или прямой вызов Python:

```powershell
Copy-Item '.tools\plantuml-render\.env.example' '.tools\plantuml-render\.env'

python .tools/plantuml-render/plantuml_render.py `
  --kroki-url http://localhost:8000 `
  --path '.source\техкарты\diagrams\TK-002-разгрузка-и-приемка.bpmn'
```

## Самостоятельное обновление PNG

Выполняйте команды из корня проекта. После изменения BPMN-файла запустите локальный Kroki и обновите PNG:

```powershell
docker compose `
  --env-file .tools/plantuml-render/.env `
  -f .tools/plantuml-render/docker-compose.base.yml `
  -f .tools/plantuml-render/docker-compose.dev.yml `
  up -d

.tools\plantuml-render\plantuml-render.bat `
  --kroki-url http://localhost:8000 `
  --path '.source\техкарты\diagrams\TK-002-разгрузка-и-приемка.bpmn'
```

Файл `TK-002-разгрузка-и-приемка.png` будет перезаписан рядом с исходной диаграммой. После завершения локальные сервисы можно остановить:

```powershell
docker compose `
  --env-file .tools/plantuml-render/.env `
  -f .tools/plantuml-render/docker-compose.base.yml `
  -f .tools/plantuml-render/docker-compose.dev.yml `
  down
```

## Опции

* `--path`, `-p` — путь к файлу `.plantuml` / `.bpmn` / `.dot` или директории; поиск рекурсивный, default: `.`.
* `--diagram-type`, `--type` — фильтр `auto`, `plantuml`, `bpmn` или `graphviz`; default: `auto`.
* `--format`, `-f` — формат вывода: `png`, `svg`; default: `png`.
* `--kroki-url` — базовый URL Kroki endpoint; по умолчанию значение `KROKI_BASE_URL` из `.tools/plantuml-render/.env`.
* `--timeout` — HTTP timeout в секундах; по умолчанию значение `KROKI_TIMEOUT` из `.tools/plantuml-render/.env`.
* `--bpmn-png-url` — URL локального сервиса преобразования BPMN SVG в PNG. Для `http://localhost:8000` автоматически используется `http://localhost:8001`.
* `--dry-run` — показать файлы, которые будут обработаны, без записи PNG/SVG.
* `--help`, `-h` — показать справку.

## Входы / выходы

* Input: файлы `.plantuml`, `.bpmn` и `.dot` в указанной директории или конкретный файл.
* Output: `.png` или `.svg` рядом с исходником. Например, `1.bpmn` создаёт `1.png`.

## Локальный Kroki

`docker-compose.base.yml` поднимает три сервиса:

* `kroki` — HTTP gateway на порту 8000;
* `bpmn` — companion-сервис `yuzutech/kroki-bpmn` на внутреннем порту 8003.
* `bpmn-png` — локальный SVG-to-PNG rasterizer на порту 8001.

Python читает боевой `.env` относительно пути самого скрипта, поэтому рабочая директория не влияет на выбор конфигурации. При отсутствии файла или обязательного ключа инструмент завершает работу с ошибкой.

Gateway получает адрес BPMN-сервиса из `KROKI_BPMN_HOST=bpmn`. Инструмент отправляет SVG из Kroki в `bpmn-png` только при запрошенном формате PNG. Версии образов и порты задаются только в боевом `.tools/plantuml-render/.env`; `.env.example` используется только как шаблон для его восстановления.

Проверка перед рендерингом:

```bash
.tools/plantuml-render/plantuml-render \
  --dry-run \
  --path .source/техкарты/diagrams/
```

Остановка локального Kroki:

```bash
docker compose \
  --env-file .tools/plantuml-render/.env \
  -f .tools/plantuml-render/docker-compose.base.yml \
  -f .tools/plantuml-render/docker-compose.dev.yml \
  down
```

## Зависимости

* Python 3.10+; используются только модули стандартной библиотеки. Для разработки рекомендуется Python 3.12+.
* Docker и Docker Compose — опционально, для локального Kroki.

## Exit codes

* `0` — все файлы обработаны.
* `1` — ошибка параметров, пути, сети или рендеринга.
* `2` — предупреждение, в том числе успешный `--dry-run`.

## Troubleshooting

Если PNG не создаётся для BPMN, убедитесь, что одновременно запущены `kroki`, `bpmn` и `bpmn-png`, а порты `8000` и `8001` доступны на localhost.

Если публичный Kroki недоступен, запустите локальный стек и передайте `--kroki-url http://localhost:8000`.

## Ссылки

* Назад к разделу: `../README.md`
* Исходник: `.tools/plantuml-render/plantuml_render.py`
* Compose base: `.tools/plantuml-render/docker-compose.base.yml`
* Compose dev: `.tools/plantuml-render/docker-compose.dev.yml`
