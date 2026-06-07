# check-encoding

Проверка файлов на артефакты поврежденной кодировки (mojibake) и невалидный UTF-8.

По умолчанию сканирует:
- `docs/`
- `README.md` в корне репозитория
- `apps/`
- `services/`
- `scripts/`
- `.manifest/`
- `.requirements/`
- `.tasks/`
- `.issues/`

## Быстрый старт

Python:

```bash
python .tools/check-encoding/check_encoding.py
```

Windows wrapper:

```bat
.tools\check-encoding\check-encoding.bat
```

PowerShell wrapper:

```powershell
powershell -ExecutionPolicy Bypass -File .tools/check-encoding/check-encoding.ps1
```

Unix wrapper:

```bash
.tools/check-encoding/check-encoding
```

## Параметры

- `--paths <list>` - список файлов/директорий для проверки (по умолчанию: `docs README.md apps services scripts .manifest .requirements .tasks .issues`)
- `--max-file-size-kb <int>` - пропуск файлов больше заданного размера
- `--format <text|json>` - формат вывода
- `--strict` - более чувствительные эвристики, может давать больше ложных срабатываний

## Примеры

```bash
python .tools/check-encoding/check_encoding.py --paths docs README.md --format text
python .tools/check-encoding/check_encoding.py --paths docs/requirements README.md --format json
python .tools/check-encoding/check_encoding.py --strict
```

## Что проверяется

- невалидный UTF-8 в текстовых файлах;
- символ замены `\ufffd`;
- повторяющиеся символы замены;
- типичные Latin mojibake-паттерны;
- типичные Cyrillic mojibake-паттерны;
- дополнительные сигнатуры в `--strict` режиме.

## Примечания

- Инструмент пропускает тяжёлые и генерируемые каталоги: `.git`, `node_modules`, `target`, `dist`, `build`, `.venv`, `__pycache__`, `.idea`, `.vscode`, `coverage`.
- JSON-вывод экранируется безопасно для любой кодовой страницы консоли.

## Troubleshooting

- `No files to scan.` - проверьте пути из `--paths`.
- Ложные срабатывания на редких строках - запустите без `--strict`.

## Коды выхода

- `0` - подозрительных строк не найдено
- `1` - найдены подозрительные строки или ошибки чтения
- `2` - предупреждение уровня запуска (например, нет входных файлов для проверки)
