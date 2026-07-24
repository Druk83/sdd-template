# Раздел .tools

В каталоге `.tools/` хранятся утилиты и скрипты, поддерживающие разработку и автоматизацию проекта.

## Структура

```text
.tools/
  README.md
  registry.json
  check-encoding/
  pdd/
    README.md
    pdd_scan.py
    pdd-scan
    pdd-scan.bat
  plantuml-render/
    README.md
    plantuml_render.py
    plantuml-render
    plantuml-render.bat
```

## Инструменты

* **check-encoding** — проверяет текстовые файлы на нарушения UTF-8 и mojibake.
* **pdd-scan** — сканирует `@todo` и обновляет реестр задач.
* **plantuml-render** — рендерит `.plantuml`, `.bpmn` и `.dot` в PNG/SVG через Kroki-compatible API; локальный Docker-стек включает BPMN companion-сервис и SVG-to-PNG rasterizer.

## Кроссплатформенный запуск

Каждый исполняемый инструмент зарегистрирован в `.tools/registry.json` и имеет универсальную Python-точку входа, а также wrapper-скрипты для Windows и Unix-подобных систем.

```bash
python .tools/plantuml-render/plantuml_render.py --format png --path <file-or-directory>
```

Для BPMN с локальным Kroki:

```bash
python .tools/plantuml-render/plantuml_render.py \
  --kroki-url http://localhost:8000 \
  --path <diagram.bpmn>
```

Для графа нормативного порядка в DOT:

```bash
python .tools/plantuml-render/plantuml_render.py \
  --diagram-type graphviz \
  --path <normative-order.dot>
```

## Ссылки

* В корень проекта: `/README.md`
* Реестр инструментов: `.tools/registry.json`
* Правила инструментов: `.manifest/toolsmanifest.md`
