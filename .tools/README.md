# Раздел .tools

В каталоге `.tools/` хранятся утилиты и скрипты, поддерживающие разработку и автоматизацию проекта.

## Структура

```text
.tools/
  README.md
  registry.json
  agent-logic/
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
  sdd-template-release/
    README.md
    build_release.py
    install_framework.py
```

## Инструменты

* **agent-logic** — компилирует UTF-8 text и Markdown в проверяемую модель ASIR и обрабатывает `agent_context`.
* **check-encoding** — проверяет текстовые файлы на нарушения UTF-8 и mojibake.
* **pdd-scan** — сканирует `@todo` и обновляет реестр задач.
* **plantuml-render** — рендерит `.plantuml`, `.bpmn` и `.dot` в PNG/SVG через Kroki-compatible API; локальный Docker-стек включает BPMN companion-сервис и SVG-to-PNG rasterizer.
* **sdd-template-release** — выбирает релиз из `release-registry.json`, собирает и устанавливает его в `.agents/sdd-template-X.Y.Z/`; каталоги `.agents/` и `tmp/` не публикуются.

`agent-logic` является обязательной частью поставки SDD Framework. Перед запуском
проверь `.tools/agent-logic/manifest.json` и следуй
`.tools/agent-logic/agent-logic.instructions.md`. Создаваемые инструментом данные
хранятся в `.tools/agent-logic/.runtime/` и не входят в экспорт.

## Версионирование

Версия каждого инструмента указывается в его README отдельной строкой:

> Версия инструмента: `X.Y.Z`.

Это канонический источник версии инструмента. Поле `version` в `.tools/registry.json`
дублирует значение и служит быстрым справочником текущих версий зарегистрированных инструментов.
Общие правила SemVer находятся в `.manifest/versionmanifest.md`, а правила increment
для CLI-инструментов — в `.manifest/toolsmanifest.md`, разделе `tools.H4.11`.

В исходном коде инструмента hardcoded-версия не указывается.
При изменении версии сначала обновляется README, затем `registry.json`.

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
* Общие правила версионирования: `.manifest/versionmanifest.md`
* Стандарт экспорта SDD Framework: `.manifest/exportmanifest.md`
