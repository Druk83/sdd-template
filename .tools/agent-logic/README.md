# agent-logic — переносимый компилятор ASIR
> Версия инструмента: `0.4.1`.

Локальный инструмент преобразует UTF-8 plain text и Markdown в проверяемую модель ASIR, сохраняет provenance и формирует контекст для ИИ-агента. Папка самодостаточна и не требует установки пакетов.

## Обязательная инструкция для ИИ-агента

Когда пользователь указывает путь к готовому каталогу этого экспорта, агент обязан скопировать пакет в `.tools/agent-logic` без пересоздания файлов. Нельзя генерировать аналог, переписывать код, wrappers, README или манифест. До работы с инструментом прочитайте [инструкции пакета](agent-logic.instructions.md), затем проверьте `manifest.json` и используйте точку входа из `registry-entry.json`.
## Быстрый старт

Из корня проекта-потребителя:

```bash
python .tools/agent-logic/agent-logic.py compile .source --format context
python .tools/agent-logic/agent-logic.py agent .tools/agent-logic/.runtime/agent-context.json --format text
```

Для Windows доступен `agent-logic.bat`, для Unix-подобных систем — `agent-logic`.

## Опции

* `compile [path]` — скомпилировать файл или каталог (по умолчанию `.source`).
* `compile --format json|md|text|context` — выбрать формат результата.
* `compile --output <path> --write` — явно записать новый файл; существующие файлы не перезаписываются.
* `compile --request <text>` — сохранить исходный запрос пользователя в отчёте.
* `compile --requested-at <ISO-8601>` — сохранить время регистрации запроса в отчёте.
* `agent <context>` — прочитать `agent_context` и сформировать локальный план.
* Для чтения контекста из pipe вместо имени файла укажите -.
* `agent --limit <n>` — ограничить число действий в плане; `0` означает все действия.
* `--help` — вывести справку.
* Флаг --replace разрешает замену существующего файла только вместе с --write.

## Входы / Выходы

* Input: UTF-8 plain text, Markdown и JSON `agent_context`.
* Output: JSON, Markdown, plain text или context в stdout; диагностика — в stderr.
* `agent` возвращает код `0`, если выполнение разрешено, и `2`, если требуется review.

## Примеры

```bash
python .tools/agent-logic/agent-logic.py compile .source --format context --output .tools/agent-logic/.runtime/agent-context.json --write
python .tools/agent-logic/agent-logic.py agent .tools/agent-logic/.runtime/agent-context.json --format json --limit 20
```

При `execution_policy.allowed=false` план не формируется, внешние действия не выполняются, а агенту возвращаются блокирующие элементы.
## Отчёт по запросу агента

При просьбе пользователя проверить или проанализировать документ агент действует по `agent-logic.instructions.md`: передаёт исходный запрос и время регистрации, а Markdown-отчёт записывает только в `.tools/agent-logic/.runtime/exports/<compilationId>/`.

```text
python .tools/agent-logic/agent-logic.py compile .manifest/dependenciesmanifest.md --format md --request "Проверить логическую целостность манифеста" --requested-at "2026-08-09T18:45:00+05:00" --output .tools/agent-logic/.runtime/exports/<compilationId>/dependenciesmanifest.agent-logic.md --write
```

Отчёт содержит `user_guidance`: при `NO_ACTION_REQUIRED` действия по результату проверки не требуются; при `REVIEW_REQUIRED` показаны только подтверждённые ручные действия; при `HUMAN_DECISION_REQUIRED` показан вопрос человеку. Неблокирующие `observations` являются только контекстом и не могут быть выданы за дефект или рекомендацию правки. Исходный документ и `.tasks/` не изменяются.

## Политика хранения результатов

* Одноразовый запуск без файлов:

```bash
python .tools/agent-logic/agent-logic.py compile .source --format context | python .tools/agent-logic/agent-logic.py agent - --format text
```

* Рабочий контекст хранится только при явном `--write` в `.tools/agent-logic/.runtime/agent-context.json`.
* Для обновления рабочего контекста используйте `--write --replace`; без `--replace` существующий файл защищён.
* Аудитные результаты сохраняйте в `.tools/agent-logic/.runtime/exports/<compilationId>/`, если их нужно передать или хранить.
* В `text` и `md` сначала приведён профиль артефакта и применённые проверки, затем отдельно показаны проблемы, предупреждения, справочные блоки и элементы для решения.
* В конце такого отчёта приведена готовая команда сохранения Markdown. Она не выполняется сама, не содержит `--replace` и записывает только путь, заданный через `--output --write`. При существующем пути выберите другое имя или осознанно добавьте `--replace`.
* `.runtime/` временный и игнорируемый каталог; удаляйте его после завершения задачи, если трассировка больше не нужна.
## Зависимости

Python 3.12+ и стандартная библиотека. Сеть и сторонние пакеты не требуются.

## Ссылки

* Реестр инструмента: `registry-entry.json`
* Контрольные суммы: `manifest.json`

## Профили формализации

Команда `prove` принимает только явно подготовленные элементы `formal_model`. Каждый факт и правило содержит объект `formalization` с `profile_id`, `profile_version`, `approval_basis` и при `human_approved` полем `approved_by`. Поддержаны профили `normative_markdown`, `business_rules` и `technical_requirements` при совпадении с видом источника и артефакта.

`source_code` и `empirical_evidence` не могут быть дедуктивными основаниями. Python-файлы анализируются только AST-анализатором для построения структурного контекста; комментарии и код не становятся правилами. Таблица или наблюдение без явной схемы и утверждённой формализации не становятся фактами.
## Внешние решатели и эмпирические данные

```bash
python .tools/agent-logic/agent-logic.py solver list --format json
```

Команда только перечисляет отключённые локальные адаптеры и не запускает сеть или внешний процесс. В текущей поставке доступен лишь `fake-local` (`enabled=false`, `network=false`). Контракт будущего solver ограничивает запрос контрольной суммой формальной модели, целью DSL и лимитами; URL, пути и shell-команды не принимаются. Положительный результат требует проверяемый trace с provenance. `evidence_record` хранит наблюдение отдельно от дедуктивных premises; эмпирическая гипотеза требует отдельного утверждения метода и статистической модели.