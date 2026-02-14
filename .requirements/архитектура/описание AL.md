# Application Layer (AL) — ArchiMate 3.2 (H6)

> **Важно:** этот файл в `.requirements/**` — **шаблон** (read-only).
> Заполненная версия хранится в: `docs/requirements/архитектура/описание AL.md`.
> **Подход:** `.approach/archimate.md` (концептуальная методология ArchiMate).

**Примечание по ссылкам:** в настоящем проекте пока используем явные пути к документам (например `docs/requirements/структура ПО/стек проекта.md`).

---

## ЗАВИСИМОСТИ

**Перед заполнением этого документа обязательно проверь наличие:**

```
1. docs/requirements/архитектура/сущности.md      <- ID сущностей (AC-*, AI-*, AS-*, DO-*)
2. docs/requirements/архитектура/описание BL.md   <- ID процессов (BP-*)
```

В сценариях AL ссылки указываются по типизированным ID:
- На Application Components: `AC-001: API Gateway`, `AC-002: User Service`
- На Application Interfaces: `AI-001: REST API`, `AI-002: gRPC API`
- На бизнес-процессы из BL: `BP-001, BP-002`
- На Data Objects: `DO-001: UserDTO`, `DO-002: OrderEvent`

**Если зависимости не созданы** — сначала выполни шаблоны:
- `.requirements/архитектура/сущности архитекутры.md`
- `.requirements/архитектура/описание BL.md`

---

## Подсказка: сущности ArchiMate 3.2

**Прикладной слой:** Application Component, Application Collaboration, Application Interface, Application Function, Application Interaction, Application Process, Application Event, Application Service, Data Object.

**Связи:** Composition, Aggregation, Assignment, Realization, Specialization, Serving, Access, Influence, Association, Triggering, Flow.

---

# ЧАСТЬ 1: ОПИСАТЕЛЬНАЯ (правила, источники, запреты)

---

## 1.1 Назначение документа

Application Layer описывает **КАК** система реализует бизнес-процессы:
- Какие сервисы/компоненты участвуют
- Как они взаимодействуют (протоколы, очереди, API)
- Какие паттерны применяются (caching, retry, circuit breaker)
- Какие технические SLA обеспечиваются

**Application Layer НЕ описывает:**
- Зачем это нужно бизнесу (Business Layer)
- На каком железе/инфраструктуре работает (Technology Layer)
- Конфигурации серверов, сети, storage

---

## 1.2 Стандарт: ArchiMate 3.2 — Application Layer (рекомендуемый)

> Если проект не использует ArchiMate — допускается альтернативная нотация (C4/UML/ADR и т.п.), при этом **обязательны** инварианты: слои, трассировка, реестр сущностей, связи и источники фактов.

### Сущности Application Layer (полный перечень)

#### Active Structure Elements (кто выполняет)

| Элемент | ArchiMate | Описание | Когда использовать |
|---------|-----------|----------|-------------------|
| **Application Component** | `Application_Component` | Модульная единица ПО | Сервис, модуль, библиотека |
| **Application Collaboration** | `Application_Collaboration` | Группа компонентов, работающих совместно | Оркестрация, saga, workflow |
| **Application Interface** | `Application_Interface` | Точка доступа к сервису | API, CLI, UI |

#### Behavior Elements (что происходит)

| Элемент | ArchiMate | Описание | Когда использовать |
|---------|-----------|----------|-------------------|
| **Application Function** | `Application_Function` | Внутренняя функция компонента | Обработка данных, валидация |
| **Application Interaction** | `Application_Interaction` | Совместное поведение компонентов | Распределённая транзакция |
| **Application Process** | `Application_Process` | Последовательность действий | ETL, pipeline, workflow |
| **Application Event** | `Application_Event` | Событие в приложении | Message, callback |
| **Application Service** | `Application_Service` | Публичная capability компонента | API endpoint, consumer |

#### Passive Structure Elements (с чем работают)

| Элемент | ArchiMate | Описание | Когда использовать |
|---------|-----------|----------|-------------------|
| **Data Object** | `Data_Object` | Структура данных | DTO, Entity, Message, Record |

---

## 1.3 Источники для заполнения

| Приоритет | Документ | Путь | Что извлекать |
|-----------|----------|------|---------------|
| **0** | **Каталог сущностей** | **`docs/requirements/архитектура/сущности.md`** | **Object N — номера компонентов** |
| **1** | **Business Layer** | **`docs/requirements/архитектура/описание BL.md`** | **Процесс BL: N — номера процессов** |
| 2 | Стек проекта | `docs/requirements/структура ПО/стек проекта.md` | Технологии, frameworks |
| 3 | Файловая структура | `docs/requirements/структура ПО/файловая структура проекта.md` | Компоненты, модули |
| 4 | Зависимости | `docs/requirements/структура ПО/зависимости.md` | Библиотеки, интеграции |
| 5 | Порты | `docs/requirements/структура ПО/ports.md` | Интерфейсы, протоколы |
| 6 | Требования (NFR) | `docs/requirements/требования/**` | Performance, availability |

---

## 1.4 Алгоритм заполнения

### Шаг 0: Проверить зависимости
- Убедиться, что существует `docs/requirements/архитектура/сущности.md`
- Убедиться, что существует `docs/requirements/архитектура/описание BL.md`
- Запомнить нумерацию Application Components (Object N)
- Запомнить нумерацию Business Processes (Процесс BL: N)

### Шаг 1: Сопоставить BL -> AL
- Для каждого Business Process определить реализующие Application Components
- Связать: `Процесс BL: N` -> какие сервисы участвуют

### Шаг 2: Описать Application Components
- Выписать все Application Components из стека проекта
- Определить их роли и ответственности
- Указать технологии (язык, framework) из `стек проекта.md`

### Шаг 3: Определить взаимодействия
- Описать протоколы (из стека проекта)
- Определить паттерны (sync/async, request-reply, pub-sub)
- Указать Application Events

### Шаг 4: Добавить паттерны надёжности
- Idempotency (дедупликация)
- Circuit Breaker (защита от каскадных сбоев)
- Retry policies (повторные попытки)
- Caching (кэширование)

### Шаг 5: Определить технические SLA
- Latency (p50, p95, p99)
- Availability (per instance, cluster)
- Error rate
- Throughput

### Шаг 6: Оценить готовность
- Проверить покрытие всех BL процессов
- Убедиться в наличии observability (trace_id)
- Проверить resilience patterns

---

## 1.5 Разграничение слоёв: BL / AL / TL

### Что относится к AL (разрешено)

| Категория | Примеры |
|-----------|---------|
| Протоколы взаимодействия | Синхронные API, асинхронные очереди, RPC |
| Системы хранения | Реляционные БД, кэши, брокеры сообщений |
| Механизмы аутентификации | Токены, сессии, OAuth flows |
| Контейнеризация | Образы, контейнеры (без инфраструктурных деталей) |
| Таймауты и retry | Конфигурация на уровне приложения |

### Что НЕ относится к AL (запрещено)

| Уровень | Категория | Примеры |
|---------|-----------|---------|
| **BL** | Бизнес-намерения | "Клиент хочет...", "Бизнес требует..." |
| **TL** | Инфраструктура | IP-адреса, DNS, размеры VM, firewall rules |
| **TL** | Deployment | Количество реплик, node affinity, storage class |
| **TL** | Секреты | Пароли, API keys, certificate paths |
| **TL** | Vendor ops | Cloud console actions, IaC конфигурации |

---

## 1.6 Паттерны надёжности (обязательные для критических путей)

Для каждого критического взаимодействия указать применимые паттерны:

### Idempotency
```
- idempotency_id = <formula>
- dedup_ttl = <N> seconds
- storage: <где хранится>
```

### Circuit Breaker
```
- failure_threshold: <N>
- reset_timeout: <N> seconds
- fallback: <strategy>
```

### Retry Policy
```
- attempts: <N>
- strategy: <exponential/linear>
- backoff: <initial>, <max>
```

### Timeout
```
- per request: <N> ms
- per operation: <N> ms
```

---

## 1.7 Observability (обязательно)

Для каждого сценария указать:

### Trace ID
```
- Как передаётся (header, payload)
- Где логируется (audit_log, traces)
```

### Metrics
```
- Latency (p50, p95, p99)
- Error rate
- Throughput
```

### Alerts
```
- Thresholds
- Severity routing
```

---

## 1.8 Типы сценариев AL

| Тип | Описание |
|-----|----------|
| **Sync Request-Reply** | Синхронный запрос-ответ |
| **Async Message** | Асинхронная передача через очередь/топик |
| **Event-Driven** | Реакция на событие |
| **Scheduled Job** | Периодическая задача |
| **Stream Processing** | Потоковая обработка |
| **Saga/Orchestration** | Распределённая транзакция |

---

## 1.9 Коды решений (AL-*)

При описании сценариев используй коды для ссылок на архитектурные решения:

| Код | Область | Описание |
|-----|---------|----------|
| AL-C1 | Idempotency | Дедупликация |
| AL-C2 | Observability | Trace ID, metrics, logging |
| AL-C3 | Circuit Breaker | Защита от каскадных сбоев |
| AL-C4 | API Gateway | Централизация auth, routing |
| AL-C5 | Persistence | Стратегия хранения |
| AL-P1 | Caching | Стратегия кэширования |
| AL-P2 | Rate Limiting | Ограничение запросов |
| AL-P3 | Async Processing | Очереди, workers |
| AL-P4 | Aggregation | Агрегация данных |
| AL-P5 | Cache Invalidation | Инвалидация кэша |

---

## 1.10 Критерии оценки готовности

| Критерий | Вопрос | Вес |
|----------|--------|-----|
| Покрытие BL | Все Business Processes имеют реализацию в AL? | 20% |
| Компоненты | Все Application Components из стека описаны? | 15% |
| Взаимодействия | Все связи между компонентами определены? | 15% |
| Resilience | Для критических путей есть паттерны надёжности? | 15% |
| Observability | Trace ID propagation описан для всех сценариев? | 10% |
| SLA | Для каждого сценария указаны latency/availability? | 10% |
| Чистота AL | Отсутствуют BL/TL детали? | 10% |
| Коды решений | Архитектурные решения задокументированы? | 5% |

**Порог готовности:** >=80% -> готов к TL

---

## 1.11 Процедура заполнения (подтверждение компонентов AL)

> **ОБЯЗАТЕЛЬНО:** Перед детальным описанием сценариев сформулируй перечень Application Components и получи подтверждение разработчика.

### Почему это важно

Application Layer определяет "КАК" система реализует бизнес-процессы:
- Application Components — это сервисы/модули, которые будут реализованы в коде
- Взаимодействия определяют контракты между компонентами
- Паттерны надежности влияют на архитектуру кода

**Ошибка в определении компонентов AL** требует переделки кода и TL.

### Алгоритм

1. Проанализируй `docs/requirements/архитектура/описание BL.md` (процессы)
2. Проанализируй `docs/requirements/структура ПО/стек проекта.md` (технологии)
3. Сформулируй перечень Application Components для реализации BP
4. Выведи блок "КАНДИДАТЫ КОМПОНЕНТОВ AL — ТРЕБУЕТСЯ ПОДТВЕРЖДЕНИЕ"
5. Дождись подтверждения или корректировки от разработчика
6. После подтверждения — описывает детальные сценарии

### Формат блока подтверждения

> **ВНИМАНИЕ:** Формат ниже — это **структура**, а не готовый пример.
> Заполни placeholder'ы (`<...>`) реальными данными из `docs/requirements/`.

```
КАНДИДАТЫ КОМПОНЕНТОВ AL — ТРЕБУЕТСЯ ПОДТВЕРЖДЕНИЕ

На основе анализа Business Layer и стека проекта выделены компоненты:

1. APPLICATION COMPONENTS (сервисы/модули)
   | ID | Component | Технология | Назначение | Реализует BP |
   |----|-----------|------------|------------|--------------|
   | AC-01 | <name> | <из стека> | <description> | BP-01, BP-02 |

2. APPLICATION INTERFACES (точки доступа)
   | ID | Interface | Тип | Component | Протокол |
   |----|-----------|-----|-----------|----------|
   | AI-01 | <name> | API/CLI/UI | AC-01 | REST/gRPC/etc |

3. APPLICATION EVENTS (события приложения)
   | ID | Event | Publisher | Subscribers | Формат |
   |----|-------|-----------|-------------|--------|
   | AE-01 | <name> | AC-01 | AC-02, AC-03 | JSON/Protobuf |

4. КРИТИЧЕСКИЕ ВЗАИМОДЕЙСТВИЯ
   | От | К | Тип | Паттерны надежности |
   |----|---|-----|---------------------|
   | AC-01 | AC-02 | sync | retry, circuit breaker |

Пожалуйста, подтвердите перечень компонентов или укажите корректировки.
После подтверждения будут описаны детальные сценарии AL.
```

### Правила формирования кандидатов

> Извлекай данные **только** из документации проекта, а не из примеров шаблона.

| Источник | Что извлекать | Куда маппить |
|----------|---------------|--------------|
| `docs/requirements/архитектура/описание BL.md` | Business Processes (BP-*) | Application Component |
| `docs/requirements/структура ПО/стек проекта.md` | Технологии backend | Технология компонента |
| `docs/requirements/сценарии/<domain>/карта процесса.md` | Интеграции между BC | Application Interface |
| `docs/requirements/сценарии/<domain>/каталог мероприятий.md` | Domain Events | Application Event |
| `docs/requirements/требования/**` | NFR требования | Паттерны (retry, CB) |

### Важно

- Формат блока — это **структура для заполнения**, не готовый пример
- **Запрещено** копировать примеры из шаблонов — извлекай только из проекта
- Все имена компонентов и интерфейсов берутся из `docs/requirements/`
- Если BL не готов — создать GAP и дождаться завершения этапа [7 BL]
- **Запрещено** добавлять TL термины (IP, DNS, replicas, firewall) на этом этапе

---

# ЧАСТЬ 2: ОБЯЗАТЕЛЬНЫЕ РАЗДЕЛЫ ПРИ ОФОРМЛЕНИИ

---

## 2.0 Контекст документа

```markdown
## 0. Контекст документа

- **Проект / продукт:** `<PROJECT_NAME>`
- **Версия:** `<X.Y>`
- **Дата:** `<YYYY-MM-DD>`
- **Стандарт:** ArchiMate 3.2 — Application Layer
- **Владелец:** `<team/person>`

### Зависимости (статус)

| Документ | Путь | Статус |
|----------|------|--------|
| Каталог сущностей | `docs/requirements/архитектура/сущности.md` | `<read/not found>` |
| Business Layer | `docs/requirements/архитектура/описание BL.md` | `<read/not found>` |
| Стек проекта | `docs/requirements/структура ПО/стек проекта.md` | `<read/not found>` |
```

---

## 2.1 Application Components

```markdown
## 1. Application Components

| ID | Component | Технология | Назначение | Object N |
|----|-----------|------------|------------|----------|
| AC-01 | `<name>` | `<из стека>` | `<description>` | Object N |
| AC-02 | `<name>` | `<...>` | `<...>` | Object N |
```

---

## 2.2 Сценарии AL

```markdown
## 2. Сценарии Application Layer

---

### AL-01. `<Название сценария>`

**Участники:** `<AC-XX (Component)>`, `<технология из стека>`

**Процесс BL:** `<номера из описание BL.md>`

**Описание:** `<Что происходит на прикладном уровне>`

**Конфигурация:**
- `<параметр>`: `<значение>`

**Паттерны надёжности:**

*Idempotency (AL-C1):* (если применимо)
- idempotency_id = `<formula>`
- dedup_ttl = `<N>` seconds

*Circuit Breaker (AL-C3):* (если применимо)
- failure_threshold: `<N>`
- reset_timeout: `<N>` seconds
- fallback: `<strategy>`

*Retry Policy:* (если применимо)
- attempts: `<N>`
- strategy: `<type>`

**Observability (AL-C2):**
- Trace ID: `<как передаётся>`
- Audit: `<что логируется>`

**SLA:**
- Latency: `<p95>`
- Availability: `<N>%`
- Error rate: `<N>%`

**Связи:** `<ArchiMate relation>` (`<source>` -> `<target>`)

**Ценность:** `<Техническая ценность>`

**Статус:** `<Утверждён / Опционален>`

---
```

---

## 2.3 Критические решения

```markdown
## 3. Критические решения (AL-*)

| Код | Область | Действие | Применено в сценариях |
|-----|---------|----------|----------------------|
| AL-C1 | Idempotency | `<описание>` | AL-01, AL-02 |
| AL-C2 | Observability | `<описание>` | AL-01, AL-02, AL-03 |
| AL-C3 | Circuit Breaker | `<описание>` | AL-02, AL-03 |
```

---

## 2.4 SLA по сервисам

```markdown
## 4. SLA по сервисам

| Service | Availability | Latency p95 | Error Rate | Scope |
|---------|--------------|-------------|------------|-------|
| `<name>` | `<N>%` | `<N>` ms | `<N>%` | `<per instance/cluster>` |
```

---

## 2.5 Итоговая таблица

```markdown
## 5. Итоговая таблица сценариев

| ID | Сценарий | Компоненты | Процесс BL | Решения | Статус |
|----|----------|------------|------------|---------|--------|
| AL-01 | `<name>` | AC-01, AC-02 | N, M | AL-CX | `<status>` |
```

---

## 2.6 Итоговая оценка

```markdown
## 6. Итоговая оценка

| Критерий | Оценка | Комментарий |
|----------|--------|-------------|
| Покрытие BL | `/10` | |
| Компоненты | `/10` | |
| Resilience | `/10` | |
| Observability | `/10` | |
| SLA | `/10` | |
| Чистота AL | `/10` | |
| **OVERALL** | **X.X/10** | |

**Готовность:**
- [ ] >=8.0 — **READY FOR TL PHASE**
- [ ] 6.0-7.9 — Требуется доработка
- [ ] <6.0 — Существенная переработка
```

---

---

## Примеры (H7)

**Считать верным:**
- AL сценарии ссылаются на BP-* из BL и на компоненты AC-*.
- Протоколы и паттерны описаны без TL деталей (IP, DNS, replicas).

**Считать неверным:**
- Присутствуют инфраструктурные параметры (размеры VM, сети, firewall).

---

## Критерии готовности

- [ ] Все BL процессы имеют реализацию в AL.
- [ ] Компоненты и интерфейсы описаны по ID.
- [ ] Указаны паттерны надёжности и observability для критических путей.

---

**Последнее обновление:** `<YYYY-MM-DD>`
