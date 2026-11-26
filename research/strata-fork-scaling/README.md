# Strata Snapshot/Fork Scaling

**E02-R завершён после двух дополнительных групп.** В основной проверке и двух дополнительных группах перенос дал 672/672 побайтовых совпадения при одинаковой форме исполнения. Обе дополнительные группы зафиксировали выход штатного batching за исходный эмпирический диапазон. [Результаты первичной проверки](reports/E02-R.md) · [Обе дополнительные группы](reports/E02-R-extension.md).

**Диагностический E03 на шести конфигурациях завершён.** Лучшее наблюдение — 1,248× при префиксе 4 096 и восьми ветках. [Времена и результаты сравнения](reports/E03-review-screen.md). После ревью зафиксирован upstream b28ca95, Strata 0.1.69. Каждая публикуемая конфигурация проходит собственное сравнение снимка с пересчётом. [Решение после ревью и границы эксперимента](reports/review-decision.md) · [Протокол E03](runs/E03/review-b28ca95/protocol.json) · [Предыдущий срез на 0.1.67](reports/E03-short.md).

Ниже сохранено решение первой итерации по прежнему G0.


**Решение первой итерации — BLOCKED на сравнении численной эквивалентности.** Стоимость исторических деревьев воспроизведена. Измерены штатное кеширование и выбор числа активных слотов на актуальном Inkling/Metal. Перенос состояния дал точные результаты при совпадающей форме GPU-вычислений. В одном сравнении с другим расписанием B3 превышен замороженный допуск. Ускорение относительно актуальной Strata, границы масштабирования и ёмкость остаются открытыми.

[Исторические измерения](reports/E00-reproduction.md) · [Актуальная Strata](reports/E01-baseline-audit.md) · [Допуск по корректности](reports/CORRECTNESS.md) · [Состояние E03 и следующий эксперимент](reports/E03-scaling.md) · [Протокол](PROTOCOL.md)

## Исходники и окружение

Родительский каталог turbine-intelligence содержит исследовательские материалы. Вложенный репозиторий Strata имеет первоначальную ветку research/adaptive-intelligence с исходными четырьмя незакоммиченными файлами. Их копия зафиксирована отдельно в локальной ветке research/strata-fork-scaling, коммит ae7d99e. Исследовательский порт на актуальную Strata хранится в research/strata-fork-scaling-metal, коммит fd243cf. Публикация веток не выполнялась. Полные SHA, флаги, пути и контрольные суммы содержатся в [инвентаризации](archive/inventory.json).

Команды ниже выполняются из turbine-intelligence. Требуются доступ к Apple Metal, установленная локально модель и токенизатор, Apple Clang, CMake и Python с numpy. Для исторического измерителя нужен также tokenizers. Для графика нужен matplotlib. Новые имена каталогов вывода обязательны там, где измеритель сам защищает прежние результаты. Их можно размещать в .work.

## Воспроизведение

Уже собраны два современных бинарника в .work/strata-scaling, а исторический бинарник сохранён в .work/strata-build. Чтобы пересобрать только целевые бинарники из локальных worktree:

```sh
w=.work/strata-scaling
cmake -S "$w/upstream/engine/src/inkling2" -B "$w/b3-build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$w/b3-build" --target strata-inkling --parallel 4
cmake -S "$w/instrumented/engine/src/inkling2" -B "$w/lab-build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$w/lab-build" --target strata-inkling --parallel 4
```

Если worktree переносятся на другую машину, восстановить upstream из 2af30cc и применить archive/scaling.patch только в копии для портированной сборки. Исторический исходник восстанавливается из 26350e4 с archive/historical.patch. Сверить хеши бинарников, входных данных и компилятора с инвентаризацией до содержательного сравнения. Для точного повторения E00 сохранить зафиксированный исторический бинарник.

```sh
lab=research/strata-fork-scaling
out=.work/scaling-repeat
python3 -B research/adaptive-intelligence/branching/live_gate.py "$out/old-state"
python3 -B "$lab/tools/reproduce.py" "$out/e00"
python3 -B "$lab/tools/native_smoke.py" "$out/native"
python3 -B "$lab/tools/baseline_dev.py" "$out/development"
python3 -B "$lab/tools/gates.py" "$out/state"
```

Последняя команда возвращает ненулевой код при нарушении G0. У независимых диагностик есть отдельные точки входа:

```sh
python3 -B "$lab/tools/shape_diagnostic.py" "$out/matched-shape"
python3 -B "$lab/tools/slot_lifetime.py" "$out/cancel"
python3 -B "$lab/tools/screen.py" "$out/instrumentation" --overhead-only
```

Скрининг принимает каталог результатов и JSON с вердиктом проверки. На сохранённом отрицательном вердикте он завершает работу до запуска модели. Плановые клетки перечислены в [машиночитаемом статусе](runs/E03/status.json). Полная регрессия, живые агентские задачи и SSD-offload в эту итерацию не входили.

## Как воспроизвести E02-R

Наблюдатель расположен в локальной исследовательской ветке research/strata-fork-e02r, коммит 13f9005 поверх fd243cf. Дополнительный патч находится в archive/e02r-observer.patch. Он добавляет выдачу логитов на выбранных шагах и одновременную подачу двух адресных запросов. Ветвление и Metal-ядра взяты из предыдущей исследовательской сборки.

На том же Mac из корня turbine-intelligence этот запуск создаёт отдельную копию результатов. Калибровка и проверка используют один GPU последовательно. Полные численные векторы хранятся отдельно от небольших JSON-файлов с метриками.

```sh
w=.work/strata-scaling
cmake -S "$w/e02r-src/engine/src/inkling2" -B "$w/e02r-build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$w/e02r-build" --target strata-inkling --parallel 4
python3 -B research/strata-fork-scaling/tools/replay_e02r.py .work/e02r-repeat .work/e02r-repeat-logits
```
