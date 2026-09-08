# .tasks — задачи проекта

В каталоге хранятся задачи проекта и реестр отметок `@todo`.

```text
.tasks/
  <TASK-ID>.md
  done/
  pdd/
    @todoregistry.md
```

Выполненные задачи перемещаются в `.tasks/done/`. Реестр
`.tasks/pdd/@todoregistry.md` обновляется инструментом PDD.

Полные правила находятся в `.agents/sdd-template-X.Y.Z/.manifest/taskmanifest.md`
и `.agents/sdd-template-X.Y.Z/.manifest/pddmanifest.md`.
