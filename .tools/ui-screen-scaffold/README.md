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

## Каталог размеров viewport

Точные CSS-размеры и привязки оболочек хранятся в `.tools/ui-screen-scaffold/catalog/viewport-profiles.json` и `.tools/ui-screen-scaffold/shells/shell-library.json`. Размеры физической панели, CSS viewport приложения и платформенные единицы `dp` являются разными величинами.

- [CSS Values and Units](https://www.w3.org/TR/css-values-4/) определяет единицу CSS `px`, а [CSSOM View](https://www.w3.org/TR/cssom-view-1/) — браузерные API для чтения viewport. Эти стандарты не задают типовые размеры экранов устройств.
- [DeviceAtlas](https://deviceatlas.com/blog/viewport-resolution-diagonal-screen-size-and-dpi-most-popular-smartphones) и [ScreenSize.net Viewport Reality Report](https://screensize.net/reports/viewport-stats) дают эмпирические наблюдения своих выборок, а не глобальную долю рынка. Для переноса размеров в каталог указаны дата получения и ограничения выборки. Перестановка ширины и высоты для второй ориентации является тестовым preset, если источник отдельно не измерил такую пару.
- Samsung Tizen и LG webOS публикуют рекомендации по графическому разрешению приложения. Для нового подтверждённого профиля проверяйте `window.innerWidth` и `window.innerHeight` в целевом runtime. Android TV guidance задаёт координаты нативного интерфейса в `dp`; не преобразуйте `960×540 dp` в CSS px без измерения WebView.
- Для неизмеренных TV runtime и браузерного CSS viewport на панелях 4K/8K каталог содержит `status: gap` и процедуру получения данных. GAP не имеет shell и не может быть выбран как подтверждённая оболочка. После измерения запишите модель/runtime, версию, `window.innerWidth`, `window.innerHeight` и релевантные screen API, добавьте источник и только затем создавайте shell.
- `1920×1080 CSS px` — выбранный разработчиком эталон desktop-проверки; он сосуществует с наблюдаемыми desktop-размерами в каталоге и не описывается как требование стандарта.

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
