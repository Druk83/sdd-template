# Связи архитектуры (ArchiMate 3.2)

> **Важно:** этот файл в `.requirements/**` — **шаблон** (read-only).
> Заполненная версия хранится в: `docs/requirements/архитектура/связи.md`.

**Примечание по ссылкам:** рассматривай `REQ:*` ключи как канонические ссылки на факты проекта (например `REQ:STACK`, `REQ:PORTS`). Указывай рядом допустимый формат пути для удобства, но не жёстко привязывай шаблон к конкретным именам директорий.
**Примечание по старым файлам:** если в репозитории есть файл `.requirements/архитектура/описание связь TL AL BL.md` — он должен либо содержать минимальный каркас и ссылку на основной шаблон, либо быть удалён; не оставляйте пустые дублеры, они вводят в заблуждение агентов.
---

## ЗАВИСИМОСТИ

**Перед заполнением этого документа ОБЯЗАТЕЛЬНО должны существовать:**

```
1. docs/requirements/архитектура/сущности.md      <- ID сущностей (BA-*, AC-*, TN-*, ...)
2. docs/requirements/архитектура/описание BL.md   <- ID процессов BL (BP-*, BE-*)
3. docs/requirements/архитектура/описание AL.md   <- ID сценариев AL (AP-*, AE-*)
4. docs/requirements/архитектура/описание TL.md   <- ID сценариев TL (TP-*, TE-*)
```

Связи указываются между сущностями по типизированным ID:
- `AC-001 --Serving--> BS-001` (Application Component обслуживает Business Service)
- `AR-001 --Realization--> AC-001` (Artifact реализует Application Component)
- `TN-001 --Assignment--> AR-001` (Node назначен для Artifact)

**Если зависимости не созданы** — сначала выполни шаблоны:
- `.requirements/архитектура/сущности архитекутры.md`
- `.requirements/архитектура/описание BL.md`
- `.requirements/архитектура/описание AL.md`
- `.requirements/архитектура/описание TL.md`

---

## МИНИМАЛЬНЫЙ НАБОР СВЯЗЕЙ (MUST)

> **Для простых проектов:** достаточно заполнить только этот раздел.
> **Для сложных проектов:** после минимума переходи к полному перечню в "ЧАСТЬ 1".

### Обязательные межслойные связи (10 типов)

| # | Source | Relation | Target | Описание | Пример |
|---|--------|----------|--------|----------|--------|
| 1 | **AR-*** (Artifact) | Realization | **AC-*** (App Component) | Артефакт реализует компонент | `AR-001 --Realization--> AC-001` |
| 2 | **TN-*** (Node) | Assignment | **AR-*** (Artifact) | Узел размещает артефакт | `TN-001 --Assignment--> AR-001` |
| 3 | **SW-*** (System Software) | Assignment | **AC-*** (App Component) | ПО хостит компонент | `SW-001 --Assignment--> AC-001` |
| 4 | **TS-*** (Tech Service) | Serving | **AC-*** (App Component) | Тех. сервис обслуживает компонент | `TS-001 --Serving--> AC-001` |
| 5 | **AC-*** (App Component) | Realization | **AI-*** (App Interface) | Компонент реализует интерфейс | `AC-001 --Realization--> AI-001` |
| 6 | **AS-*** (App Service) | Realization | **BS-*** (Business Service) | Прикл. сервис реализует бизнес-сервис | `AS-001 --Realization--> BS-001` |
| 7 | **AS-*** (App Service) | Serving | **BP-*** (Business Process) | Прикл. сервис обслуживает процесс | `AS-001 --Serving--> BP-001` |
| 8 | **AI-*** (App Interface) | Serving | **BR-*** (Business Role) | Интерфейс обслуживает роль | `AI-001 --Serving--> BR-001` |
| 9 | **DO-*** (Data Object) | Realization | **BO-*** (Business Object) | Данные реализуют бизнес-объект | `DO-001 --Realization--> BO-001` |
| 10 | **AE-*** (App Event) | Triggering | **BE-*** (Business Event) | Прикл. событие триггерит бизнес-событие | `AE-001 --Triggering--> BE-001` |

### Обязательные внутрислойные связи (5 типов)

| # | Source | Relation | Target | Описание | Пример |
|---|--------|----------|--------|----------|--------|
| 1 | **BA-*** (Actor) | Assignment | **BR-*** (Role) | Актор исполняет роль | `BA-001 --Assignment--> BR-001` |
| 2 | **BR-*** (Role) | Assignment | **BP-*** (Process) | Роль выполняет процесс | `BR-001 --Assignment--> BP-001` |
| 3 | **BP-*** (Process) | Access | **BO-*** (Object) | Процесс читает/пишет объект | `BP-001 --Access--> BO-001` |
| 4 | **AC-*** (Component) | Access | **DO-*** (Data Object) | Компонент читает/пишет данные | `AC-001 --Access--> DO-001` |
| 5 | **BE-*** (Event) | Triggering | **BP-*** (Process) | Событие запускает процесс | `BE-001 --Triggering--> BP-001` |

### Минимальная цепочка трассировки

```
[Business Layer]
BA-001 (Actor) --Assignment--> BR-001 (Role) --Assignment--> BP-001 (Process)
                                                                    |
                                                            --Access--> BO-001 (Object)
                                                                    |
                                                            <--Realization--
[Application Layer]                                                 |
AC-001 (Component) --Realization--> AS-001 (Service) --Realization--> BS-001
         |                                    |
         --Access--> DO-001 (Data) --Realization--> BO-001
         |
         <--Realization--
[Technology Layer]    |
AR-001 (Artifact) --deployed on--> TN-001 (Node)
         ^
         |
SW-001 (Software) --Assignment--> AC-001
```

> **Порог готовности:** минимум 15 связей (10 межслойных + 5 внутрислойных) для базового сценария.
> После заполнения минимума — переходи к полному перечню для детализации.

---

## Подсказка: типы связей ArchiMate 3.2

### Структурные связи (Structural Relations)

| Связь | Нотация | Описание |
|-------|---------|----------|
| **Composition** | `◆──` | Неразрывная часть целого |
| **Aggregation** | `◇──` | Часть целого (может существовать отдельно) |
| **Assignment** | `○──●` | Назначение ресурса на поведение |
| **Realization** | `- - -▷` | Реализация абстракции конкретным элементом |

### Связи зависимости (Dependency Relations)

| Связь | Нотация | Описание |
|-------|---------|----------|
| **Serving** | `──▷` | Предоставление сервиса |
| **Access** | `- - -` | Доступ к данным (read/write) |
| **Influence** | `- - ->` | Влияние на мотивационный элемент |

### Динамические связи (Dynamic Relations)

| Связь | Нотация | Описание |
|-------|---------|----------|
| **Triggering** | `──▶` | Инициирование поведения |
| **Flow** | `──>` | Передача данных/объектов |

### Другие связи

| Связь | Нотация | Описание |
|-------|---------|----------|
| **Specialization** | `──▷` (пустая) | Наследование/специализация |
| **Association** | `────` | Общая связь |

---

# ЧАСТЬ 1: ОПИСАТЕЛЬНАЯ (правила, источники, запреты)

---

## 1.1 Назначение документа

Документ описывает **связи** между сущностями архитектуры:
- **Внутрислойные связи** — внутри каждого слоя (BL, AL, TL)
- **Межслойные связи** — между слоями (TL → AL → BL)

**Зачем нужны связи:**
- Трассировка от бизнеса до инфраструктуры
- Понимание зависимостей между компонентами
- Построение диаграмм ArchiMate
- Анализ влияния изменений

---

## 1.2 Источники для заполнения

| Приоритет | Документ | Путь | Что извлекать |
|-----------|----------|------|---------------|
| **0** | **Каталог сущностей** | **`docs/requirements/архитектура/сущности.md`** | **Object N — номера для ссылок** |
| **1** | **Business Layer** | **`docs/requirements/архитектура/описание BL.md`** | **Процесс BL: N — бизнес-процессы** |
| **2** | **Application Layer** | **`docs/requirements/архитектура/описание AL.md`** | **Процесс AL: N — прикладные сценарии** |
| **3** | **Technology Layer** | **`docs/requirements/архитектура/описание TL.md`** | **Процесс TL: N — инфраструктурные сценарии** |
| 4 | Стек проекта | REQ:STACK (формат пути: `docs/requirements/структура ПО/стек проекта.md`) | Технологии, компоненты |

---

## 1.3 Полный перечень связей по слоям

### Business Layer — допустимые связи

| Source | Relation | Target | Описание |
|--------|----------|--------|----------|
| **Business Actor** | Assignment | Business Role | Актор исполняет роль |
| **Business Actor** | Composition | Business Actor | Актор включает актора (подразделение) |
| **Business Actor** | Aggregation | Business Collaboration | Актор участвует в коллаборации |
| **Business Role** | Composition | Business Role | Роль включает подроль |
| **Business Role** | Assignment | Business Process | Роль выполняет процесс |
| **Business Role** | Assignment | Business Function | Роль выполняет функцию |
| **Business Role** | Assignment | Business Interaction | Роль участвует во взаимодействии |
| **Business Role** | Aggregation | Business Collaboration | Роль входит в коллаборацию |
| **Business Collaboration** | Assignment | Business Interaction | Коллаборация выполняет взаимодействие |
| **Business Collaboration** | Aggregation | Business Collaboration | Вложенные коллаборации |
| **Business Interface** | Serving | Business Role | Интерфейс обслуживает роль |
| **Business Interface** | Serving | Business Actor | Интерфейс обслуживает актора |
| **Business Process** | Triggering | Business Process | Процесс запускает процесс |
| **Business Process** | Flow | Business Process | Передача между процессами |
| **Business Process** | Realization | Business Service | Процесс реализует сервис |
| **Business Process** | Access | Business Object | Процесс читает/пишет объект |
| **Business Process** | Access | Contract | Процесс использует контракт |
| **Business Process** | Access | Representation | Процесс использует представление |
| **Business Function** | Realization | Business Service | Функция реализует сервис |
| **Business Function** | Triggering | Business Function | Функция вызывает функцию |
| **Business Function** | Access | Business Object | Функция читает/пишет объект |
| **Business Interaction** | Realization | Business Service | Взаимодействие реализует сервис |
| **Business Interaction** | Access | Business Object | Взаимодействие читает/пишет объект |
| **Business Event** | Triggering | Business Process | Событие запускает процесс |
| **Business Event** | Triggering | Business Function | Событие запускает функцию |
| **Business Event** | Triggering | Business Interaction | Событие запускает взаимодействие |
| **Business Event** | Flow | Business Event | Цепочка событий |
| **Business Service** | Serving | Business Role | Сервис обслуживает роль |
| **Business Service** | Serving | Business Actor | Сервис обслуживает актора |
| **Business Service** | Serving | Business Process | Сервис обслуживает процесс |
| **Business Service** | Access | Business Object | Сервис использует объект |
| **Business Object** | Composition | Business Object | Вложенные объекты |
| **Business Object** | Aggregation | Business Object | Агрегация объектов |
| **Business Object** | Specialization | Business Object | Наследование объектов |
| **Contract** | Association | Business Service | Контракт регулирует сервис |
| **Contract** | Association | Business Process | Контракт регулирует процесс |
| **Contract** | Access | Business Object | Контракт описывает объект |
| **Representation** | Realization | Business Object | Представление визуализирует объект |
| **Product** | Composition | Business Service | Продукт включает сервисы |
| **Product** | Composition | Contract | Продукт включает контракты |
| **Product** | Association | Business Interface | Продукт предоставляется через интерфейс |

### Application Layer — допустимые связи

| Source | Relation | Target | Описание |
|--------|----------|--------|----------|
| **Application Component** | Composition | Application Component | Вложенные компоненты |
| **Application Component** | Aggregation | Application Collaboration | Компонент участвует в коллаборации |
| **Application Component** | Assignment | Application Function | Компонент выполняет функцию |
| **Application Component** | Assignment | Application Process | Компонент выполняет процесс |
| **Application Component** | Assignment | Application Interaction | Компонент участвует во взаимодействии |
| **Application Component** | Realization | Application Service | Компонент реализует сервис |
| **Application Component** | Realization | Application Interface | Компонент реализует интерфейс |
| **Application Component** | Access | Data Object | Компонент читает/пишет данные |
| **Application Collaboration** | Assignment | Application Interaction | Коллаборация выполняет взаимодействие |
| **Application Collaboration** | Realization | Application Service | Коллаборация реализует сервис |
| **Application Interface** | Serving | Application Component | Интерфейс обслуживает компонент |
| **Application Interface** | Serving | Application Collaboration | Интерфейс обслуживает коллаборацию |
| **Application Interface** | Flow | Application Interface | Поток между интерфейсами |
| **Application Function** | Realization | Application Service | Функция реализует сервис |
| **Application Function** | Triggering | Application Function | Функция вызывает функцию |
| **Application Function** | Access | Data Object | Функция читает/пишет данные |
| **Application Process** | Realization | Application Service | Процесс реализует сервис |
| **Application Process** | Triggering | Application Process | Процесс запускает процесс |
| **Application Process** | Flow | Application Process | Поток между процессами |
| **Application Process** | Access | Data Object | Процесс читает/пишет данные |
| **Application Interaction** | Realization | Application Service | Взаимодействие реализует сервис |
| **Application Interaction** | Access | Data Object | Взаимодействие читает/пишет данные |
| **Application Event** | Triggering | Application Process | Событие запускает процесс |
| **Application Event** | Triggering | Application Function | Событие запускает функцию |
| **Application Event** | Triggering | Application Interaction | Событие запускает взаимодействие |
| **Application Event** | Flow | Application Event | Цепочка событий |
| **Application Service** | Serving | Application Component | Сервис обслуживает компонент |
| **Application Service** | Serving | Application Process | Сервис обслуживает процесс |
| **Application Service** | Access | Data Object | Сервис использует данные |
| **Data Object** | Composition | Data Object | Вложенные объекты данных |
| **Data Object** | Aggregation | Data Object | Агрегация данных |
| **Data Object** | Specialization | Data Object | Наследование данных |
| **Data Object** | Access (reverse) | Application Component | Данные доступны компоненту |

### Technology Layer — допустимые связи

| Source | Relation | Target | Описание |
|--------|----------|--------|----------|
| **Node** | Composition | Node | Вложенные узлы |
| **Node** | Assignment | Artifact | Узел размещает артефакт |
| **Node** | Assignment | Technology Function | Узел выполняет функцию |
| **Node** | Assignment | Technology Process | Узел выполняет процесс |
| **Node** | Aggregation | Technology Collaboration | Узел участвует в коллаборации |
| **Device** | Composition | Device | Вложенные устройства |
| **Device** | Assignment | System Software | Устройство хостит ПО |
| **Device** | Assignment | Node | Устройство размещает узел |
| **Device** | Realization | Node | Устройство реализует узел |
| **System Software** | Composition | System Software | Вложенное ПО |
| **System Software** | Assignment | Artifact | ПО размещает артефакт |
| **System Software** | Realization | Technology Service | ПО реализует сервис |
| **System Software** | Assignment | Technology Function | ПО выполняет функцию |
| **System Software** | Assignment | Technology Process | ПО выполняет процесс |
| **Technology Collaboration** | Assignment | Technology Interaction | Коллаборация выполняет взаимодействие |
| **Technology Collaboration** | Aggregation | Node | Коллаборация включает узлы |
| **Technology Collaboration** | Aggregation | System Software | Коллаборация включает ПО |
| **Technology Interface** | Serving | Node | Интерфейс обслуживает узел |
| **Technology Interface** | Serving | System Software | Интерфейс обслуживает ПО |
| **Technology Interface** | Association | Path | Интерфейс связан с путём |
| **Technology Function** | Realization | Technology Service | Функция реализует сервис |
| **Technology Function** | Triggering | Technology Function | Функция вызывает функцию |
| **Technology Process** | Realization | Technology Service | Процесс реализует сервис |
| **Technology Process** | Triggering | Technology Process | Процесс запускает процесс |
| **Technology Process** | Flow | Technology Process | Поток между процессами |
| **Technology Interaction** | Realization | Technology Service | Взаимодействие реализует сервис |
| **Technology Event** | Triggering | Technology Process | Событие запускает процесс |
| **Technology Event** | Triggering | Technology Function | Событие запускает функцию |
| **Technology Event** | Flow | Technology Event | Цепочка событий |
| **Technology Service** | Serving | Node | Сервис обслуживает узел |
| **Technology Service** | Serving | System Software | Сервис обслуживает ПО |
| **Technology Service** | Realization | Technology Interface | Сервис экспонирует интерфейс |
| **Artifact** | Composition | Artifact | Вложенные артефакты |
| **Artifact** | Aggregation | Artifact | Агрегация артефактов |
| **Artifact** | Realization | Application Component | Артефакт реализует компонент (межслой) |
| **Artifact** | Realization | Data Object | Артефакт реализует данные (межслой) |
| **Communication Network** | Serving | Node | Сеть обслуживает узел |
| **Communication Network** | Realization | Path | Сеть реализует путь |
| **Communication Network** | Association | Technology Interface | Сеть связана с интерфейсом |
| **Path** | Serving | Technology Interaction | Путь обслуживает взаимодействие |
| **Path** | Association | Technology Interface | Путь связан с интерфейсом |

### Межслойные связи

| Source (TL) | Relation | Target (AL) | Описание |
|-------------|----------|-------------|----------|
| Technology Service | Serving | Application Component | TL сервис обслуживает AL компонент |
| Technology Service | Serving | Application Service | TL сервис обслуживает AL сервис |
| Technology Interface | Realization | Application Interface | TL интерфейс реализует AL интерфейс |
| Artifact | Realization | Application Component | Артефакт реализует компонент |
| Artifact | Realization | Data Object | Артефакт реализует данные |
| Node | Assignment | Application Component | Узел размещает компонент |
| System Software | Assignment | Application Component | ПО хостит компонент |

| Source (AL) | Relation | Target (BL) | Описание |
|-------------|----------|-------------|----------|
| Application Service | Realization | Business Service | AL сервис реализует BL сервис |
| Application Service | Serving | Business Process | AL сервис обслуживает BL процесс |
| Application Process | Realization | Business Process | AL процесс реализует BL процесс |
| Application Function | Realization | Business Function | AL функция реализует BL функцию |
| Application Interaction | Realization | Business Interaction | AL взаимодействие реализует BL взаимодействие |
| Application Event | Triggering | Business Event | AL событие триггерит BL событие |
| Application Interface | Realization | Business Interface | AL интерфейс реализует BL интерфейс |
| Application Interface | Serving | Business Role | AL интерфейс обслуживает BL роль |
| Data Object | Realization | Business Object | Данные реализуют бизнес-объект |

---

## 1.4 Алгоритм заполнения

### Шаг 1: Внутрислойные связи Business Layer
1. Для каждого **Business Actor** определить назначенные **Business Role** (Assignment)
2. Для каждой **Business Role** определить:
   - Какие **Business Interface** использует (Role ← Interface: Serving)
   - Какие **Business Service** потребляет (Role ← Service: Serving)
   - В каких **Business Collaboration** участвует (Aggregation)
   - Какие **Business Process/Function** выполняет (Assignment)
3. Для каждого **Business Process** определить:
   - Какие **Business Service** реализует (Realization)
   - Какие **Business Object** читает/пишет (Access)
   - Какие **Business Event** его запускают (Event → Process: Triggering)
   - Какие **Business Process** запускает далее (Triggering/Flow)
4. Для каждого **Business Service** определить:
   - Какие роли/актора обслуживает (Serving)
5. Для **Contract** определить связи с **Service** и **Object** (Association, Access)
6. Для **Representation** определить связи с **Business Object** (Realization)
7. Для **Product** определить включённые **Service** и **Contract** (Composition)

### Шаг 2: Внутрислойные связи Application Layer
1. Для каждого **Application Component** определить:
   - Какие **Application Interface** реализует (Realization)
   - Какие **Application Service** реализует (Realization)
   - Какие **Application Function/Process** выполняет (Assignment)
   - В каких **Application Collaboration** участвует (Aggregation)
   - Какие **Data Object** читает/пишет (Access)
2. Для каждого **Application Process** определить:
   - Какие **Application Service** реализует/использует (Realization/Serving)
   - Какие **Application Event** его запускают (Triggering)
   - Какие **Data Object** читает/пишет (Access)
3. Для каждого **Application Interaction** определить участников и результат
4. Для каждого **Application Event** определить триггеры и последствия
5. Для каждого **Data Object** определить связи с компонентами (Access)

### Шаг 3: Внутрислойные связи Technology Layer
1. Для каждого **Device** определить:
   - Какие **Node** размещает (Assignment/Realization)
   - Какое **System Software** хостит (Assignment)
2. Для каждого **Node** определить:
   - Какое **System Software** содержит (Assignment)
   - Какие **Artifact** размещены (Assignment)
   - В каких **Technology Collaboration** участвует (Aggregation)
3. Для каждого **System Software** определить:
   - Какие **Technology Service** реализует (Realization)
   - Какие **Technology Function** выполняет (Assignment)
4. Для каждого **Technology Service** определить:
   - Какие **Technology Interface** экспонирует (Realization)
   - Какие узлы/ПО обслуживает (Serving)
5. Для каждого **Artifact** определить:
   - На каких **Node** развёрнут (Assignment)
   - Какие **Application Component** реализует (Realization — межслой)
6. Для **Communication Network** определить:
   - Какие **Path** реализует (Realization)
   - Какие **Node** обслуживает (Serving)
7. Для **Technology Event** определить триггеры процессов (Triggering)

### Шаг 4: Межслойные связи Technology → Application
1. Для каждого **Technology Service** определить обслуживаемые **Application Component** (Serving)
2. Для каждого **Artifact** определить реализуемые **Application Component** (Realization)
3. Для каждого **Technology Interface** определить связь с **Application Interface** (Realization)
4. Для каждого **Node/System Software** определить размещённые **Application Component** (Assignment)

### Шаг 5: Межслойные связи Application → Business
1. Для каждого **Application Service** определить:
   - Какие **Business Service** реализует (Realization)
   - Какие **Business Process** обслуживает (Serving)
2. Для каждого **Application Process** определить реализуемые **Business Process** (Realization)
3. Для каждого **Application Event** определить триггеры **Business Event** (Triggering)
4. Для каждого **Application Interface** определить:
   - Какие **Business Interface** реализует (Realization)
   - Какие **Business Role** обслуживает (Serving)
5. Для каждого **Data Object** определить реализуемые **Business Object** (Realization)

### Шаг 6: Полные цепочки трассировки
- Для каждого критического бизнес-сценария построить цепочку: BL → AL → TL
- Проверить, что все элементы цепочки связаны

---

## 1.5 Правила оформления связей

### Формат записи связи

```
N. <Source> → <Target>
   **Тип:** <ArchiMate relation> (<русское название>)
   **Означает:** <что означает эта связь>
   **Комментарий:** <контекст использования>
```

### Нумерация
- Нумерация сквозная внутри каждого раздела
- Опциональные связи помечаются `*(опционально)*`

### Ссылки на сущности
- Используй номера из каталога: `Object N: <Name>`
- Используй номера процессов: `Процесс BL: N`, `Процесс AL: N`, `Процесс TL: N`

---

## 1.6 Критерии оценки готовности

| Критерий | Вопрос | Вес |
|----------|--------|-----|
| Покрытие BL | Все Business сущности имеют связи? | 15% |
| Покрытие AL | Все Application сущности имеют связи? | 15% |
| Покрытие TL | Все Technology сущности имеют связи? | 15% |
| Межслойные TL→AL | Все AL компоненты связаны с TL? | 15% |
| Межслойные AL→BL | Все BL процессы связаны с AL? | 15% |
| Цепочки | Для критических сценариев есть полные цепочки? | 15% |
| Корректность типов | Типы связей соответствуют ArchiMate 3.2? | 10% |

**Порог готовности:** >=80% -> готов к построению диаграмм

---

# ЧАСТЬ 2: ОБЯЗАТЕЛЬНЫЕ РАЗДЕЛЫ ПРИ ОФОРМЛЕНИИ

---

## 2.0 Контекст документа

```markdown
## 0. Контекст документа

- **Проект / продукт:** `<PROJECT_NAME>`
- **Версия:** `<X.Y>`
- **Дата:** `<YYYY-MM-DD>`
- **Стандарт:** ArchiMate 3.2 — Relations (рекомендуемый)
- **Примечание:** Если проект не использует ArchiMate — допускается альтернативная нотация при сохранении инвариантов: слои, трассировка, реестр сущностей, связи и источники фактов.
- **Владелец:** `<team/person>`

### Зависимости (статус)

| Документ | Путь | Статус |
|----------|------|--------|
| Каталог сущностей | `docs/requirements/архитектура/сущности.md` | `<read/not found>` |
| Business Layer | `docs/requirements/архитектура/описание BL.md` | `<read/not found>` |
| Application Layer | `docs/requirements/архитектура/описание AL.md` | `<read/not found>` |
| Technology Layer | `docs/requirements/архитектура/описание TL.md` | `<read/not found>` |
```

---

## 2.1 Внутрислойные связи: Business Layer

```markdown
## 1. Связи Business Layer

### 1.1 Assignment (Actor → Role)

1. `<ActorName>` (актёр) → Роль: `<RoleName>`
   **Тип:** Assignment relation (Отношение назначения)
   **Означает:** `<кто исполняет роль>`
   **Комментарий:** `<контекст>`

### 1.2 Serving (Interface/Service → Role/Actor)

2. Интерфейс: `<InterfaceName>` → Роль: `<RoleName>`
   **Тип:** Serving relation (Отношение обслуживания)
   **Означает:** `<интерфейс обслуживает роль>`
   **Комментарий:** `<точка контакта>`

3. Сервис: `<ServiceName>` → Роль: `<RoleName>`
   **Тип:** Serving relation (Отношение обслуживания)
   **Означает:** `<сервис обслуживает роль>`
   **Комментарий:** `<ценность>`

### 1.3 Realization (Process/Function → Service)

4. Процесс: `<ProcessName>` → Сервис: `<ServiceName>`
   **Тип:** Realization relation (Отношение реализации)
   **Означает:** `<процесс реализует бизнес-сервис>`
   **Комментарий:** `<что именно делает>`

5. Функция: `<FunctionName>` → Сервис: `<ServiceName>`
   **Тип:** Realization relation (Отношение реализации)
   **Означает:** `<функция реализует сервис>`
   **Комментарий:** `<capabilities>`

### 1.4 Triggering (Event → Process/Function)

6. Событие: `<EventName>` → Процесс: `<ProcessName>`
   **Тип:** Triggering relation (Отношение инициирования)
   **Означает:** `<событие запускает процесс>`
   **Комментарий:** `<последствия>`

7. Процесс: `<ProcessName1>` → Процесс: `<ProcessName2>`
   **Тип:** Triggering relation (Отношение инициирования)
   **Означает:** `<процесс запускает следующий процесс>`
   **Комментарий:** `<цепочка>`

### 1.5 Flow (Process → Process, Event → Event)

8. Процесс: `<ProcessName1>` → Процесс: `<ProcessName2>`
   **Тип:** Flow relation (Отношение потока)
   **Означает:** `<передача результата между процессами>`
   **Комментарий:** `<что передаётся>`

### 1.6 Access (Process/Function → Object)

9. Процесс: `<ProcessName>` → Объекты: `<ObjectName1>`, `<ObjectName2>`
   **Тип:** Access relation (Отношение доступа)
   **Означает:** `<чтение/запись данных>`
   **Комментарий:** `<какие операции>`

### 1.7 Aggregation (Collaboration ← Role/Actor)

10. Коллаборация: `<CollaborationName>` ← Роли: `<Role1>`, `<Role2>`
    **Тип:** Aggregation relation (Агрегация)
    **Означает:** `<совместное участие ролей>`
    **Комментарий:** `<цель коллаборации>`

### 1.8 Association (Contract, Collaboration)

11. Контракт: `<ContractName>` ↔ Сервисы: `<Service1>`, `<Service2>`
    **Тип:** Association (Ассоциация)
    **Означает:** `<регламентирует условия>`
    **Комментарий:** `<что регулирует>`

### 1.9 Realization (Representation → Object)

12. Представление: `<RepresentationName>` → Объект: `<ObjectName>`
    **Тип:** Realization relation (Отношение реализации)
    **Означает:** `<визуальное представление объекта>`
    **Комментарий:** `<формат/назначение>`

### 1.10 Composition (Product ← Service/Contract)

13. Продукт: `<ProductName>` ← Сервисы: `<Service1>`, `<Service2>`
    **Тип:** Composition relation (Композиция)
    **Означает:** `<продукт включает сервисы>`
    **Комментарий:** `<состав продукта>`
```

---

## 2.2 Внутрислойные связи: Application Layer

```markdown
## 2. Связи Application Layer

### 2.1 Realization (Component → Interface/Service)

1. Компонент: `<ComponentName>` → Интерфейс: `<InterfaceName>`
   **Тип:** Realization relation (Отношение реализации)
   **Означает:** `<компонент публикует интерфейс>`
   **Комментарий:** `<что предоставляет>`

2. Компонент: `<ComponentName>` → Сервис: `<ServiceName>`
   **Тип:** Realization relation (Отношение реализации)
   **Означает:** `<компонент реализует сервис>`
   **Комментарий:** `<capabilities>`

### 2.2 Assignment (Component → Function/Process)

3. Компонент: `<ComponentName>` → Функция: `<FunctionName>`
   **Тип:** Assignment relation (Отношение назначения)
   **Означает:** `<компонент выполняет функцию>`
   **Комментарий:** `<внутренняя логика>`

### 2.3 Application Interaction

4. Взаимодействие: `<InteractionName>` [`<Component1>` + `<Component2>`]
   **Тип:** Application Interaction
   **Означает:** `<что происходит при взаимодействии>`
   **Комментарий:** `<протокол/механизм>`

### 2.4 Serving (Interface/Service → Component)

5. Интерфейс: `<InterfaceName>` → Компонент: `<ComponentName>`
   **Тип:** Serving relation (Отношение обслуживания)
   **Означает:** `<интерфейс обслуживает компонент>`
   **Комментарий:** `<точка интеграции>`

### 2.5 Realization (Process → Service)

6. Процесс: `<ProcessName>` → Сервис: `<ServiceName>`
   **Тип:** Realization relation (Отношение реализации)
   **Означает:** `<процесс реализует сервис>`
   **Комментарий:** `<шаги процесса>`

### 2.6 Triggering (Event → Process/Function)

7. Событие: `<EventName>` → Процесс: `<ProcessName>`
   **Тип:** Triggering relation (Отношение инициирования)
   **Означает:** `<событие запускает процесс>`
   **Комментарий:** `<что происходит далее>`

8. Процесс: `<Process1>` → Процесс: `<Process2>`
   **Тип:** Triggering relation (Отношение инициирования)
   **Означает:** `<процесс запускает следующий>`
   **Комментарий:** `<цепочка>`

### 2.7 Flow (Process → Process, Event → Event)

9. Процесс: `<Process1>` → Процесс: `<Process2>`
   **Тип:** Flow relation (Отношение потока)
   **Означает:** `<передача данных между процессами>`
   **Комментарий:** `<что передаётся>`

### 2.8 Access (Component/Process → Data Object)

10. Компонент: `<ComponentName>` → Объекты данных: `<DataObject1>`, `<DataObject2>`
    **Тип:** Access relation (Отношение доступа)
    **Означает:** `<чтение/запись данных>`
    **Комментарий:** `<какие операции>`

### 2.9 Aggregation (Collaboration ← Component)

11. Коллаборация: `<CollaborationName>` ← Компоненты: `<Comp1>`, `<Comp2>`
    **Тип:** Aggregation relation (Агрегация)
    **Означает:** `<совместная работа компонентов>`
    **Комментарий:** `<цель>`

### 2.10 Composition (Component ← Component)

12. Компонент: `<ParentComponent>` ← Компоненты: `<Child1>`, `<Child2>`
    **Тип:** Composition relation (Композиция)
    **Означает:** `<вложенные компоненты>`
    **Комментарий:** `<структура>`
```

---

## 2.3 Внутрислойные связи: Technology Layer

```markdown
## 3. Связи Technology Layer

### 3.1 Assignment/Realization (Device → Node)

1. Device: `<DeviceName>` → Node: `<NodeName>`
   **Тип:** Assignment relation (Отношение назначения)
   **Означает:** `<узел размещён на устройстве>`
   **Комментарий:** `<назначение узла>`

### 3.2 Assignment (Node/Device → System Software)

2. Node: `<NodeName>` → System Software: `<Software1>`, `<Software2>`
   **Тип:** Assignment relation (Отношение назначения)
   **Означает:** `<узел хостит ПО>`
   **Комментарий:** `<версии/конфигурация>`

### 3.3 Assignment (Node → Artifact)

3. Node: `<NodeName>` → Artifact: `<ArtifactName>`
   **Тип:** Assignment relation (Deployment)
   **Означает:** `<узел размещает артефакт>`
   **Комментарий:** `<развёртывание>`

### 3.4 Realization (Software → Technology Service)

4. System Software: `<SoftwareName>` → Technology Service: `<ServiceName>`
   **Тип:** Realization relation (Отношение реализации)
   **Означает:** `<ПО реализует сервис>`
   **Комментарий:** `<что предоставляет>`

### 3.5 Realization (Service → Technology Interface)

5. Technology Service: `<ServiceName>` → Technology Interface: `<InterfaceName>`
   **Тип:** Realization relation (Отношение реализации)
   **Означает:** `<сервис доступен через интерфейс>`
   **Комментарий:** `<протокол/порт>`

### 3.6 Serving (Service → Node/Software)

6. Technology Service: `<ServiceName>` → Node: `<NodeName>`
   **Тип:** Serving relation (Отношение обслуживания)
   **Означает:** `<сервис обслуживает узел>`
   **Комментарий:** `<что предоставляет>`

### 3.7 Aggregation (Collaboration ← Software/Node)

7. Technology Collaboration: `<CollaborationName>` ← System Software: `<SW1>`, `<SW2>`
   **Тип:** Aggregation relation (Агрегация)
   **Означает:** `<стек агрегирует компоненты>`
   **Комментарий:** `<назначение стека>`

### 3.8 Realization (Function ← Software)

8. Technology Function: `<FunctionName>` ← System Software: `<SoftwareName>`
   **Тип:** Realization relation (Отношение реализации)
   **Означает:** `<функция обеспечивается ПО>`
   **Комментарий:** `<механизм>`

### 3.9 Realization (Process ← Service)

9. Technology Process: `<ProcessName>` ← Technology Service: `<ServiceName>`
   **Тип:** Realization relation (Отношение реализации)
   **Означает:** `<процесс использует сервис>`
   **Комментарий:** `<что делает>`

### 3.10 Triggering (Event → Process)

10. Technology Event: `<EventName>` → Technology Process: `<ProcessName>`
    **Тип:** Triggering relation (Отношение инициирования)
    **Означает:** `<событие запускает процесс>`
    **Комментарий:** `<реакция>`

### 3.11 Realization (Network → Path)

11. Communication Network: `<NetworkName>` → Path: `<PathName>`
    **Тип:** Realization relation (Отношение реализации)
    **Означает:** `<сеть реализует путь>`
    **Комментарий:** `<маршрут>`

### 3.12 Serving (Network → Node)

12. Communication Network: `<NetworkName>` → Node: `<NodeName>`
    **Тип:** Serving relation (Отношение обслуживания)
    **Означает:** `<сеть обслуживает узел>`
    **Комментарий:** `<связность>`

### 3.13 Association (Path ↔ Interface)

13. Path: `<PathName>` ↔ Technology Interface: `<InterfaceName>`
    **Тип:** Association (Ассоциация)
    **Означает:** `<путь связан с интерфейсом>`
    **Комментарий:** `<endpoint>`

### 3.14 Flow/Path (Interaction)

14. Technology Interaction: `<InteractionName>` [`<Node1>` + `<Node2>`] → Path: `<PathName>`
    **Тип:** Flow/Path relation (Поток/маршрут)
    **Означает:** `<соединение по указанному пути>`
    **Комментарий:** `<протокол/сегмент сети>`

### 3.15 Composition (Node ← Node, Artifact ← Artifact)

15. Node: `<ParentNode>` ← Nodes: `<Child1>`, `<Child2>`
    **Тип:** Composition relation (Композиция)
    **Означает:** `<вложенные узлы>`
    **Комментарий:** `<структура>`
```

---

## 2.4 Межслойные связи: Technology → Application

```markdown
## 4. Межслойные связи: Technology → Application

### 4.1 Serving (Technology Service → Application Component)

| Technology Service | Тип | Application Component | Комментарий |
|--------------------|-----|----------------------|-------------|
| `<TL ServiceName>` | Serving | `<AL ComponentName>` | `<что предоставляет>` |

### 4.2 Realization (Artifact → Application Component)

| Artifact | Тип | Application Component | Комментарий |
|----------|-----|----------------------|-------------|
| `<ArtifactName>` | Realization | `<AL ComponentName>` | `<образ/пакет>` |

### 4.3 Realization (Technology Interface → Application Interface)

| Technology Interface | Тип | Application Interface | Комментарий |
|---------------------|-----|----------------------|-------------|
| `<TL InterfaceName>` | Realization | `<AL InterfaceName>` | `<протокол>` |

### 4.4 Assignment (Node/Software → Application Component)

| Node/Software | Тип | Application Component | Комментарий |
|---------------|-----|----------------------|-------------|
| `<NodeName>` | Assignment | `<AL ComponentName>` | `<размещение>` |

### Детализация ключевых связей

1. Technology Service: `<DatabaseService>` → Application Component: `<services>`
   **Тип:** Serving
   **Комментарий:** `<хранение данных>`

2. Artifact: `<Docker image>` → Application Component: `<ComponentName>`
   **Тип:** Realization
   **Комментарий:** `<контейнеризация>`
```

---

## 2.5 Межслойные связи: Application → Business

```markdown
## 5. Межслойные связи: Application → Business

### 5.1 Realization (Application Service → Business Service)

| Application Service | Тип | Business Service | Комментарий |
|--------------------|-----|------------------|-------------|
| `<AL ServiceName>` | Realization | `<BL ServiceName>` | `<что реализует>` |

### 5.2 Serving (Application Service → Business Process)

| Application Service | Тип | Business Process | Комментарий |
|--------------------|-----|------------------|-------------|
| `<AL ServiceName>` | Serving | `<BL ProcessName>` | `<что автоматизирует>` |

### 5.3 Realization (Application Process → Business Process)

| Application Process | Тип | Business Process | Комментарий |
|--------------------|-----|------------------|-------------|
| `<AL ProcessName>` | Realization | `<BL ProcessName>` | `<что реализует>` |

### 5.4 Triggering (Application Event → Business Event)

| Application Event | Тип | Business Event | Комментарий |
|------------------|-----|----------------|-------------|
| `<AL EventName>` | Triggering | `<BL EventName>` | `<что фиксирует>` |

### 5.5 Realization/Serving (Application Interface → Business Interface/Role)

| Application Interface | Тип | Business Interface/Role | Комментарий |
|----------------------|-----|------------------------|-------------|
| `<AL InterfaceName>` | Realization | `<BL InterfaceName>` | `<точка контакта>` |
| `<AL InterfaceName>` | Serving | `<BL RoleName>` | `<обслуживание роли>` |

### 5.6 Realization (Data Object → Business Object)

| Data Object | Тип | Business Object | Комментарий |
|-------------|-----|-----------------|-------------|
| `<DataObjectName>` | Realization | `<BusinessObjectName>` | `<данные объекта>` |

### Детализация ключевых связей

1. Application Service: `<ServiceAPI>` → Business Service: `<BusinessService>`
   **Тип:** Realization relation
   **Означает:** `<прикладной сервис реализует бизнес-сервис>`
   **Комментарий:** `<capabilities>`
```

---

## 2.6 Полные цепочки трассировки

```markdown
## 6. Цепочки трассировки (BL → AL → TL)

### Формат цепочки

| Бизнес-сценарий | Application Chain | Technology Chain |
|-----------------|-------------------|------------------|
| `<BL Process>` | `<AL Component>` → `<AL Component>` | `<TL Node>` → `<TL Service>` → `<TL Node>` |

### Цепочки для критических сценариев

| ID | Бизнес-сценарий | Application Chain | Technology Chain |
|----|-----------------|-------------------|------------------|
| 1 | `<Название процесса BL>` | `<Component1>` → `<Component2>` | `<Node>` → `<Service>` → `<DB>` |
| 2 | `<...>` | `<...>` | `<...>` |
```

---

## 2.7 Структура для диаграммы ArchiMate

```markdown
## 7. Рекомендованная структура диаграммы

**Слои (снизу вверх):**

Technology Layer
 ├─ `<Node1>`
 ├─ `<SystemSoftware1>`
 ├─ `<TechnologyService1>`
 └─ ...
     │
     ▼ (Serving / Realization)
Application Layer
 ├─ `<Component1>`
 ├─ `<Component2>`
 ├─ `<ApplicationService1>`
 └─ ...
     │
     ▼ (Serving / Realization)
Business Layer
 ├─ `<BusinessProcess1>`
 ├─ `<BusinessService1>`
 └─ ...

**Типы связей между слоями:**
- **TL → AL** — Serving, Realization, Assignment
- **AL → BL** — Serving, Realization, Triggering
```

---

## 2.8 Итоговая таблица связей

```markdown
## 8. Итоговая таблица связей

### По слоям

| Слой | Внутрислойных связей | Межслойных связей |
|------|---------------------|-------------------|
| Business Layer | `<N>` | — |
| Application Layer | `<N>` | `<N>` (→ BL) |
| Technology Layer | `<N>` | `<N>` (→ AL) |
| **ИТОГО** | `<N>` | `<N>` |

### По типам связей

| Тип связи | Количество | Слои |
|-----------|------------|------|
| Assignment | `<N>` | BL, AL, TL |
| Serving | `<N>` | BL, AL, TL, межслой |
| Realization | `<N>` | BL, AL, TL, межслой |
| Triggering | `<N>` | BL, AL, TL, межслой |
| Flow | `<N>` | BL, AL, TL |
| Access | `<N>` | BL, AL |
| Association | `<N>` | BL, TL |
| Aggregation | `<N>` | BL, AL, TL |
| Composition | `<N>` | BL, AL, TL |
```

---

## 2.9 Итоговая оценка

```markdown
## 9. Итоговая оценка

| Критерий | Оценка | Комментарий |
|----------|--------|-------------|
| Покрытие BL | `/10` | |
| Покрытие AL | `/10` | |
| Покрытие TL | `/10` | |
| Межслойные TL→AL | `/10` | |
| Межслойные AL→BL | `/10` | |
| Цепочки трассировки | `/10` | |
| Корректность типов | `/10` | |
| **OVERALL** | **X.X/10** | |

**Готовность:**
- [ ] >=8.0 — **READY FOR DIAGRAMS**
- [ ] 6.0-7.9 — Требуется доработка
- [ ] <6.0 — Существенная переработка
```

---

**Последнее обновление:** `<YYYY-MM-DD>`
