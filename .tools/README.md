# Раздел .tools

В каталоге `.tools/` хранятся утилиты и скрипты, поддерживающие разработку и автоматизацию проекта (маленькие инструменты, которые не являются частью core-сервиса).

## Структура
```text
.tools/
  README.md
  registry.json
  pdd/
    README.md
    pdd_scan.py
    pdd-scan         # bash wrapper
    pdd-scan.bat     # Windows wrapper
  plantuml-render/
    README.md
    plantuml_render.py
    plantuml-render      # bash wrapper
    plantuml-render.bat  # Windows wrapper
```

## Инструменты

* **pdd** — сканирует `@todo` в исходниках и генерирует реестр задач → см. `.tools/pdd/README.md` (stable)
* **plantuml-render** — рендерит `.plantuml` файлы в PNG/SVG через Kroki.io API → см. `.tools/plantuml-render/README.md` (stable)

## Кроссплатформенный запуск

Каждый инструмент имеет три точки входа:
- `entry` — универсальная команда через python (работает везде)
- `entry_unix` — bash wrapper для Linux/macOS
- `entry_win` — .bat wrapper для Windows

**Рекомендуемый способ:** использовать `entry` из `registry.json`:
```bash
# Универсально (Windows/Linux/macOS)
python .tools/pdd/pdd_scan.py --format md
python .tools/plantuml-render/plantuml_render.py --format png
```

## Примечания об операционных файлах

* `registry.json` — машинно-удобный реестр утилит в `.tools/` (имя, путь, точка входа, теги). Поля `entry_win`/`entry_unix` — платформо-специфичные варианты запуска.

## Ссылки

* В корень проекта: `/README.md`
* Документация: `docs/` (если есть)
* Правила оформления README: `.manifest/readmemanifest.md`
