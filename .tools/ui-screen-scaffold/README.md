# ui-screen-scaffold — генератор макетов пользовательского интерфейса

> Версия инструмента: `0.1.0`.

Генератор создаёт автономные страницы HTML/CSS для явно выбранных записей `screen-manifest.json`, используя оболочки и точные размеры из установленного SDD Framework. Он не выбирает экраны, оболочки, паттерны или шаблоны вместо разработчика и не заполняет продуктовый интерфейс.

## Быстрый старт

Сначала заполни `screen-manifest.json` для выбранного набора эталонных материалов (reference-set), включая `screen_id`, роль, состояние, viewport, точную `shell_binding` и выходной путь. Затем проверь план без записи:

```text
python .tools/ui-screen-scaffold/ui_screen_scaffold.py generate --package docs/requirements/пользовательский-интерфейс --reference-set <reference-set-id>
```

Для создания файлов повтори команду с `--write`:

```text
python .tools/ui-screen-scaffold/ui_screen_scaffold.py generate --package docs/requirements/пользовательский-интерфейс --reference-set <reference-set-id> --write
```

В Windows доступна оболочка запуска:

```text
.tools/ui-screen-scaffold/ui-screen-scaffold.bat generate --package docs/requirements/пользовательский-интерфейс --reference-set <reference-set-id> --write
```

## Входы и выходы

Входы:

- UI manifest, экранный пул и указанный `reference-set` версии контракта `2`;
- записи `artifacts[]` в `screen-manifest.json` с точным экраном, ролью, состоянием, CSS viewport и оболочкой;
- установленная библиотека оболочек `.tools/ui-screen-scaffold/shells/shell-library.json` и `release-manifest.json` Framework.

Выходы для каждого выбранного экрана и viewport:

```text
references/<reference-set-id>/screens/<screen-id>/<viewport-id>/
├── index.html
├── shell.css
├── reference-manifest.json
└── README.md
```

Каждый `index.html` можно открыть отдельно в браузере. Страница показывает только экран: холст начинается в точке `(0, 0)`, а его размер совпадает с CSS viewport; заголовок и поля каталожного предпросмотра скрыты. Сохраняется нейтральный слот `screen-content`, рамки устройства нет. Метаданные остаются в `reference-manifest.json` и `README.md`. Агент заполняет слот содержимым по спецификации экрана и только явно выбранными ссылками на UI-паттерны/шаблоны. Продуктовые тексты и поведение генератор не создаёт.

## Проверки и безопасность

- Без `--write` инструмент только проверяет и печатает план.
- С `--write` создаются только новые файлы; если любой целевой файл существует, вся запись отменяется до первого изменения.
- Пути ограничены каталогом выбранного reference-set; абсолютные пути, `..` и выход через символьные ссылки отклоняются.
- Для `track-integrated` допустимы только подтверждённые экран, viewport и выбранная оболочка. `early-prototype` сохраняет предварительный статус.
- `gap` и `not_applicable` не порождают ложную оболочку; они возвращаются в списке `gaps`.
- Каталог оболочек сверяется с точным `source_commit` Framework. Происхождение `ui-patterns` проверяется отдельно по UI manifest.

После генерации выполни проверку всего пакета:

```text
python .tools/ui-reference/ui_reference.py validate --package docs/requirements/пользовательский-интерфейс
```

У инструмента нет внешних зависимостей; требуется Python 3.10 или новее. Тесты исходного репозитория:

```text
python -B -m unittest discover -s .tools/ui-screen-scaffold/tests -v
```

## Ссылки

- [Библиотека оболочек и viewport](shells/)
- [Контракт UI-пакета](../../.requirements/пользовательский-интерфейс/README.md)
- [Манифест UI](../../.manifest/uimanifest.md)
