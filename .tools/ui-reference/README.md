# Инструмент UI reference (UI reference tool)

> Версия инструмента: `0.2.0`.

Инструмент проверяет технические документы пользовательского интерфейса и reference artifacts (эталонные артефакты интерфейса), а также безопасно переносит legacy-наборы макетов. Он работает с указанным каталогом и не ограничен только `.figma`.

Инструмент не создаёт production UI, не выбирает UI-паттерны и не заменяет этап `[5.a]` планирования пользовательского интерфейса. Для обновления Framework основной установщик дополнительно выполняет собственный inventory старого release и временного source clone.

## Быстрый старт

Показать актуальные команды:

```text
python .tools/ui-reference/ui_reference.py --help
```

Проверить набор reference artifacts:

```text
python .tools/ui-reference/ui_reference.py validate --reference-set docs/requirements/пользовательский-интерфейс/references/<reference-set>
```

Проверить полный UI-пакет, включая screen pool, pattern/template refs,
traceability и границы reference artifacts:

```text
python .tools/ui-reference/ui_reference.py validate --package docs/requirements/пользовательский-интерфейс
```

Команды возвращают JSON в stdout. При ошибке проверки инструмент выводит сообщение в stderr и завершается с кодом `1`.

## Команды

### `inventory`

Режим только для чтения. Рекурсивно сканирует указанный каталог и возвращает список файлов, размеры, SHA-256 и fingerprint (отпечаток набора файлов).

```text
python .tools/ui-reference/ui_reference.py inventory --source docs/.figma
```

`--source` может указывать на любой reference-каталог, например `.figma`, `references/<reference-set>` или другой каталог с пользовательскими UI-артефактами.

### `validate`

Проверяет переданные части UI-пакета. Можно передать одну или несколько опций:

- `--pool <path>` — screen pool (пул экранов): JSON с описанием экранов;
- `--manifest <path>` — manifest спецификации пользовательского интерфейса;
- `--reference-set <path>` — набор reference artifacts с `screen-manifest.json`, viewport-каталогами и обязательными файлами.
- `--package <path>` — полный UI-пакет в canonical-каталоге
  `docs/requirements/пользовательский-интерфейс/`.

Пример полной проверки:

```text
python .tools/ui-reference/ui_reference.py validate --pool docs/requirements/пользовательский-интерфейс/пул-экранов.json --manifest docs/requirements/пользовательский-интерфейс/манифест-спецификации-интерфейса.json --reference-set docs/requirements/пользовательский-интерфейс/references/<reference-set>
```

Проверка полного пакета:

```text
python .tools/ui-reference/ui_reference.py validate --package docs/requirements/пользовательский-интерфейс
```

Проверяются структура JSON, обязательные поля, допустимые статусы, связи экранов с
pool, pattern/template IDs, traceability, существование screen artifacts, viewport
и обязательных файлов reference-set. Валидация не оценивает визуальное соответствие
макета и не доказывает готовность production-кода.

### `migrate`

Безопасно переносит файлы из одного reference-каталога в другой. По умолчанию выполняется dry-run (пробный запуск без записи).

```text
python .tools/ui-reference/ui_reference.py migrate --source docs/.figma --target docs/requirements/пользовательский-интерфейс/references/<reference-set> --report tmp/ui-migration-report.json
```

Для фактического копирования добавляется `--write`:

```text
python .tools/ui-reference/ui_reference.py migrate --source docs/.figma --target docs/requirements/пользовательский-интерфейс/references/<reference-set> --write --report tmp/ui-migration-report.json
```

Гарантии миграции:

- исходный каталог не удаляется;
- существующие идентичные файлы пропускаются;
- конфликтующие файлы не перезаписываются;
- новые файлы копируются только с `--write`;
- источник и target должны быть независимыми каталогами.

## Входы и выходы

Входом является путь к каталогу или JSON-документу, переданный соответствующей опцией. Результат каждой команды — JSON в stdout:

- `inventory` — entries, размеры, SHA-256 и fingerprint;
- `validate` — `status: pass` либо ошибка с перечнем нарушений;
- `migrate` — списки `copied`, `skipped_identical`, `conflicts` и признаки выполненного удаления или перезаписи.

Отчёт `--report` записывается только для команды `migrate` и содержит тот же результат, что и stdout.

## Использование при обновлении Framework

`ui-reference` является отдельным переиспользуемым инструментом. Он запускается явно для проверки или миграции конкретного UI-набора.

При обновлении Framework установщик отдельно сравнивает содержимое старого `.agents/sdd-template-X.Y.Z` с release manifest и проверяет временный `tmp/sdd-template-source-X.Y.Z-<short-commit>`. Нестандартные файлы, включая `.figma`, показываются пользователю до удаления. Удаление возможно только после отдельного подтверждения по fingerprint.

## Ограничения и безопасность

Инструмент не сканирует весь проект автоматически и не удаляет произвольные каталоги. Это позволяет отличать явную операцию с выбранным reference-каталогом от обновления Framework и не затрагивать `docs/`, production-код или пользовательские данные без указанного действия.

## Ссылки

- Реестр инструментов: `../registry.json`.
- Правила инструментов: `../../.manifest/toolsmanifest.md`.
- Контракт UI Framework: `../../.manifest/uimanifest.md`.
- Внешний каталог UI-паттернов: `https://github.com/Druk83/ui-patterns.git`.
