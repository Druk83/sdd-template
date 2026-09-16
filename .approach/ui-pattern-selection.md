# Выбор UI-паттернов из внешнего каталога

Версия адаптера: `1.0`

## Назначение

Подход применяется на подэтапе `[5.a]` для выбора UI-паттернов и reusable screen UI
templates из внешнего каталога:

`https://github.com/Druk83/ui-patterns.git`

В результате создаются решения и ссылки на источник, а не копия каталога.

## Процедура

1. Проверить, что UI-контур подтверждён и screen pool содержит обязательные поля.
2. Получить опубликованную revision внешнего каталога и сохранить её в provenance.
3. Определить `screen_type` из утверждённого каталога или зарегистрированного
   project extension.
4. Сопоставить purpose, roles, task, modality, viewport, states и constraints экрана
   с условиями применения и противопоказаниями паттернов.
5. Предложить pattern candidates и reusable screen UI templates с rationale.
6. Исключить варианты, для которых отсутствует обязательный контекст или нарушены
   contraindications.
7. Получить подтверждение выбранных pattern candidates.
8. Связать `pattern -> screen template -> screen specification -> acceptance criteria`.
9. Сохранить rejected candidates с причиной и решением разработчика.

## Контракт входа

Адаптер получает:

```yaml
catalog:
  index: <path-to-catalog-index>
  revision: <git-commit-or-tag>
ui_task:
  roles: []
  scenarios: []
  data_types: []
  actions: []
  constraints: []
  quality_attributes: []
  accessibility_requirements: []
  wireframe:
    path: <path-or-null>
    status: <absent|partial|approved>
  baseline:
    path: <path-or-null>
    revision: <git-commit-or-tag-or-null>
```

Обязательные поля входной UI-задачи нельзя подменять названием устройства,
визуальным сходством или предположением агента. При их отсутствии создаётся
`GAP` с перечнем недостающих данных.

## Детерминированный выбор

Порядок фильтрации и ранжирования:

1. проверить доступность указанной revision каталога и разрешимость provenance;
2. определить `screen_type`, `domain` и `decision_scope`;
3. отфильтровать записи по области решения;
4. проверить `required_conditions` и исключить `contraindications`;
5. проверить `conflicts_with`, `compatible_with` и `supersedes`;
6. сопоставить `requirement_drivers` и ограничения задачи;
7. вернуть все равноценные варианты вместо произвольного выбора;
8. записать выбранный вариант, отклонённые альтернативы и открытые `GAP`.

Порядок записей в каталоге не является рейтингом. Числовое ранжирование
допустимо только при явно заданной шкале.

## Контракт результата

Результат адаптера имеет следующий формат:

```yaml
catalog_id: <stable-catalog-id>
catalog_revision: <git-commit-or-tag>
pattern_name: <selected-pattern-or-null>
pattern_kind: <pattern-type-or-null>
source_url: <source-url-or-local-source>
source_revision: <source-revision>
retrieved_at: <date>
drivers: []
evidence_refs: []
candidates: []
rejected_alternatives: []
decision: <selected-pattern-or-GAP>
approval: <developer-confirmation>
downstream_impact: []
limitations: []
gap: []
```

В `candidates` и `rejected_alternatives` сохраняются стабильные идентификаторы
паттернов и причины решения. Результат передаётся в screen specification и
acceptance criteria, но не заменяет project-specific требования.

## Ограничения

- Нельзя выбирать паттерн по памяти агента, названию устройства или визуальному
  сходству без источника.
- При недоступном внешнем источнике создаётся `gap`, выбор останавливается.
- Внешний каталог не копируется в Framework или проект-потребитель.
- Generic template не подменяет project design system.
- Production code, project API, secrets и product data не являются результатом
  данного подхода.

## Provenance

Каждый UI-пакет фиксирует официальный URL, template set version, exact revision,
contract/schema version, дату генерации, выбранные templates и rejected alternatives.
