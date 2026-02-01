# Инструменты не кроссплатформенные: registry ссылается на bash-обёртки

**Type:** `type:bug`
**Priority:** `priority:P2`
**Severity:** `severity:S3`
**Status:** `status:needs-info`

## Контекст
- Компонент/сервис: `.tools/registry.json`, `.tools/*`
- Версия/коммит: <указать>
- Окружение: Windows (PowerShell), локальный запуск
- Частота: всегда
- Impact: агенты/пользователи на Windows не могут запускать `pdd-scan` и `plantuml-render` через registry

## Шаги воспроизведения
1. На Windows выполнить entry из `.tools/registry.json`:
   - `.tools/pdd/pdd-scan --format md`
   - `.tools/plantuml-render/plantuml-render --format png`
2. Команда не запускается без Git Bash/WSL

## Ожидаемое поведение
Инструменты запускаются из registry на Windows и *nix без ручной настройки shell.

## Фактическое поведение
Registry ссылается на bash-обёртки; `.bat` версии не используются.

## Логи/скриншоты
<если есть>

## Дополнительно
- Возможные варианты: добавить platform-specific entry, заменить entry на python-скрипт, сделать единый launcher
- Связанные задачи: <нет>
- Связанные PR: <нет>
