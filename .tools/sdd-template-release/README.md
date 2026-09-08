# sdd-template-release — сборка релиза SDD Framework

> Версия инструмента: `0.1.0`.

Инструмент собирает и устанавливает переносимый релиз SDD Framework из чистых исходников
репозитория `Druk83/sdd-template.git`. Папки `.agents/` и `tmp/` в корне
репозитория разработки являются только локальными dev-артефактами и исключены
из Git.

## Быстрый старт

Проверить состояние без записи:

```text
python .tools/sdd-template-release/build_release.py
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
python tmp/sdd-template-source-X.Y.Z-<short-commit>/.tools/sdd-template-release/install_framework.py --source-root tmp/sdd-template-source-X.Y.Z-<short-commit> --target-root . --action use --version X.Y.Z --old-action move --write
```

`--old-action` передаётся только после подтверждения пользователя. Единственный
допустимый результат — `.agents/sdd-template-X.Y.Z/` в корне проекта-потребителя.
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
`awaiting_user_confirmation`; агент обязан показать пользователю значение
`cleanup.question` и `next_action.message`, дождаться ответа «да» или «нет» и только затем считать
операцию завершённой. Общий статус после установки —
`installed_pending_cleanup`. После ответа повторно запустить этот же установщик
с `--cleanup-action delete` или `--cleanup-action keep`.

```text
python tmp/sdd-template-source-X.Y.Z-<short-commit>/.tools/sdd-template-release/install_framework.py --source-root tmp/sdd-template-source-X.Y.Z-<short-commit> --target-root . --cleanup-action delete
```

Режим очистки удаляет только указанный клон и вложенный staging.

## Опции

- `--root <path>` — корень копии исходного репозитория; по умолчанию определяется по расположению инструмента.
- `--write` — создать staging и локальную релизную папку. Без флага выполняется только проверка.
- `--resume-stage` — использовать уже созданную staging-папку после прерванной записи.
- `--source-ref <ref>` — записать выбранный commit или tag в метаданные релиза.
- `--target-root <path>` — корень проекта-потребителя, куда устанавливается готовый пакет.
- `--cleanup-action <keep|delete>` — завершить ожидающее подтверждение очистки клона.
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
