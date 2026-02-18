# pdd — сканер @todo

Простая утилита для поиска меток `@todo` в исходниках и генерации реестра задач (MD или JSON).

## Быстрый старт

```bash
# Запустить сканер и записать реестр в .tasks/pdd/@todoregistry.md
.tools/pdd/pdd-scan --format md --write

# Вывести MD в stdout (без записи файла)
.tools/pdd/pdd-scan --format md

# Записать в JSON-файл
.tools/pdd/pdd-scan --format json --write --output .tasks/pdd/todos.json
```

## Опции

* `--root`, `-r` — корень для сканирования (default: `.`)
* `--format` — формат вывода: `table`, `json`, `md` (default: `md`)
* `--write`, `-w` — записать вывод в файл; без флага результат идёт в stdout
* `--output`, `-o` — путь для записи (default при `--write --format md`: `.tasks/pdd/@todoregistry.md`; требует `--write`)

(Опции подтверждены исходным кодом: `.tools/pdd/pdd_scan.py`)

## Конфигурация / ENV

* `PYTHON` — путь к интерпретатору Python (опционально). Unix-wrapper (`pdd-scan`) использует `python3` по умолчанию; Windows-wrapper (`pdd-scan.bat`) использует `python` по умолчанию.

## Входы / Выходы

* Input: исходные файлы в репозитории (сканирует все файлы, за исключением скрытых)
* Output: реестр задач. По умолчанию `.tasks/pdd/@todoregistry.md`, либо файл, заданный `--output`; при `--format json` — JSON

## Примеры

```bash
# Сканировать конкретную папку и записать реестр
.tools/pdd/pdd-scan --root src/ --format md --write

# Вывести JSON в stdout
.tools/pdd/pdd-scan --format json

# Записать JSON в файл
.tools/pdd/pdd-scan --format json --write --output .tasks/pdd/todos.json
```

## Колонка refs_exist

Поле `refs_exist` в выходной таблице принимает три значения:

| Значение | Смысл |
|----------|-------|
| `yes` | поле `refs:` указано и все файлы найдены |
| `no` | поле `refs:` указано, но файл(ы) не найдены |
| `n/a` | поле `refs:` не указано (нарушение `pdd.H4.2`) |

## Troubleshooting

* Для вычисления возраста задач используется `git blame`; если репозиторий не в git или git отсутствует, поля `created_at` / `age_days` будут `null`.
* Сообщение `No @todo found.` выводится только при `--format table`. При форматах `md` и `json` создаётся пустой файл/вывод без сообщения.

## Ссылки

* Назад к разделу: `../README.md`
* Исходник: `.tools/pdd/pdd_scan.py`
