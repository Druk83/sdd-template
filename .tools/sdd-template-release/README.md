# sdd-template-release — сборка релиза SDD Framework

> Версия инструмента: `0.2.0`.

Инструмент собирает и устанавливает переносимый релиз SDD Framework из чистых исходников
репозитория `Druk83/sdd-template.git`. Папки `.agents/` и `tmp/` в корне
репозитория разработки являются только локальными dev-артефактами и исключены
из Git.

## Быстрый старт

Проверить состояние без записи:

```text
python .tools/sdd-template-release/build_release.py
```

Проверить перед commit, что текущий кандидат действительно собирается в новый релиз:

```text
python .tools/sdd-template-release/verify_release.py
```

Проверка создаёт пакет во временной директории и проверяет `release-manifest.json`, состав и
SHA-256 всех файлов, копию `release-registry.json` и обязательные файлы поставляемого пакета.
Рабочие `.agents/` и `tmp/` мета-репозитория не изменяются. Успешный результат этой команды
является обязательной локальной проверкой перед commit релиза.

После commit и создания tag проверь опубликованный релиз:

```text
python .tools/sdd-template-release/verify_release.py --published
```

Проверка требует, чтобы все записи со статусом `supported` ссылались на существующие
immutable refs, а текущий commit совпадал с ref текущей версии. Для публикации новой версии
создай tag локально на проверенном commit, выполни проверку, а затем используй atomic push
ветки и tag одной операцией:

```text
git tag sdd-template-X.Y.Z
python .tools/sdd-template-release/verify_release.py --published
git push --atomic origin HEAD:main refs/tags/sdd-template-X.Y.Z
```

Создать локальный пакет для проверки:

```text
python .tools/sdd-template-release/build_release.py --write
```

В проекте-потребителе агент получает только корневые `README.md` и
`release-registry.json` для выбора записи без создания обзорного клона (например,
через raw-файл GitHub), затем
один раз мелко клонирует выбранный `ref` в единственный каталог корневого `tmp/`
и запускает установщик из клонированной
копии. Промежуточная сборка создаётся во вложенном `tmp/` этого клона, поэтому второй каталог
рядом с ним в `tmp/` не появляется. Установщик читает
`release-registry.json`, выбирает запись, запускает сборщик и создаёт пакет
непосредственно в `.agents/sdd-template-X.Y.Z/`. Копирование корня исходного
репозитория в проект-потребитель запрещено.

Команды установки из корня проекта-потребителя:

```text
python tmp/sdd-template-source-X.Y.Z-<short-commit>/.tools/sdd-template-release/install_framework.py --source-root tmp/sdd-template-source-X.Y.Z-<short-commit> --target-root . --action init --write
python tmp/sdd-template-source-X.Y.Z-<short-commit>/.tools/sdd-template-release/install_framework.py --source-root tmp/sdd-template-source-X.Y.Z-<short-commit> --target-root . --action update --old-action move --write
python tmp/sdd-template-source-X.Y.Z-<short-commit>/.tools/sdd-template-release/install_framework.py --source-root tmp/sdd-template-source-X.Y.Z-<short-commit> --target-root . --action update --old-action move --old-confirmation <old-inventory-fingerprint> --write
python tmp/sdd-template-source-X.Y.Z-<short-commit>/.tools/sdd-template-release/install_framework.py --source-root tmp/sdd-template-source-X.Y.Z-<short-commit> --target-root . --action use --version X.Y.Z --old-action move --old-confirmation <old-inventory-fingerprint> --write
```

При наличии старого release первый вызов с `--old-action move|delete` только
формирует inventory и возвращает `status: awaiting_user_confirmation`. Агент обязан
показать пользователю fingerprint, сводку и полный список нестандартных путей.
После отдельного подтверждения повторный вызов передаёт этот fingerprint через
`--old-confirmation`. Старый release удаляется или переносится только после успешной
сборки и проверки нового package. Единственный допустимый результат после выбранного
действия — `.agents/sdd-template-X.Y.Z/` в корне проекта-потребителя.
При первичной установке установщик дополнительно добавляет только отсутствующие
элементы каркаса `.source/`, `.tasks/` и `.issues/`: README, каталоги `done` и
реестр PDD. Корневой `.chatlog/` не создаётся.
Каталог `docs/requirements/` не входит в релиз и не заполняется его содержимым:
существующий каталог, включая все файлы и подкаталоги, сохраняется полностью.
Если его нет, создаются только каталог и `.gitkeep`.
В отсутствующий `.gitignore` записываются правила для `.project-structure.json`,
`tmp/`, `.source/`, `.tasks/done/`, `.issues/done/` и
`.agents/sdd-template-*/`. В существующий `.gitignore` эти правила добавляются
только при отсутствии и не заменяют пользовательские строки.
После записи установщик возвращает поле `cleanup` со статусом
`awaiting_user_confirmation`, inventory и fingerprint; агент обязан показать пользователю
`cleanup.question`, `next_action.message`, сводку и полный список нестандартных путей.
Общий статус после установки — `installed_pending_cleanup`. После ответа «нет» повторно
запустить установщик с `--cleanup-action keep`. Для удаления повторно запустить его с
`--cleanup-action delete --cleanup-fingerprint <cleanup-inventory-fingerprint>`.

```text
python tmp/sdd-template-source-X.Y.Z-<short-commit>/.tools/sdd-template-release/install_framework.py --source-root tmp/sdd-template-source-X.Y.Z-<short-commit> --target-root . --cleanup-action delete --cleanup-fingerprint <cleanup-inventory-fingerprint>
```

Без fingerprint режим удаления только повторно формирует inventory и не удаляет данные.
При несовпадении fingerprint удаление блокируется. Режим очистки удаляет только
указанный клон и вложенный staging; корневой `tmp/` и соседние каталоги не затрагиваются.

Перед записью установщик проверяет существующие `AGENTS.md` и
`.project-structure.json`. Полный старый `AGENTS.md` Framework без маркеров,
изменённый managed-раздел, повреждённые маркеры и структура мета-репозитория в
корне проекта считаются коллизиями. В этом случае установщик возвращает
`status: awaiting_user_confirmation`, подробные `agents.differences` или
`project_structure.differences` и не записывает спорный файл. После решения
пользователя передайте одно из подтверждённых действий:

```text
--agents-action migrate
--agents-action replace-legacy
--agents-action replace-managed
--agents-action keep
--project-structure-action migrate
--project-structure-action replace
--project-structure-action keep
```

`migrate` изменяет только доказанные Framework-owned ссылки и возвращает
машиночитаемый diff. Неоднозначные ссылки требуют отдельного подтверждения и не
перезаписываются автоматически. После записи запускается post-install validator:
он классифицирует ссылки как `valid`, `stale`, `missing` или `external` и не даёт
завершить установку успешным статусом при нерешённых локальных Framework-ссылках.

Добавление нового managed-раздела поверх старых полных инструкций Framework
без подтверждения запрещено. При отсутствии корневого `.project-structure.json`
создаётся структура проекта-потребителя с путями через
`.agents/sdd-template-X.Y.Z`, а не копия структуры мета-репозитория.

## Опции

- `--root <path>` — корень копии исходного репозитория; по умолчанию определяется по расположению инструмента.
- `--write` — создать staging и локальную релизную папку. Без флага выполняется только проверка.
- `--resume-stage` — использовать уже созданную staging-папку после прерванной записи.
- `--source-ref <ref>` — записать выбранный commit или tag в метаданные релиза.
- `--target-root <path>` — корень проекта-потребителя, куда устанавливается готовый пакет.
- `--cleanup-action <keep|delete>` — завершить ожидающее подтверждение очистки клона.
- `--cleanup-fingerprint <sha256>` — fingerprint inventory, подтверждённый пользователем
  для удаления source clone.
- `--old-confirmation <sha256>` — fingerprint inventory старого release, подтверждённый
  пользователем для `--old-action move|delete`.
- `--agents-action <ask|keep|migrate|replace-legacy|replace-managed>` — разрешить
  расхождения `AGENTS.md` после подтверждения пользователя.
- `--project-structure-action <ask|keep|migrate|replace>` — разрешить расхождения
  корневого `.project-structure.json`.
- `--help` — вывести справку.

## Входы и выходы

- Input: корневой `README.md`, `.manifest/`, `.requirements/`, `.approach/` и разрешённые `.tools/`.
- Output: `.agents/sdd-template-X.Y.Z/`; промежуточная сборка находится в
  `tmp/sdd-template-source-X.Y.Z-<short-commit>/tmp/` и удаляется вместе с клоном.
- Stdout: JSON-отчёт о версии, составе, сохранённых каталогах и результате.
- Stderr: ошибки проверки и обязательное уведомление о подтверждении очистки.

## Ограничения

- Версия берётся из корневого README чистой копии.
- Существующий релиз не перезаписывается.
- Старый релиз не удаляется без подтверждённого действия пользователя.
- `AGENTS.md`, `.tasks/`, `.issues/`, `.source/`, тесты сборщика, локальные данные и `.git/` не экспортируются.
- Инструмент изменяет только результат в `.agents/` и отсутствующие элементы
  корневого каркаса; `AGENTS.md` создаётся или дополняется управляемым разделом
  с полными инструкциями Framework, пользовательский текст вне него сохраняется.
- При обновлении одна корректная пара маркеров `AGENTS.md` заменяется актуальным
  управляемым разделом; пользовательский текст вне него не изменяется.
- При конфликте `AGENTS.md` установщик возвращает список `agents.conflicts` и не
  перезаписывает спорное содержимое.
- Инструмент не удаляет весь `tmp/` и не публикует локальные `.agents/` и `tmp/` из dev-репозитория.
- Предварительный каталог `.sdd-template-review/` не создаётся. Имя единственного
  клона содержит первые 8 символов его фактического commit.
- После ошибки записи валидный staging той же версии, ref и commit используется
  повторно; staging из другого источника не перезаписывается.
- Для релиза по tag поле `commit` в реестре может быть `null`; фактический commit
  проверяется после клонирования и записывается в `release-manifest.json`.

## Ссылки

- Стандарт экспорта: `../../.manifest/exportmanifest.md`.
- Корневой README: `../../README.md`.
- Реестр инструментов: `../registry.json`.
## Контроль пользовательских данных при обновлении

При обнаружении старого release первый ответ установщика содержит два независимых
  inventory: старого каталога `.agents/sdd-template-X.Y.Z` и временного
  `tmp/sdd-template-source-X.Y.Z-<short-commit>`. Для каждого набора данных
  используется собственный fingerprint и отдельное подтверждение. Наличие любого
  нестандартного файла или каталога устанавливает `safe_to_delete: false`; удаление
  возможно только после явного подтверждения именно этого fingerprint.
