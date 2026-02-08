# Раздел .approach

В каталоге `.approach/` хранятся описания методологических подходов, используемых при создании технической документации.

## Структура

```text
.approach/
  README.md
  registry.json          # реестр подходов
  event-storming.md      # методология
  context-map.md         # методология
  ddd-patterns.md        # методология
  cqrs.md                # паттерн потоков данных
  event-sourcing.md      # паттерн потоков данных
  pub-sub.md             # паттерн потоков данных
  archimate.md           # нотация для [7]
```

## Методологии моделирования

Выбор методологии осуществляется на этапе [2] (обоснование выбора).

* **event-storming** — моделирование бизнес-процессов через события и команды -> см. `.approach/event-storming.md`
* **context-map** — визуализация связей между ограниченными контекстами -> см. `.approach/context-map.md`
* **ddd-patterns** — паттерны Domain-Driven Design -> см. `.approach/ddd-patterns.md`

## Паттерны потоков данных

Выбор паттерна осуществляется на этапе [2] (раздел 3.5.3 обоснования выбора).

* **cqrs** — разделение read/write -> см. `.approach/cqrs.md`
* **event-sourcing** — аудит всех изменений, восстановление состояния -> см. `.approach/event-sourcing.md`
* **pub-sub** — слабая связность между модулями -> см. `.approach/pub-sub.md`

## Нотация

* **archimate** — описание архитектуры в слоях BL/AL/TL (используется всегда на этапе [7]) -> см. `.approach/archimate.md`

## Архитектурные паттерны

Архитектурные паттерны (Layered, Hexagonal, Clean Architecture, etc.) не хранятся в `.approach/`.

**Источник:** https://github.com/Druk83/arch-patterns

Агент ОБЯЗАН изучить каталог `arch-patterns` и выбрать оптимальный паттерн на этапе [2].
Выбранный паттерн фиксируется в разделе "Итог выбора" (3.5.6) документа `обоснование выбора.md`.

## Примечания об операционных файлах

* `registry.json` — машинно-читаемый реестр подходов (id, этапы SDD, артефакты, ссылка на файл).

## Ссылки

* В корень проекта: `/README.md`
* SDD процесс: `.manifest/sddmanifest.md`
* Трек разработки: `.requirements/трек разработки.md`
* Правила оформления README: `.manifest/readmemanifest.md`
