# Diagrams Manifest (H2)

Правила создания, именования и хранения диаграмм в документации.

**Инструмент рендеринга:** `.tools/plantuml-render/` (см. README инструмента)

---

## diagrams.H3.1 Храни код диаграммы отдельно от документа
Код диаграммы сохраняется в отдельный файл, не inline в markdown.
**Почему важно:**
Отдельные файлы позволяют версионировать, рендерить и переиспользовать диаграммы.

---

## diagrams.H4.1 Размещай диаграммы в папках diagrams/

```
docs/requirements/
  diagrams/                           # общие диаграммы
    domain-overview.plantuml
    domain-overview.png
  сценарии/
    <domain>/
      diagrams/                       # диаграммы домена
        UC-01-sequence.plantuml
        UC-01-sequence.png
  архитектура/
    diagrams/                         # архитектурные диаграммы
      BL.plantuml
      AL.plantuml
      TL.plantuml
```

---

## diagrams.H3.2 Используй единые конвенции именования
Имена файлов диаграмм следуют строгому формату по типу.
**Почему важно:**
Единообразие упрощает навигацию и автоматизацию.

---

## diagrams.H4.2 Называй файлы по типу диаграммы

| Тип диаграммы | Формат имени | Пример |
|---------------|--------------|--------|
| Обзор домена | `<domain>-overview.plantuml` | `domain-overview.plantuml` |
| Sequence (UC) | `UC-<NN>-sequence.plantuml` | `UC-01-sequence.plantuml` |
| Activity (UC) | `UC-<NN>-activity.plantuml` | `UC-01-activity.plantuml` |
| Context Map | `context-map.plantuml` | `context-map.plantuml` |
| ArchiMate слой | `<layer>.plantuml` | `BL.plantuml`, `AL.plantuml` |
| ERD | `erd-<domain>.plantuml` | `erd-users.plantuml` |

---

## diagrams.H3.3 Рендерь диаграммы через инструмент проекта
Используй `.tools/plantuml-render/` для рендеринга.
**Почему важно:**
Единый инструмент обеспечивает консистентность и не требует локальных зависимостей.

---

## diagrams.H4.3 Запускай рендеринг командой

```bash
# Все диаграммы в docs/requirements/
.tools/plantuml-render/plantuml-render --path docs/requirements/

# Конкретная директория
.tools/plantuml-render/plantuml-render --path docs/requirements/архитектура/diagrams/

# Проверка без рендеринга
.tools/plantuml-render/plantuml-render --dry-run --path docs/requirements/
```

**Полная документация:** `.tools/plantuml-render/README.md`

---

## diagrams.H3.4 Вставляй ссылку на диаграмму в документ
После рендеринга добавь изображение в markdown с комментарием на исходник.
**Почему важно:**
Документ без ссылки на изображение не покажет диаграмму.

---

## diagrams.H4.4 Вставляй изображение по шаблону

```markdown
### 12.1 Диаграмма событий

<!-- Исходный код: diagrams/domain-events.plantuml -->
![Диаграмма событий домена](diagrams/domain-events.png)
```

**Правила:**
- Комментарий с путем к исходному коду обязателен
- Alt-текст должен быть описательным
- Путь относительный от текущего документа

---

## diagrams.H3.5 Проверяй синтаксис перед коммитом
Диаграмма с ошибками синтаксиса не отрендерится.
**Почему важно:**
Битые диаграммы ломают документацию.

---

## diagrams.H4.5 Проверь по чеклисту перед коммитом

- [ ] Код сохранен в `*.plantuml` файл в папке `diagrams/`
- [ ] Имя файла соответствует конвенции (diagrams.H4.2)
- [ ] Выполнен рендеринг: `.tools/plantuml-render/plantuml-render --path <dir>`
- [ ] PNG создан рядом с исходником
- [ ] В markdown добавлена ссылка на PNG (diagrams.H4.4)
- [ ] Диаграмма отображается корректно

---

**Запрещено:**
- Inline-диаграммы в markdown (` ```plantuml ... ``` `)
- Диаграммы без исходного кода (только PNG)
- Диаграммы в корне документации (используй папку `diagrams/`)
- Рендеринг через внешние сервисы минуя инструмент проекта
