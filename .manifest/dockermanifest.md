# Docker Manifest (H2)

Политики и стандарты работы с Docker: конфигурация dev/prod окружений, сборка образов, безопасность и оптимизация.

---

## docker.H3.1 Разделяй dev и prod окружения
Dev и prod имеют разные приоритеты и не должны смешиваться в одной конфигурации.
**Почему важно:**
Dev оптимизируется под скорость итераций, prod - под стабильность и безопасность. Попытка покрыть оба режима одной конфигурацией ведет к компромиссам.

---

## docker.H4.1 Структура compose-файлов
Используй схему base + override:
- `docker-compose.base.yml` - общие сервисы и сети (ядро)
- `docker-compose.dev.yml` - dev-override (mounts, debug, ports, watch)
- `docker-compose.prod.yml` - prod-override (минимум портов, без mounts, усиленная безопасность)
- `docker-compose.test.yml` - тестовое окружение (изолированное, быстрое)
**Правило:** base описывает "что это за сервисы", override описывает "как именно мы их запускаем в данном режиме".
**Используй profiles для опциональных сервисов:**
`monitoring`, `devtools`, `ml`, `debug`, `ci`

---

## docker.H3.2 Оптимизируй dev workflow без rebuild
В dev изменение кода не должно требовать пересборки образа.
**Почему важно:**
Ожидание rebuild на каждое изменение убивает продуктивность. Правильный dev workflow - изменил код, увидел результат через секунду.

---

## docker.H4.2 Dev workflow: bind mounts и hot reload
**В dev используй:**
- Bind mounts для монтирования исходников
- Watch/reload инструменты (nodemon, cargo-watch, uvicorn --reload)
- Rebuild только при изменении зависимостей или базового окружения
**Dev-итерации НЕ должны зависеть от COPY исходников в Dockerfile**
Основной путь разработки - bind mount.
**Типичный день разработки:**
- Утро: `make dev` (один раз)
- День: редактирование кода (hot reload, без docker команд)
- Добавил dependency: `make rebuild`
- Вечер: `make down`
**Антипаттерн:** Если набираешь `docker build` чаще раза в час - dev workflow организован неправильно.

---

## docker.H3.3 Обеспечь воспроизводимость и кросс-платформенность
Сборки должны быть идентичны на любой машине и платформе.
**Почему важно:**
Невоспроизводимые сборки ведут к "works on my machine", расхождениям между dev/prod, сложности отладки.

---

## docker.H4.3 Правила воспроизводимости
**Фиксируй версии:**
- Lock-файлы зависимостей (package-lock.json, Cargo.lock, poetry.lock)
- Базовые образы с конкретным tag (не :latest), желательно digest
- Конфигурация из env/файлов, не "магия в контейнере"
**Кросс-платформенность:**
- Конфигурация работает на Linux, macOS, Windows без правок
- `.gitattributes` нормализует line endings: `* text=auto eol=lf`
- Пути с `/` в Dockerfile/compose/scripts
- Для bind mounts на macOS/Windows допускается `:cached` если поддерживается и даёт прирост

---

## docker.H4.4 Multi-stage Dockerfile
Используй один multi-stage Dockerfile с минимум тремя стадиями:
**Стадии:**
- `dev` - инструменты разработки (watch/reload/отладка), без зависимости от COPY исходников для итераций
- `builder` - сборка/компиляция/установка зависимостей
- `runtime` - минимальный запуск (prod)
**Запрещено:**
- Создавать отдельные `Dockerfile.dev` и `Dockerfile.prod`
- Использовать `:latest` для базовых образов
- Копировать `.env` или secrets в образ
- Устанавливать избыточные системные пакеты
- Делать dev-итерации зависимыми от `COPY . .`

---

## docker.H4.5 Оптимизация кэширования слоев
**Порядок инструкций:**
1. Копируй файлы зависимостей (`package-lock.json`, `Cargo.lock`, `requirements.txt`, `pyproject.toml`)
2. Ставь зависимости
3. Копируй исходники (только где требуется для build/runtime)
4. Собирай
**Цель:** Изменение одного файла в `src/` не должно инвалидировать слой зависимостей.
**Используй BuildKit cache mounts:**
```dockerfile
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt
RUN --mount=type=cache,target=/usr/local/cargo/registry cargo build --release
RUN --mount=type=cache,target=/root/.npm npm ci
```

---

## docker.H4.6 Обязательные файлы проекта
Проект должен содержать:
- `.gitattributes` - нормализация line endings (`* text=auto eol=lf`)
- `.gitignore` - содержит `.env`, но НЕ `.env.example`
- `.env.example` - в git, идентичен по структуре `.env`
- `.dockerignore` - рядом с каждым Dockerfile
- `Makefile` или task runner - стандартизированные команды
**Содержимое `.dockerignore`:**
```
node_modules
target
.git
.env
*.log
build/
dist/
```

---

## docker.H3.4 Защищай секреты и credentials
Секреты не должны попадать в образы, репозиторий или command line контейнера.
**Почему важно:**
Секреты в образе/git доступны всем с доступом к registry/репозиторию. Утечка ведет к компрометации систем.

---

## docker.H4.7 Управление секретами
**Используй 12-factor подход:**
- Конфигурация только через env / конфиг-файлы
- Один образ запускается в разных окружениях с разной конфигурацией
**Запрещено:**
- Хранить секреты в репозитории
- Передавать секреты в командной строке контейнера (видно в `inspect`)
- Копировать `.env` в образ
**В prod предпочтительно:**
- File-based secrets (Docker secrets / volume-mounted secret files)
- Минимум: `.env` вне git + строгие права доступа
**Единый контракт переменных:**
Имена env-переменных одинаковые в dev/prod/test. Меняй значения, не ключи.

---

## docker.H3.5 Минимизируй attack surface в prod
Production не должен раскрывать внутренние сервисы и работать под root.
**Почему важно:**
Открытые порты БД, работа под root, избыточные пакеты - всё это увеличивает риск компрометации.

---

## docker.H4.8 Конфигурация портов и сетей
**Публикация портов:**
- В dev: публикуй порты наружу для удобства
- В prod: публикуй только необходимое (обычно reverse-proxy)
- Базы/очереди/мониторинг в prod НЕ открывай наружу без строгой необходимости
**Разделяй сети:**
- `public` - входящий трафик
- `internal` - межсервисное взаимодействие
- Для внутренних сервисов достаточно `expose`, не `ports`
**Runtime безопасность:**
- В prod контейнере работай не под root
- Файлы с ключами/сертификатами - минимальные права и предсказуемая доставка

---

## docker.H4.9 Volumes и bind mounts
**Разделяй данные и кэш:**
- Данные БД/хранилищ - устойчивые volumes
- Build/SDK кэши (cargo/pip/node) - отдельно
**Dependencies в dev - named volumes:**
- Dependencies (`node_modules`, `target`, `venv`) - named volumes (переживают `docker compose down`, ускоряют dev)
- Исходный код - bind mount
- На macOS/Windows допускается `:cached` если поддерживается
**Запрещено:**
- Монтировать dependencies как bind mount (медленно, ломает права/платформенность)
**Read-only mounts:**
Если файл монтируется read-only, контейнер не должен пытаться менять его права. Если нужны права - копируй внутрь в writable путь на старте.

---

## docker.H3.6 Обеспечь observability через healthchecks и логи
Критичные зависимости должны сообщать о готовности, логи должны быть централизованы.
**Почему важно:**
Без healthcheck сервисы начинают принимать трафик до готовности. Без централизованных логов невозможна отладка в prod.

---

## docker.H4.10 Healthchecks и готовность зависимостей
**Добавляй healthcheck для:**
- БД, очередей, кэшей, vector store, секрет-хранилищ
**Жди готовности зависимостей:**
Используй `healthcheck` + ожидание, либо `wait-for-it`, `dockerize`, встроенный retry/backoff в приложении.
**Пример healthcheck:**
```yaml
healthcheck:
  test: ["CMD", "pg_isready", "-U", "postgres"]
  interval: 5s
  timeout: 3s
  retries: 5
```

---

## docker.H4.11 Лимиты ресурсов и логирование
**Лимиты ресурсов:**
- В dev - мягкие лимиты (не мешают отладке)
- В prod - строгие лимиты CPU/Memory, рестарты, политики логов (ротация)
**Логирование:**
- Логи в stdout/stderr, НЕ в файлы внутри контейнера
- В prod - драйвер логов/агент/централизация (ELK/Loki/Vector/Fluent Bit)
**Мониторинг:**
- Подключается профилем/override-файлом
- В prod доступ защищен (VPN/Auth/ACL), не открыт наружу "как есть"

---

## docker.H4.12 Стандартные команды разработки
Создай единые команды (Makefile/Taskfile/npm scripts):
```makefile
make dev      # Поднять dev окружение
make prod     # Поднять prod конфигурацию
make test     # Тестовая инфраструктура + тесты
make logs     # Смотреть логи
make ps       # Статус
make down     # Выключить окружение
make rebuild  # Пересобрать при изменении зависимостей
make clean    # Очистка docker-мусора
```
**Точечные команды для одного сервиса:**
- build one
- restart one
- run shell inside

---

## docker.H4.13 Команды очистки мусора
**Типы очистки:**
- Легкая очистка (dangling images): ежедневно/по необходимости
- Очистка билд-кэша: когда заметно разросся
- Полная очистка: после экспериментов/веток/CI-гонок
- Очистка конкретного проекта: `down + remove-orphans + rmi local`
**Пример команд:**
```bash
docker image prune -f                    # dangling images
docker builder prune -f                  # build cache
docker system prune -a --volumes -f      # полная (осторожно!)
```

---

## docker.H4.14 Правила для агента
**При создании новой Docker конфигурации:**
- Создай один multi-stage Dockerfile (минимум: builder, runtime, опционально dev)
- Убедись что dev workflow не зависит от `COPY . .` (основной путь - bind mounts)
- Создай `.dockerignore` (исключить: node_modules, target, .git, .env, build artifacts)
- Создай `.gitattributes` с `* text=auto eol=lf`
- Настрой bind mounts в `docker-compose.dev.yml` для исходников
- Настрой dependencies как named volumes (НЕ bind mount)
- Используй `${VAR}` для всех значений в compose
- Создай `.env.example` со всеми переменными
**При проверке существующей конфигурации:**
- [ ] Multi-stage build в Dockerfile
- [ ] Dev workflow без обязательного `COPY . .` (bind mounts + watch/reload)
- [ ] Bind mounts для source code в docker-compose.dev.yml
- [ ] `.dockerignore`
- [ ] `.gitattributes`
- [ ] `${VAR}` вместо хардкода в compose
- [ ] BuildKit cache mounts где применимо
- [ ] Правильный порядок слоев (deps → install → code)
**При изменении конфигурации:**
- НЕ создавай отдельные Dockerfile.dev и Dockerfile.prod - один Dockerfile с multi-stage
- НЕ используй хардкод в docker-compose (только `${VAR}`)
- НЕ монтируй dependencies как bind mount (только named volumes)
- Сохраняй порядок инструкций для оптимизации кэша
- Используй YAML anchors для устранения дублирования
**Исправляй частые ошибки:**
- Dev-итерации требуют rebuild → проверь bind mounts и watch/reload, убери зависимость от `COPY . .`
- Хардкод в docker-compose → замени на `${VAR}`
- Отсутствует .dockerignore → создай
- `:latest` в базовом образе → укажи версию/digest
- Отсутствует .gitattributes → создай
- Дублирующиеся блоки в compose → используй YAML anchors
- Dependencies в bind mount → замени на named volumes

---

## docker.H4.15 Диагностические вопросы и чеклисты
**Если требуется пересборка при изменении кода:**
- Есть ли bind mount исходников в docker-compose.dev.yml?
- Есть ли watch/reload?
- Dev workflow не завязан на `COPY . .`?
**Если медленная работа на macOS/Windows:**
- Используется ли `:cached` (если поддерживается)?
- Dependencies не монтируются bind mount?
- Нет ли лишних файлов в bind mount (проверь .dockerignore)?
**Если dependencies устанавливаются каждый раз:**
- Правильный ли порядок в Dockerfile? → COPY deps → RUN install → COPY code
- Используются ли named volumes / BuildKit cache mounts?
**Если shell-скрипты не работают:**
- Есть ли .gitattributes с `eol=lf`?
**Dev must-have:**
- [ ] Bind mounts для исходников
- [ ] Watch/reload без rebuild
- [ ] Кэш зависимостей через named volumes или BuildKit cache mounts
- [ ] Быстрые команды (make/task scripts)
- [ ] `.gitattributes` с `* text=auto eol=lf`
- [ ] `:cached` для bind mounts на macOS/Windows если поддерживается и даёт прирост
**Prod must-have:**
- [ ] Multi-stage Dockerfile (builder + runtime)
- [ ] Секреты не в командной строке и не в git
- [ ] Закрытые внутренние порты
- [ ] Healthchecks/ожидание готовности
- [ ] Лимиты ресурсов и политика рестарта
**Hygiene must-have:**
- [ ] Команды очистки docker-мусора в проекте
- [ ] Отсутствие `container_name` для масштабирования/параллельных окружений
- [ ] Единый контракт env для всех окружений
- [ ] `.dockerignore` рядом с каждым Dockerfile
