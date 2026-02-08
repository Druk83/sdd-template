# Создай диаграмму Context Map (H6)

Процедура этапа [5.4] из `.requirements/трек разработки.md`.

> **Важно:** это **методика** (read-only) в `.requirements/**`.
> **Подход:** `.approach/context-map.md` (концептуальная методология Context Map).

---

**Входные данные:**
- `docs/requirements/сценарии/<domain_slug>/ограниченные контексты.md` (этап [5.3])

**Выходные данные:**
- `docs/requirements/сценарии/<domain_slug>/diagrams/context-map.plantuml` (H8)

---

## Примеры заполнения (ОБЯЗАТЕЛЬНО изучить перед созданием)

> **Важно:** Примеры ниже носят иллюстративный характер. Конкретные BC и связи
> должны определяться на основе документа `ограниченные контексты.md` проекта.

### Считать верным: Достаточная детализация Context Map

```plantuml
@startuml ContextMap_Orders
!theme plain
skinparam backgroundColor #FFFFFF
skinparam componentStyle rectangle

title Context Map: Order Management

skinparam component {
    BackgroundColor<<Core>> #FFF59D
    BackgroundColor<<Supporting>> #B3E5FC
    BackgroundColor<<External>> #F8BBD9
    BackgroundColor<<ACL>> #FFCC80
}

component "BC: Order Processing\nOrder lifecycle" as Orders <<Core>>
component "BC: Inventory\nStock management" as Inventory <<Supporting>>
component "BC: Notifications\nMessaging" as Notify <<Supporting>>
component "EXT: Payment Gateway" as Payment <<External>>
component "ACL" as ACL_Payment <<ACL>>

Orders -[#1976D2,thickness=2]-> Inventory : <color:#1976D2>U/D</color>
Orders .[#2196F3,dashed].> Notify : <color:#2196F3>OrderCreated</color>
Payment -[#FF9800]-> ACL_Payment
ACL_Payment -[#FF9800]-> Orders : <color:#FF9800>ACL</color>

legend right
|= Тип BC |= Цвет |
| Core | Желтый |
| Supporting | Голубой |
| External | Розовый |
| ACL | Оранжевый |
endlegend

@enduml
```

**Почему верно:**
- BC классифицированы (Core/Supporting/External)
- Типы связей указаны (U/D, ACL, Event Flow)
- Цвета соответствуют типам BC
- Легенда присутствует
- Направление зависимостей указано

### Считать неверным: Недостаточная детализация

```plantuml
@startuml ContextMap
Orders --> Inventory
Orders --> Payments
Orders --> Notifications
@enduml
```

**Почему неверно:**
- BC не классифицированы (нет Core/Supporting/Generic)
- Типы связей не указаны (U/D? CF? ACL?)
- Нет цветовой схемы
- Нет легенды
- Нет описания ответственности BC
- Невозможно понять архитектуру интеграций

---

## Минимальные критерии детализации Context Map

| Элемент | Минимум | Как проверить |
|---------|---------|---------------|
| **BC на диаграмме** | Все BC из `ограниченные контексты.md` | Сравнить с разделом 2 |
| **Классификация BC** | Указан тип (Core/Supporting/Generic) | Цвет + <<type>> |
| **Внешние системы** | Все EXT из интеграций | Отдельный цвет (розовый) |
| **ACL** | Показаны где есть legacy интеграции | Оранжевый цвет |
| **Типы связей** | U/D, CF, ACL, OHS для каждой связи | Метка на стрелке |
| **Событийные потоки** | Из Integration Matrix | Пунктирные стрелки с именем события |
| **Легенда** | Присутствует | Внизу или справа диаграммы |
| **Рендеринг** | Без ошибок | Проверить через PlantUML/Kroki |

---

## Правила извлечения данных для Context Map

| Откуда | Что извлекать | Куда |
|--------|---------------|------|
| Ограниченные контексты, раздел 2 | Список BC с ответственностями | `component` элементы |
| Ограниченные контексты, раздел 2 | Тип BC (Core/Supporting/Generic) | `<<type>>` стереотип |
| Ограниченные контексты, раздел 3 | Context Map связи | Стрелки с типами (U/D, CF, ACL) |
| Ограниченные контексты, раздел 3.1 | ACL | `component` с `<<ACL>>` |
| Ограниченные контексты, раздел 4 | Integration Matrix | Пунктирные стрелки (Event Flow) |
| Карточка домена, `interfaces` | Внешние системы | `component` с `<<External>>` |

---

## 1. Когда строить Context Map

**Предусловия:**
- Этап [5.3] Ограниченные контексты завершен
- Выделены Bounded Contexts (BC) с ответственностями
- Определены интеграции между BC (события, API)

**Результат:**
- `docs/requirements/сценарии/<domain>/diagrams/context-map.plantuml`
- Опционально: отдельные диаграммы для подсистем

---

## 2. Типы связей Context Map (DDD)

| Тип связи | Направление | Описание | Когда использовать |
|-----------|-------------|----------|-------------------|
| **Customer/Supplier** | U → D | Upstream поставляет, Downstream потребляет | Зависимость с возможностью влияния |
| **Conformist** | U → D | Downstream принимает модель Upstream без изменений | Нет возможности влиять на поставщика |
| **Anti-Corruption Layer (ACL)** | U → [ACL] → D | Downstream защищается от чужой модели | Интеграция с legacy/внешними системами |
| **Open Host Service (OHS)** | U → D | Upstream предоставляет публичный протокол | API для множества потребителей |
| **Published Language (PL)** | U ↔ D | Общий язык/схема обмена | JSON Schema, Protobuf, AsyncAPI |
| **Shared Kernel** | A ↔ B | Общий код/модель между контекстами | Тесная связь, общая команда |
| **Partnership** | A ↔ B | Взаимозависимые контексты, совместное развитие | Две команды, общие цели |
| **Separate Ways** | A | B | Контексты не интегрируются | Независимые домены |

---

## 3. Цветовая схема

| Элемент | Цвет | HEX | Назначение |
|---------|------|-----|------------|
| **Core Domain BC** | Желтый | `#FFF59D` | Основной бизнес |
| **Supporting BC** | Голубой | `#B3E5FC` | Поддерживающие функции |
| **Generic BC** | Серый | `#E0E0E0` | Типовые/внешние сервисы |
| **External System** | Розовый | `#F8BBD9` | Внешние системы |
| **ACL** | Оранжевый | `#FFCC80` | Anti-Corruption Layer |
| **Shared Kernel** | Зеленый | `#C8E6C9` | Общий код |

### Цвета связей

| Тип связи | Цвет | Стиль |
|-----------|------|-------|
| Customer/Supplier | `#1976D2` | solid, thickness=2 |
| Conformist | `#9E9E9E` | dashed |
| ACL | `#FF9800` | solid, thickness=2 |
| OHS/PL | `#4CAF50` | solid |
| Shared Kernel | `#8BC34A` | dotted, thickness=2 |
| Partnership | `#9C27B0` | solid, bidirectional |
| Event Flow | `#2196F3` | dashed |

---

## 4. Context Map — PlantUML

### 4.1 Шаблон

```plantuml
@startuml ContextMap_<Domain>
!theme plain
skinparam backgroundColor #FFFFFF
skinparam defaultFontSize 11
skinparam componentStyle rectangle
skinparam linetype ortho

title Context Map: <Domain Name>

' ========== ЦВЕТОВАЯ СХЕМА ==========
skinparam component {
    BackgroundColor<<Core>> #FFF59D
    BackgroundColor<<Supporting>> #B3E5FC
    BackgroundColor<<Generic>> #E0E0E0
    BackgroundColor<<External>> #F8BBD9
    BackgroundColor<<ACL>> #FFCC80
    BackgroundColor<<Shared>> #C8E6C9
}

' ========== BOUNDED CONTEXTS ==========
component "BC: <Name>\n<responsibility>" as BC1 <<Core>>
component "BC: <Name>\n<responsibility>" as BC2 <<Supporting>>
component "BC: <Name>\n<responsibility>" as BC3 <<Generic>>

' ========== EXTERNAL SYSTEMS ==========
component "EXT: <Name>" as EXT1 <<External>>

' ========== ACL (если есть) ==========
component "ACL" as ACL1 <<ACL>>

' ========== SHARED KERNEL (если есть) ==========
component "Shared\n<module>" as SK1 <<Shared>>

' ========== СВЯЗИ ==========
' Customer/Supplier (U -> D)
BC1 -[#1976D2,thickness=2]-> BC2 : <color:#1976D2>U/D</color>

' Conformist
BC2 -[#9E9E9E,dashed]-> BC3 : <color:#9E9E9E>CF</color>

' ACL
EXT1 -[#FF9800,thickness=2]-> ACL1
ACL1 -[#FF9800,thickness=2]-> BC1 : <color:#FF9800>ACL</color>

' Open Host Service
BC3 -[#4CAF50]-> BC2 : <color:#4CAF50>OHS/PL</color>

' Shared Kernel
BC1 -[#8BC34A,dotted,thickness=2]- SK1
BC2 -[#8BC34A,dotted,thickness=2]- SK1

' Partnership (bidirectional)
BC1 <-[#9C27B0,thickness=2]-> BC2 : <color:#9C27B0>Partnership</color>

' Event Flow
BC1 .[#2196F3,dashed].> BC2 : <color:#2196F3>EventName</color>

' ========== ЛЕГЕНДА ==========
legend right
|= Тип BC |= Цвет |
| Core Domain | Желтый |
| Supporting | Голубой |
| Generic | Серый |
| External | Розовый |
|  |  |
|= Связь |= Обозначение |
| Customer/Supplier | U/D |
| Conformist | CF |
| ACL | ACL |
| Open Host Service | OHS |
| Published Language | PL |
| Shared Kernel | SK |
| Partnership | <-> |
endlegend

@enduml
```

### 4.2 Формат элементов

```plantuml
' Bounded Context
component "BC: <Name>\n<short responsibility>" as BC_ID <<Type>>

' External System
component "EXT: <Name>" as EXT_ID <<External>>

' ACL
component "ACL\n<what it protects>" as ACL_ID <<ACL>>

' Shared Kernel
component "Shared\n<module name>" as SK_ID <<Shared>>
```

### 4.3 Формат связей

```plantuml
' Customer/Supplier: Upstream -> Downstream
BC_Upstream -[#1976D2,thickness=2]-> BC_Downstream : <color:#1976D2>U/D</color>

' Conformist: принимает модель без изменений
BC_Consumer -[#9E9E9E,dashed]-> BC_Provider : <color:#9E9E9E>CF</color>

' ACL: защита от внешней модели
EXT_Legacy -[#FF9800]-> ACL_Adapter
ACL_Adapter -[#FF9800]-> BC_Internal : <color:#FF9800>ACL</color>

' Open Host Service + Published Language
BC_Provider -[#4CAF50]-> BC_Consumer : <color:#4CAF50>OHS/PL\nREST API</color>

' Shared Kernel: общий код (bidirectional, no arrow)
BC_A -[#8BC34A,dotted,thickness=2]- SharedKernel
BC_B -[#8BC34A,dotted,thickness=2]- SharedKernel

' Partnership: совместное развитие
BC_A <-[#9C27B0,thickness=2]-> BC_B : <color:#9C27B0>Partnership</color>

' Event Flow (async)
BC_Publisher .[#2196F3,dashed].> BC_Subscriber : <color:#2196F3>OrderCreated</color>
```

---

## 5. Context Map — Mermaid

### 5.1 Шаблон

```mermaid
flowchart TB
    subgraph Core["Core Domain"]
        BC1["BC: Auth\nIdentity & Access"]
        BC2["BC: Orders\nOrder Management"]
    end

    subgraph Supporting["Supporting"]
        BC3["BC: Notifications\nMessaging"]
        BC4["BC: Analytics\nReporting"]
    end

    subgraph Generic["Generic"]
        BC5["BC: Payments\n3rd Party"]
    end

    subgraph External["External Systems"]
        EXT1["EXT: Legacy CRM"]
        EXT2["EXT: Payment Gateway"]
    end

    ACL1["ACL"]

    %% Customer/Supplier
    BC1 -->|U/D| BC2
    BC2 -->|U/D| BC3

    %% Conformist
    BC4 -.->|CF| BC2

    %% ACL
    EXT1 --> ACL1
    ACL1 -->|ACL| BC2

    %% OHS/PL
    BC5 -->|OHS/PL| BC2

    %% Event Flow
    BC2 -.->|OrderCreated| BC3
    BC2 -.->|OrderCreated| BC4

    %% Styles
    style BC1 fill:#FFF59D
    style BC2 fill:#FFF59D
    style BC3 fill:#B3E5FC
    style BC4 fill:#B3E5FC
    style BC5 fill:#E0E0E0
    style EXT1 fill:#F8BBD9
    style EXT2 fill:#F8BBD9
    style ACL1 fill:#FFCC80
```

### 5.2 Формат элементов Mermaid

```mermaid
%% Bounded Context
BC1["BC: <Name>\n<responsibility>"]

%% External System
EXT1["EXT: <Name>"]

%% ACL
ACL1["ACL"]

%% Связи
BC1 -->|U/D| BC2           %% Customer/Supplier
BC1 -.->|CF| BC2           %% Conformist
BC1 -->|ACL| BC2           %% через ACL
BC1 -->|OHS/PL| BC2        %% Open Host Service
BC1 -.->|EventName| BC2    %% Event Flow
BC1 <-->|Partnership| BC2  %% Partnership
```

---

## 6. Паттерны интеграции

### 6.1 Customer/Supplier с событиями

```plantuml
component "BC: Orders\n(Upstream)" as Orders <<Core>>
component "BC: Shipping\n(Downstream)" as Shipping <<Supporting>>
component "BC: Billing\n(Downstream)" as Billing <<Supporting>>

Orders .[#2196F3,dashed].> Shipping : <color:#2196F3>OrderPlaced</color>
Orders .[#2196F3,dashed].> Billing : <color:#2196F3>OrderPlaced</color>

note bottom of Orders : Publisher
note bottom of Shipping : Subscriber
note bottom of Billing : Subscriber
```

### 6.2 ACL для Legacy системы

```plantuml
component "EXT: Legacy ERP" as Legacy <<External>>
component "ACL\nERP Adapter" as ACL <<ACL>>
component "BC: Inventory" as Inventory <<Core>>

Legacy -[#FF9800,thickness=2]-> ACL : SOAP/XML
ACL -[#FF9800,thickness=2]-> Inventory : <color:#FF9800>Domain Events</color>

note right of ACL
  Transforms:
  - Legacy Product -> Product
  - Legacy Order -> OrderLine
end note
```

### 6.3 Shared Kernel

```plantuml
component "BC: Auth" as Auth <<Core>>
component "BC: Users" as Users <<Core>>
component "Shared\nIdentity" as Identity <<Shared>>

Auth -[#8BC34A,dotted,thickness=2]- Identity
Users -[#8BC34A,dotted,thickness=2]- Identity

note bottom of Identity
  Shared:
  - UserId value object
  - Permission enum
  - Role entity
end note
```

### 6.4 Open Host Service + Published Language

```plantuml
component "BC: Catalog\n(Provider)" as Catalog <<Core>>
component "BC: Search\n(Consumer)" as Search <<Supporting>>
component "BC: Mobile App\n(Consumer)" as Mobile <<Supporting>>

Catalog -[#4CAF50]-> Search : <color:#4CAF50>OHS: REST API\nPL: OpenAPI 3.0</color>
Catalog -[#4CAF50]-> Mobile : <color:#4CAF50>OHS: GraphQL\nPL: Schema</color>

note right of Catalog
  Published Language:
  - OpenAPI spec
  - JSON Schema
  - AsyncAPI (events)
end note
```

---

## 7. Связь с Integration Matrix

Context Map визуализирует данные из раздела 4 "Integration Matrix" документа `ограниченные контексты.md`:

| Publisher (BC) | Event | Subscribers (BC) | Визуализация |
|----------------|-------|------------------|--------------|
| Orders | OrderPlaced | Shipping, Billing | `Orders .[dashed].> Shipping : OrderPlaced` |
| Orders | OrderCancelled | Shipping, Billing | `Orders .[dashed].> Billing : OrderCancelled` |

---

## 8. Примеры

### 8.1 Smart Home Context Map

```plantuml
@startuml ContextMap_SmartHome
!theme plain
skinparam backgroundColor #FFFFFF
skinparam componentStyle rectangle

title Context Map: Smart Home System

skinparam component {
    BackgroundColor<<Core>> #FFF59D
    BackgroundColor<<Supporting>> #B3E5FC
    BackgroundColor<<Generic>> #E0E0E0
    BackgroundColor<<External>> #F8BBD9
    BackgroundColor<<ACL>> #FFCC80
}

' Core Domain
component "BC: Device Management\nIoT control & state" as Devices <<Core>>
component "BC: Automation\nRules & scenarios" as Automation <<Core>>
component "BC: Auth\nIdentity & access" as Auth <<Core>>

' Supporting
component "BC: Notifications\nAlerts & messaging" as Notify <<Supporting>>
component "BC: Analytics\nTelemetry & reports" as Analytics <<Supporting>>

' Generic / External
component "BC: Billing\nPayments" as Billing <<Generic>>
component "EXT: Voice Assistant\nAlice/Google" as Voice <<External>>
component "EXT: RSO\nUtility provider" as RSO <<External>>

' ACL
component "ACL" as ACL_Voice <<ACL>>
component "ACL" as ACL_RSO <<ACL>>

' Связи
Auth -[#1976D2,thickness=2]-> Devices : <color:#1976D2>U/D</color>
Auth -[#1976D2,thickness=2]-> Automation : <color:#1976D2>U/D</color>

Devices -[#1976D2,thickness=2]-> Automation : <color:#1976D2>U/D</color>
Automation .[#2196F3,dashed].> Devices : <color:#2196F3>CommandIssued</color>
Devices .[#2196F3,dashed].> Analytics : <color:#2196F3>TelemetryReceived</color>
Automation .[#2196F3,dashed].> Notify : <color:#2196F3>AlertTriggered</color>

Voice -[#FF9800]-> ACL_Voice
ACL_Voice -[#FF9800]-> Automation : <color:#FF9800>ACL</color>

Analytics -[#4CAF50]-> RSO : <color:#4CAF50>OHS/PL\nREST</color>
RSO -[#FF9800]-> ACL_RSO
ACL_RSO -[#FF9800]-> Billing : <color:#FF9800>ACL</color>

legend right
|= Тип BC |= Цвет |
| Core | Желтый |
| Supporting | Голубой |
| Generic | Серый |
| External | Розовый |
| ACL | Оранжевый |
endlegend

@enduml
```

---

## 9. Ссылки

- Ограниченные контексты: `.requirements/сценарии/ограниченные контексты.md`
- Определение доменов: `.requirements/домены/определение доменов.md`
- Формат диаграмм: `docs/requirements/обоснование выбора.md`

---

## Критерии готовности этапа [5.4] (Context Map)

### Минимальные (блокируют завершение этапа [5])

- [ ] **BC на диаграмме:** все BC из `ограниченные контексты.md` присутствуют
- [ ] **Классификация:** BC типизированы (Core/Supporting/Generic)
- [ ] **Внешние системы:** все EXT из интеграций показаны
- [ ] **Типы связей:** указаны (U/D, CF, ACL, OHS) для каждой связи
- [ ] **Событийные потоки:** события из Integration Matrix визуализированы
- [ ] **Легенда:** присутствует с расшифровкой цветов и связей
- [ ] **Рендеринг:** диаграмма рендерится без ошибок
- [ ] **H8 создан:** `docs/requirements/сценарии/<domain_slug>/diagrams/context-map.plantuml`

### Рекомендуемые

- [ ] **ACL:** показаны для интеграций с legacy/внешними системами
- [ ] **Направление U/D:** указано Upstream/Downstream
- [ ] **Цветовая схема:** соответствует стандарту (Core=желтый, Supporting=голубой, etc.)
- [ ] **Размер:** не перегружена (max 10-12 BC на диаграмму)

### Проверка соответствия

- [ ] Сравнить с разделом 2 `ограниченные контексты.md` — все BC присутствуют
- [ ] Сравнить с разделом 3 `Context Map` — все связи показаны
- [ ] Сравнить с разделом 4 `Integration Matrix` — события визуализированы
