# DDD Patterns — паттерны Domain-Driven Design

Набор паттернов для моделирования предметной области: Entity, Value Object, Aggregate, Repository, Domain Service.

## Назначение

DDD Patterns используются на этапах [4], [5.3] для:
- Классификации объектов домена
- Определения границ агрегатов
- Проектирования структуры данных
- Выбора паттернов хранения

## Глоссарий

| Термин | Определение |
|--------|-------------|
| Entity | Объект с уникальной идентичностью, изменяемый во времени |
| Value Object | Объект без идентичности, определяемый атрибутами, иммутабельный |
| Aggregate | Кластер Entity и Value Objects с корневым Entity |
| Aggregate Root | Корневая сущность агрегата, единственная точка доступа |
| Repository | Абстракция доступа к коллекции агрегатов |
| Domain Service | Операция домена, не принадлежащая конкретной сущности |
| Factory | Создание сложных агрегатов |
| Domain Event | Уведомление о значимом изменении в домене |

## Процедура (императив для агента)

### Шаг 1: Идентификация сущностей
1. Прочитай результаты этапа [1] (глоссарий, use cases).
2. Для каждого термина домена определи:
   - Это Entity? (имеет уникальный ID, изменяется)
   - Это Value Object? (определяется значениями, иммутабельный)
3. Запиши классификацию в таблицу.

### Шаг 2: Группировка в агрегаты
1. Определи, какие сущности всегда изменяются вместе.
2. Выбери корневую сущность (Aggregate Root).
3. Правило: внешний код обращается только к Aggregate Root.
4. Запиши агрегаты в `docs/requirements/домены/реестр.md`.

### Шаг 3: Определение репозиториев
1. Для каждого агрегата определи Repository.
2. Назови: `<AggregateRoot>Repository`.
3. Определи базовые методы: `save`, `findById`, `findBy*`, `delete`.

### Шаг 4: Выявление доменных сервисов
1. Найди операции, не принадлежащие одной сущности.
2. Оформи как Domain Service.
3. Примеры: `PricingService`, `TransferService`.

### Шаг 5: Проектирование структуры данных
1. Для каждого агрегата определи таблицы/документы.
2. Entity -> отдельная таблица с ID.
3. Value Object -> встроен в Entity или отдельная таблица.
4. Запиши в `docs/requirements/структура Данных/`.

## Артефакты

| Артефакт | Расположение | Содержимое |
|----------|--------------|------------|
| Реестр доменов | `docs/requirements/домены/реестр.md` | Домены, агрегаты, границы |
| Карточки доменов | `docs/requirements/домены/<domain>.md` | Entity, VO, Repository |
| Структура данных | `docs/requirements/структура Данных/` | Таблицы, индексы |

## Критерии готовности

- [ ] Все сущности классифицированы (Entity/Value Object)
- [ ] Агрегаты определены с Aggregate Root
- [ ] Границы агрегатов обоснованы
- [ ] Repository определены для каждого агрегата
- [ ] Domain Services выделены (если есть)
- [ ] Структура данных соответствует агрегатам

## Примеры классификации

```
Домен: Заказы

Aggregate: Order (Aggregate Root)
  - Entity: Order (id, status, createdAt)
  - Entity: OrderItem (id, quantity, price)
  - Value Object: Money (amount, currency)
  - Value Object: Address (street, city, zip)

Repository: OrderRepository
  - save(order)
  - findById(orderId)
  - findByCustomer(customerId)
  - findByStatus(status)

Domain Service: PricingService
  - calculateTotal(order, discounts)
```

## Ссылки

* Назад к разделу: `../README.md`
* Этап [4]: `.requirements/домены/определение доменов.md`
* Связанный шаблон: `.requirements/структура Данных/описание БД.md`
* Event Storming: `.approach/event-storming.md`
