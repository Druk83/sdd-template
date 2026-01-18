# pdd — сканер @todo

Простая утилита для поиска меток `@todo` в исходниках и генерации реестра задач (MD или JSON).

## Быстрый старт

```bash
# Запустить сканер из корня репозитория и записать реестр в .tasks/pdd/@todoregistry.md
.tools/pdd/pdd-scan --format md

# Записать в JSON-файл
.tools/pdd/pdd-scan --format json --output .tasks/pdd/todos.json
```

## Опции

* `--root`, `-r` — корень для сканирования (default: `.`)
* `--format` — формат вывода: `table`, `json`, `md` (default: `md`)
* `--output`, `-o` — путь для записи (по умолчанию: `.tasks/pdd/@todoregistry.md` при `md` формате)

(Опции подтверждены исходным кодом: `.tools/pdd/pdd_scan.py`)

## Конфигурация / ENV

* `PYTHON` — (wrapper) путь к интерпретатору Python, по умолчанию `python3` (опционально, используется в `pdd-scan` wrapper).

## Входы / Выходы

* Input: исходные файлы в репозитории (сканирует все файлы, за исключением скрытых)
* Output: реестр задач. По умолчанию `.tasks/pdd/@todoregistry.md`, либо файл, заданный `--output`; при `--format json` — JSON

## Примеры

```bash
# Сканировать конкретную папку
.tools/pdd/pdd-scan --root src/ --format md

# Вывести JSON в stdout
.tools/pdd/pdd-scan --format json
```

## Troubleshooting

* Для вычисления возраста задач используется `git blame`; если репозиторий не в git или git отсутствует, поля `created_at` / `age_days` будут `null`.
* Если задач не найдено, утилита выводит `No @todo found.`

## Ссылки

* Назад к разделу: `../README.md`
* Исходник: `.tools/pdd/pdd_scan.py`
