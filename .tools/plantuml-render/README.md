# plantuml-render — рендеринг PlantUML диаграмм

Утилита для batch-рендеринга `.plantuml` файлов в PNG/SVG через Kroki.io API. Не требует локальной установки Java или PlantUML.

## Быстрый старт

```bash
# Рендеринг всех .plantuml файлов в текущей директории
.tools/plantuml-render/plantuml-render

# Рендеринг файлов в конкретной директории
.tools/plantuml-render/plantuml-render --path примеры/Виды_архитектур/

# Проверка без рендеринга (dry-run)
.tools/plantuml-render/plantuml-render --dry-run
```

## Опции

* `--path`, `-p` — путь к .plantuml файлу или директории (default: `.`)
* `--format`, `-f` — формат вывода: `png`, `svg` (default: `png`)
* `--dry-run` — показать что будет отрендерено без фактического рендеринга
* `--help`, `-h` — показать справку

## Входы / Выходы

* **Input:** `.plantuml` файлы в указанной директории (рекурсивно)
* **Output:** изображения (`.png` или `.svg`) рядом с исходными файлами

## Примеры

```bash
# Рендеринг конкретного файла
.tools/plantuml-render/plantuml-render --path docs/diagrams/architecture.plantuml

# Рендеринг в SVG формат
.tools/plantuml-render/plantuml-render --format svg --path примеры/

# Проверка перед рендерингом
.tools/plantuml-render/plantuml-render --dry-run --path .
```

## Зависимости

Использует стандартную библиотеку Python 3.6+. Внешние зависимости не требуются.

**Требуется доступ к интернету** для использования Kroki.io API.

## Exit codes

* `0` — успех, все файлы отрендерены
* `1` — ошибка (файл не найден, сетевая ошибка, etc.)
* `2` — warning (dry-run режим или частичный успех)

## Платформы

Протестировано на:
* Windows 10+ (Python 3.8+)
* Linux (Python 3.6+)
* macOS (Python 3.6+)

## Troubleshooting

**Ошибка сети:**
Убедитесь, что есть доступ к `https://kroki.io`. Kroki.io — бесплатный сервис для рендеринга диаграмм.

**Python не найден:**
Установите Python 3.6+ или задайте переменную окружения `PYTHON`:
```bash
export PYTHON=/usr/bin/python3.9
.tools/plantuml-render/plantuml-render
```

**Большие диаграммы:**
Kroki.io имеет лимит на размер диаграмм (~50KB исходного кода). Для очень больших диаграмм рекомендуется локальная установка PlantUML.

## Ссылки

* Назад к разделу: `../README.md`
* Исходник: `.tools/plantuml-render/plantuml_render.py`
* Kroki.io: https://kroki.io
