# Справочник портов

<!--
> **Важно:** этот файл в `.requirements/**` — **шаблон/методика** (read-only).  
> **Фактический справочник портов (source of truth) ведётся в:** `docs/requirements/справочник портов.md`.  
> Состав сервисов и используемых инструментов/технологий берётся из: `docs/requirements/структура ПО/стек проекта.md`. -->

---

## 0. Контекст
- **Проект / продукт:** `<PROJECT_NAME>`
- **Среда:** `<dev | staging | prod>`
- **Источник конфигурации:** `<docker-compose.yml | helm chart | terraform | ansible | ...>`
- **Дата обновления:** `<YYYY-MM-DD>`
- **Ответственный:** `<team/person>`
- **Как проверять актуальность:** `<команда/скрипт, например: docker compose config | rg "ports:|expose:">`

---

## 1. Правила и обозначения

### 1.1 Формат записи
- `hostPort:containerPort/proto` — проброс порта в контейнер (Compose)
- `hostPort/proto` — сервис слушает host напрямую (без контейнера)
- `нет внешнего порта` — сервис доступен только внутри сети (Compose/K8s)
- `public` — доступен извне (интернет/корп сеть)
- `internal` — доступен только внутри VPC/overlay сети/локальной машины

### 1.2 Обязательные поля для каждого порта
Для каждой записи фиксируй:
- протокол (`tcp/udp`)
- `hostPort`
- `containerPort` (если есть контейнер)
- `host bind` (если есть, например `127.0.0.1`)
- доступность (`public/internal`)
- назначение (Purpose)
- владелец (Owner)
- примечания (TLS termination / auth / ограничения)

Если порта нет (internal-only), пиши: `нет внешнего порта`.

### 1.3 Условные метки
- **TL (Technology Layer)** — инфраструктурные компоненты (DB, broker, proxy)
- **AL (Application Layer)** — прикладные сервисы
- **OBS (Observability)** — мониторинг/трейсинг/логи
- **SEC (Security)** — IAM, Vault, PKI, gateways

---

## 2. Сводная таблица портов (рекомендуется заполнять первой)

| Layer | Service | Host bind | Mapping (host:container) | Proto | Public? | Purpose | Owner | Notes |
|---|---|---|---|---|---|---|---|---|
| TL | `<postgres>` | `<0.0.0.0/127.0.0.1>` | `<5432:5432>` | tcp | internal | SQL | `<team>` | `<...>` |
| AL | `<api-gateway>` | `<0.0.0.0>` | `<4000:3000>` | tcp | public | Public API | `<team>` | `<...>` |
| OBS | `<prometheus>` | `<127.0.0.1>` | `<9090:9090>` | tcp | internal | Metrics | `<team>` | `<...>` |

> Подсказка агентам: если таблица заполнена, ниже можно генерировать разделы автоматически.

---

## 3. Технологический уровень (TL)

### `<Service Name 1>` (`<tech/version>`)
- **Service ID (compose/k8s):** `<service-name>`
- **Назначение:** `<what it is for>`
- **Сеть/доступ:** `<public/internal + network name>`
- **Порты:**
  - `<hostPort>:<containerPort>/<proto>` — `<description>` (access: `<public/internal>`)
  - `<hostPort>:<containerPort>/<proto>` — `<description>`
- **Health/metrics (если есть):** `<port/path>`
- **Примечания:** `<tls termination / auth / bind addr / rate limits>`

### `<Service Name 2>` (`<tech/version>`)
- ...

---

## 4. Слой приложений (AL)

### `<Service Name>` (`<lang/stack>`)
- **Service ID:** `<service-name>`
- **Роль:** `<domain responsibility>`
- **Base URL (если есть):** `http(s)://<host>:<port>`
- **Порты:**
  - `<hostPort>:<containerPort>/<proto>` — `<endpoint purpose>` (`public/internal`)
- **Внутренние порты (без проброса):**
  - `<containerPort>/<proto>` — `<used внутри overlay сети>`
- **Транспорт:** `<HTTP/GRPC/WebSocket/SSE/MQTT/etc>`
- **Auth:** `<none/jwt/mTLS/api-key>`
- **Примечания:** `<timeouts/retries/idempotency/circuit breaker etc>`

### `<Worker / background service>`
- **Service ID:** `<worker-name>`
- **Порты:** `нет внешнего порта`
- **Каналы/очереди:** `<queue/topic names>`
- **Примечания:** `<конкурентность/ретраи/DLQ>`

---

## 5. Безопасность (SEC) (опционально)

### `<Auth/IAM/Vault/PKI/Ingress>`
- **Service ID:** `<service-name>`
- **Порты:**
  - `<hostPort>:<containerPort>/<proto>` — `<purpose>` (`public/internal`)
- **TLS:** `<where terminated, cert rotation>`
- **Примечания:** `<RBAC/allowlist>`

---

## 6. Обсервабельность (OBS)

### `<Prometheus / Grafana / Jaeger / Loki / OTel Collector>`
- **Service ID:** `<service-name>`
- **Порты:**
  - `<hostPort>:<containerPort>/<proto>` — `<purpose>` (`public/internal`)
  - `<hostPort>:<containerPort>/<proto>` — `<purpose>`
- **UI логины (если допустимо):** `<default creds or ссылку на secrets>`
- **Примечания:** `<scrape endpoints / exporters / retention>`

---

## 7. Внутренние DNS-имена и адреса (Compose/K8s)
> Важно для агентов: как обращаться к сервисам изнутри сети.

- **Compose service DNS:** `http://<service-name>:<containerPort>`
- **K8s service DNS:** `http://<service>.<namespace>.svc.cluster.local:<port>`
- **Примеры:**
  - `<service-a>:<port>` — `<use case>`
  - `<service-b>:<port>` — `<use case>`

---

## 8. Политика портов (Port Policy)

### 8.1 Резервирование диапазонов (пример)
- `3000–3999` — UI/панели (внутренние, по возможности bind `127.0.0.1`)
- `4000–4999` — публичные API gateway / edge
- `5000–5999` — внутренние API сервисов
- `9000–9999` — observability
- `5432/6379/27017/...` — стандартные порты баз/брокеров (лучше не менять без нужды)

### 8.2 Принципы безопасности
- UI наблюдаемости по умолчанию: **internal-only** (`127.0.0.1`/VPN/ingress auth)
- DB/broker наружу: **запрещено** без явной причины
- TLS: фиксировать “где завершается” и “кто выдаёт сертификаты”

### 8.3 Типовые конфликты и решение
- **Conflict:** порт занят локально → `<решение: изменить hostPort / остановить сервис / использовать profile>`
- **Conflict:** несколько окружений на одной машине → `<решение: prefix ports / compose project name>`

---

## 9. Чек-лист актуализации
- [ ] Сверить с `docker-compose.yml` / helm values
- [ ] Проверить фактические слушающие порты: `docker ps` / `ss -lntup`
- [ ] Обновить сводную таблицу и разделы
- [ ] Указать изменения в CHANGELOG/ADR (если менялись публичные порты)

---

## Примеры (H7)

**Считать верным:**
- Для каждого сервиса указаны внешние и внутренние порты с протоколами и назначением.
- Отдельно зафиксированы точки доступа observability и политики безопасности портов.

**Считать неверным:**
- Указаны только порты, без протоколов и назначения.
- Порты дублируются между сервисами без политики конфликтов.

---

## Критерии готовности

- [ ] Все сервисы и их порты перечислены и соответствуют факту
- [ ] Указаны протоколы, назначения и уровень доступа (public/internal)
- [ ] Есть политика портов и описаны типовые конфликты
