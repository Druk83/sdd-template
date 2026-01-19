# Technology Layer (TL) — ArchiMate 3.2

> **Важно:** этот файл в `.requirements/**` — **шаблон** (read-only).
> Заполненная версия хранится в: `docs/requirements/архитектура/описание TL.md`.

**Примечание по ссылкам:** в настоящем проекте пока используем явные пути к документам (например `docs/requirements/структура ПО/стек проекта.md`).

---

## ЗАВИСИМОСТИ

**Перед заполнением этого документа ОБЯЗАТЕЛЬНО должны существовать:**

```
1. docs/requirements/архитектура/сущности.md      <- ID сущностей (TN-*, SW-*, TS-*, AR-*)
2. docs/requirements/архитектура/описание AL.md   <- ID сценариев (AP-*)
```

В сценариях TL ссылки указываются по типизированным ID:
- На Nodes: `TN-001: app-container`, `TN-002: db-server`
- На System Software: `SW-001: PostgreSQL`, `SW-002: Docker`
- На Technology Services: `TS-001: Database Service`, `TS-002: Monitoring`
- На Artifacts: `AR-001: docker-image`, `AR-002: helm-chart`
- На прикладные сценарии из AL: `AP-001, AP-002`

**Если зависимости не созданы** — сначала выполни шаблоны:
- `.requirements/архитектура/сущности архитекутры.md`
- `.requirements/архитектура/описание AL.md`

---

## Подсказка: сущности ArchiMate 3.2

**Технологический слой:** Node, Device, System Software, Technology Collaboration, Technology Interface, Technology Function, Technology Process, Technology Interaction, Technology Event, Technology Service, Artifact, Communication Network, Path.

**Связи:** Composition, Aggregation, Assignment, Realization, Specialization, Serving, Access, Influence, Association, Triggering, Flow.

---

# ЧАСТЬ 1: ОПИСАТЕЛЬНАЯ (правила, источники, запреты)

---

## 1.1 Назначение документа

Technology Layer описывает **НА ЧЁМ** работает система:
- Какая инфраструктура используется (серверы, контейнеры, сети)
- Как компоненты развёрнуты и связаны
- Какие механизмы обеспечивают надёжность (HA, backup, failover)
- Какие меры безопасности применяются (шифрование, firewall, VPN)

**Technology Layer НЕ описывает:**
- Зачем это нужно бизнесу (Business Layer)
- Какую логику выполняют сервисы (Application Layer)
- Бизнес-правила и процессы

---

## 1.2 Стандарт: ArchiMate 3.2 — Technology Layer (рекомендуемый)

> Если проект не использует ArchiMate — допускается альтернативная нотация (C4/UML/ADR и т.п.), при этом **обязательны** инварианты: слои, трассировка, реестр сущностей, связи и источники фактов.

### Сущности Technology Layer (полный перечень)

#### Active Structure Elements (что исполняет)

| Элемент | ArchiMate | Описание | Когда использовать |
|---------|-----------|----------|-------------------|
| **Node** | `Node` | Вычислительный ресурс | Сервер, VM, контейнер, кластер |
| **Device** | `Device` | Физическое устройство | Сервер, edge device, IoT gateway |
| **System Software** | `System_Software` | Системное ПО | OS, runtime, СУБД, брокер |
| **Technology Collaboration** | `Technology_Collaboration` | Группа узлов | Кластер, стек мониторинга |
| **Technology Interface** | `Technology_Interface` | Точка доступа | Порт, протокол, endpoint |

#### Behavior Elements (что происходит)

| Элемент | ArchiMate | Описание | Когда использовать |
|---------|-----------|----------|-------------------|
| **Technology Function** | `Technology_Function` | Функция инфраструктуры | Контейнеризация, кэширование |
| **Technology Process** | `Technology_Process` | Инфраструктурный процесс | Deployment, backup, failover |
| **Technology Interaction** | `Technology_Interaction` | Взаимодействие узлов | Репликация, синхронизация |
| **Technology Event** | `Technology_Event` | Инфраструктурное событие | Startup, crash, failover trigger |
| **Technology Service** | `Technology_Service` | Инфраструктурный сервис | Database service, cache service |

#### Passive Structure Elements (что хранится/передаётся)

| Элемент | ArchiMate | Описание | Когда использовать |
|---------|-----------|----------|-------------------|
| **Artifact** | `Artifact` | Артефакт | Docker image, config file, package |
| **Communication Network** | `Communication_Network` | Сеть | LAN, VPN, internal network |
| **Path** | `Path` | Маршрут | Network path, data flow |

---

## 1.3 Источники для заполнения

| Приоритет | Документ | Путь | Что извлекать |
|-----------|----------|------|---------------|
| **0** | **Каталог сущностей** | **`docs/requirements/архитектура/сущности.md`** | **Object N — номера компонентов** |
| **1** | **Application Layer** | **`docs/requirements/архитектура/описание AL.md`** | **Процесс AL: N — номера сценариев** |
| 2 | Стек проекта | `docs/requirements/структура ПО/стек проекта.md` | Технологии инфраструктуры |
| 3 | Требования (NFR) | `docs/requirements/требования/**` | Availability, RTO, RPO, security |
| 4 | Порты | `docs/requirements/структураПО/ports.md` | Сетевые интерфейсы |

---

## 1.4 Алгоритм заполнения

### Шаг 0: Проверить зависимости
- Убедиться, что существует `docs/requirements/архитектура/сущности.md`
- Убедиться, что существует `docs/requirements/архитектура/описание AL.md`
- Запомнить нумерацию Technology Components (Object N)
- Запомнить нумерацию Application Scenarios (Процесс AL: N)

### Шаг 1: Сопоставить AL -> TL
- Для каждого Application Scenario определить инфраструктурные компоненты
- Связать: `Процесс AL: N` -> какие узлы/сервисы обеспечивают

### Шаг 2: Описать инфраструктуру
- Выписать все Nodes из стека проекта
- Определить System Software (OS, runtime, СУБД)
- Указать сети и связи

### Шаг 3: Определить механизмы надёжности
- High Availability (кластеризация, репликация)
- Backup & Recovery (стратегия, RTO/RPO)
- Failover (автоматический/ручной)

### Шаг 4: Описать безопасность
- Шифрование (at rest, in transit)
- Сетевая безопасность (firewall, segmentation)
- Доступ (VPN, аутентификация)

### Шаг 5: Добавить observability
- Мониторинг (метрики, health checks)
- Логирование (сбор, хранение, ротация)
- Алертинг (правила, маршрутизация)

### Шаг 6: Оценить готовность
- Проверить покрытие всех AL сценариев
- Убедиться в наличии HA/DR стратегии
- Проверить compliance требования

---

## 1.5 Разграничение слоёв: AL / TL

### Что относится к TL (разрешено)

| Категория | Описание |
|-----------|----------|
| Инфраструктура | Серверы, VM, контейнеры, кластеры |
| Сети | Подсети, firewall rules, VPN, DNS |
| Системное ПО | OS, runtime, СУБД (как инфраструктура) |
| Конфигурации | Размеры ресурсов, репликация, retention |
| Безопасность | Шифрование, key management |
| Процессы Ops | Deployment, backup, failover, scaling |

### Что НЕ относится к TL (запрещено)

| Уровень | Категория | Описание |
|---------|-----------|----------|
| **BL** | Бизнес-логика | Правила, процессы, ценности |
| **AL** | Прикладная логика | API endpoints, сервисы, паттерны retry |
| **AL** | Data Objects | DTO, entities, messages |

---

## 1.6 Паттерны надёжности TL

### High Availability (HA)
```
- Clustering: количество узлов, механизм выбора leader
- Replication: sync/async, lag tolerance
- Load balancing: алгоритм, health checks
```

### Backup & Recovery
```
- Backup type: full/incremental, schedule
- Storage: location, encryption, retention
- RTO/RPO: целевые значения
- Verification: тестирование восстановления
```

### Failover
```
- Detection: время обнаружения сбоя
- Promotion: автоматическое/ручное
- Data loss: допустимая потеря данных
```

---

## 1.7 Паттерны безопасности TL

### Encryption
```
- In transit: протокол, версия
- At rest: алгоритм, key management
- Certificate management: rotation, renewal
```

### Network Security
```
- Segmentation: подсети, isolation
- Firewall: ingress/egress rules
- Access control: VPN, bastion hosts
```

---

## 1.8 Observability TL

### Monitoring
```
- Metrics: system (CPU, RAM, disk), application exporters
- Health checks: endpoints, frequency, timeout
- Dashboards: SLA compliance, resource usage
```

### Logging
```
- Collection: agent, format
- Storage: retention, indexing
- Search: query capabilities
```

### Alerting
```
- Rules: thresholds, severity
- Routing: channels по severity
- Escalation: timeout, on-call
```

---

## 1.9 Коды решений (TL-*)

| Код | Область | Описание |
|-----|---------|----------|
| TL-C1 | Artifacts | Versioning, scanning, signing |
| TL-C2 | Security | Encryption, firewall, access control |
| TL-C3 | High Availability | Clustering, failover, replication |
| TL-P1 | Deployment | Orchestration, startup order |
| TL-P2 | Messaging | Broker configuration, delivery guarantees |
| TL-P3 | Networking | Proxy, load balancing, SSL termination |
| TL-P4 | Storage | Database configuration, tuning |
| TL-P5 | Backup | Strategy, retention, verification |
| TL-P6 | Monitoring | Metrics collection, exporters |
| TL-P7 | Logging | Collection, storage, rotation |
| TL-P8 | Alerting | Rules, routing, escalation |
| TL-P9 | CI/CD | Pipeline, deployment strategy |
| TL-P10 | Edge | Local autonomy, buffering |

---

## 1.10 Критерии оценки готовности

| Критерий | Вопрос | Вес |
|----------|--------|-----|
| Покрытие AL | Все Application Scenarios имеют инфраструктуру? | 20% |
| HA | Критические компоненты кластеризованы? | 15% |
| Backup | Стратегия backup/recovery определена? | 15% |
| Security | Шифрование и сетевая безопасность описаны? | 15% |
| Monitoring | Метрики и health checks настроены? | 10% |
| Logging | Сбор и хранение логов определены? | 10% |
| Alerting | Правила алертинга настроены? | 10% |
| Чистота TL | Отсутствуют BL/AL детали? | 5% |

**Порог готовности:** >=80% -> готов к реализации

---

# ЧАСТЬ 2: ОБЯЗАТЕЛЬНЫЕ РАЗДЕЛЫ ПРИ ОФОРМЛЕНИИ

---

## 2.0 Контекст документа

```markdown
## 0. Контекст документа

- **Проект / продукт:** `<PROJECT_NAME>`
- **Версия:** `<X.Y>`
- **Дата:** `<YYYY-MM-DD>`
- **Стандарт:** ArchiMate 3.2 — Technology Layer
- **Владелец:** `<team/person>`

### Зависимости (статус)

| Документ | Путь | Статус |
|----------|------|--------|
| Каталог сущностей | `docs/requirements/архитектура/сущности.md` | `<read/not found>` |
| Application Layer | `docs/requirements/архитектура/описание AL.md` | `<read/not found>` |
| Стек проекта | `docs/requirements/структураПО/стек проекта.md` | `<read/not found>` |
```

---

## 2.1 Infrastructure Components

```markdown
## 1. Infrastructure Components

| ID | Component | Тип | Назначение | Object N |
|----|-----------|-----|------------|----------|
| TN-01 | `<name>` | `<Node/Device/Software>` | `<description>` | Object N |
| TN-02 | `<name>` | `<...>` | `<...>` | Object N |
```

---

## 2.2 Сценарии TL

```markdown
## 2. Сценарии Technology Layer

---

### TL-01. `<Название сценария>`

**Участники:** `<TN-XX (Component)>`, `<технология из стека>`

**Процесс AL:** `<номера из описание AL.md>`

**Описание:** `<Что происходит на инфраструктурном уровне>`

**Конфигурация:**
- `<параметр>`: `<значение>`

**High Availability (TL-C3):** (если применимо)
- Clustering: `<описание>`
- Replication: `<описание>`
- Failover: `<описание>`

**Backup (TL-P5):** (если применимо)
- Strategy: `<full/incremental>`
- Schedule: `<cron>`
- Retention: `<N days>`
- RTO/RPO: `<values>`

**Security (TL-C2):** (если применимо)
- Encryption: `<описание>`
- Access: `<описание>`

**Monitoring (TL-P6):**
- Metrics: `<что собирается>`
- Health check: `<endpoint, frequency>`

**SLA:**
- Availability: `<N>%`
- Latency: `<N>` ms
- RTO/RPO: `<values>`

**Связи:** `<ArchiMate relation>` (`<source>` -> `<target>`)

**Ценность:** `<Инфраструктурная ценность>`

**Статус:** `<Утверждён / Опционален>`

---
```

---

## 2.3 Критические решения

```markdown
## 3. Критические решения (TL-*)

| Код | Область | Действие | Применено в сценариях |
|-----|---------|----------|----------------------|
| TL-C1 | Artifacts | `<описание>` | TL-01, TL-07 |
| TL-C2 | Security | `<описание>` | TL-02, TL-03, TL-06 |
| TL-C3 | HA | `<описание>` | TL-04, TL-08, TL-09 |
```

---

## 2.4 SLA по компонентам

```markdown
## 4. SLA по компонентам

| Component | Availability | RTO | RPO | Scope |
|-----------|--------------|-----|-----|-------|
| `<name>` | `<N>%` | `<time>` | `<time>` | `<cluster/instance>` |
```

---

## 2.5 Согласованность слоёв

```markdown
## 5. Согласованность слоёв (BL -> AL -> TL)

| BL Process | AL Scenario | TL Scenario | Связь |
|------------|-------------|-------------|-------|
| `<N>` | `<N>` | TL-XX | `<ArchiMate relation>` |
```

---

## 2.6 Итоговая таблица

```markdown
## 6. Итоговая таблица сценариев

| ID | Сценарий | Компоненты | Процесс AL | Решения | Статус |
|----|----------|------------|------------|---------|--------|
| TL-01 | `<name>` | TN-01, TN-02 | N, M | TL-CX | `<status>` |
```

---

## 2.7 Итоговая оценка

```markdown
## 7. Итоговая оценка

| Критерий | Оценка | Комментарий |
|----------|--------|-------------|
| Покрытие AL | `/10` | |
| HA | `/10` | |
| Backup | `/10` | |
| Security | `/10` | |
| Monitoring | `/10` | |
| Logging | `/10` | |
| Alerting | `/10` | |
| Чистота TL | `/10` | |
| **OVERALL** | **X.X/10** | |

**Готовность:**
- [ ] >=8.0 — **READY FOR IMPLEMENTATION**
- [ ] 6.0-7.9 — Требуется доработка
- [ ] <6.0 — Существенная переработка
```

---

**Последнее обновление:** `<YYYY-MM-DD>`
