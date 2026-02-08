# Несоответствие .approach/ структуре раздела 3.5 обоснования выбора

**Type:** `type:doc`
**Priority:** `priority:P2`
**Severity:** `severity:S2`
**Status:** `status:done`

## Контекст
- Компонент: `.approach/` и `.requirements/обоснование выбора.md` раздел 3.5
- Impact: агент может использовать устаревшие или несуществующие подходы

## Описание проблемы
После реструктуризации раздела 3.5 "Методология моделирования и паттерны" обнаружены несоответствия между:
- Новой структурой 3.5 (3.5.1-3.5.6)
- Существующими файлами в `.approach/`
- Записями в `registry.json`

---

## Перечень расхождений

### GAP-A1: Отсутствует cqrs.md
**Priority:** P2 | **Severity:** S2

**В разделе 3.5.3:**
```
| CQRS | да/нет | [6], [7] | Нагрузка > 10K RPS или явное разделение read/write |
```

**В .approach/:** файл отсутствует

**В diagram legend:**
```
| Методологии: DDD, Event Storming, |
| Context Map, CQRS, Event Sourcing |
```

**Решение:** создать `.approach/cqrs.md` с процедурой применения CQRS

---

### GAP-A2: Отсутствует event-sourcing.md
**Priority:** P2 | **Severity:** S2

**В разделе 3.5.3:**
```
| Event Sourcing | да/нет | [6] | Аудит всех изменений, восстановление состояния |
```

**В .approach/:** файл отсутствует

**Решение:** создать `.approach/event-sourcing.md` с процедурой применения Event Sourcing

---

### GAP-A3: ddd-patterns.md - несоответствие этапов
**Priority:** P3 | **Severity:** S3

**В файле ddd-patterns.md:**
```
DDD Patterns используются на этапах [4], [5], [6]
```

**В разделе 3.5.2:**
```
| DDD (Domain-Driven Design) | да/нет | ddd-patterns.md | [4], [5.3] |
```

**Расхождение:** файл указывает этапы [4], [5], [6], а 3.5.2 указывает [4], [5.3]

**Решение:** уточнить корректные этапы и обновить либо файл, либо таблицу

---

### GAP-A4: registry.json - stages не соответствуют 3.5
**Priority:** P3 | **Severity:** S3

**В registry.json:**
```json
{
  "id": "ddd-patterns",
  "stages": ["4", "5", "6"],
  ...
}
```

**В разделе 3.5.2:** этапы [4], [5.3]

**Решение:** после уточнения GAP-A3 обновить stages в registry.json

---

### GAP-A5: registry.json - нет записей для CQRS и Event Sourcing
**Priority:** P2 | **Severity:** S2

**После создания cqrs.md и event-sourcing.md** необходимо добавить записи в registry.json.

**Решение:** добавить записи после создания файлов (GAP-A1, GAP-A2)

---

## План исправления

### Этап 1: Создание недостающих approaches
- [x] GAP-A1: Создать `.approach/cqrs.md`
- [x] GAP-A2: Создать `.approach/event-sourcing.md`

### Этап 2: Согласование этапов
- [x] GAP-A3: Уточнить этапы для ddd-patterns.md (согласовать с разработчиком)

### Этап 3: Обновление registry.json
- [x] GAP-A4: Обновить stages для ddd-patterns
- [x] GAP-A5: Добавить записи для cqrs и event-sourcing

### Этап 4: Обновление README.md
- [x] Обновить `.approach/README.md` со списком всех подходов

---

## Связи
- Целевой раздел: `.requirements/обоснование выбора.md` раздел 3.5
- Целевая папка: `.approach/`
- Диаграмма: `.requirements/последовательность событий.plantuml` (legend)
- Манифест: `.manifest/issuesmanifest.md`

---

## Closing note
- Созданы подходы: `.approach/cqrs.md`, `.approach/event-sourcing.md`, `.approach/pub-sub.md`
- Обновлены: `.approach/README.md`, `.approach/registry.json`, `.approach/ddd-patterns.md`
