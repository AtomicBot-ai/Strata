# Архив исследований Atomic Turbine

Срез от 26 ноября 2026 года на базе продуктовой main `df258bf4`. Ветка хранит результаты экспериментов, в том числе отложенные и не прошедшие пороги интеграции. Коммиты движков доступны в ветках ниже.

| Материалы | Что смотреть |
|---|---|
| [Adaptive Intelligence](adaptive-intelligence/) | Протокол, пилоты, промежуточные результаты и измерения SSD |
| [Strata Fork Scaling](strata-fork-scaling/) | E00–E03, метрики, наблюдатели и сырые прогоны |
| [Final Sprint](final-sprint/REPORT.md) | Сценарии Inkling, Qwen и OpenCode, контрольные результаты |
| [Affinity PoC](affinity-poc/REPORT.md) | A01/A02, проверка порядка обработки и кеша экспертов |
| [Fast Sprint](fast-sprint/REPORT.md) | Политики спекулятивной генерации, код воспроизведения и результаты |
| [Spec Policy](spec-policy-fast/REPORT.md) | Стоимость шага, диагностические варианты и токены |
| [ForkSpec](forkspec/REPORT.md) | Проверки restore и rollback, кандидат и наблюдатели |

[Пакеты для ревью и PDF](../output/) · [Сборки Mac с контрольными суммами](../dist/) · [Дополнительные стендовые логи и инструменты](support/) · [SHA-256 архивных файлов](ARCHIVE-SHA256.json)

Большой исходный архив `E02-R-logits.zip` оставлен на локальном диске по решению владельца. Размер 1 600 509 222 байта, SHA-256 `9685f8ff35d2c129652a685e37f947ea8bb30fb423d9606f93a20f899ffc9b7d`. Сводные результаты и малый архив для ревью находятся в [E02-review](../output/E02-review-20261125-223649/).

Воспроизведение может потребовать весов и внешних наборов данных, указанных в соответствующем протоколе. Временные копии сборок, окружения и кеши загрузок остаются локальными.

## Экспериментальные исходники

- [research/strata-fork-scaling](https://github.com/AtomicBot-ai/Strata/tree/research/strata-fork-scaling) · `ae7d99efe9`
- [research/strata-fork-scaling-metal](https://github.com/AtomicBot-ai/Strata/tree/research/strata-fork-scaling-metal) · `fd243cfe43`
- [research/strata-fork-e02r](https://github.com/AtomicBot-ai/Strata/tree/research/strata-fork-e02r) · `13f9005851`
- [research/affinity-poc](https://github.com/AtomicBot-ai/Strata/tree/research/affinity-poc) · `b4e7e92014`
- [research/ssd-expert-trace](https://github.com/AtomicBot-ai/Strata/tree/research/ssd-expert-trace) · `0cb4cfe970`
- [research/fast-sprint](https://github.com/AtomicBot-ai/Strata/tree/research/fast-sprint) · `3121b6ed0a`
- [research/spec-policy-fast](https://github.com/AtomicBot-ai/Strata/tree/research/spec-policy-fast) · `863b3c2cb9`
- [research/spec-policy-existing-probes](https://github.com/AtomicBot-ai/Strata/tree/research/spec-policy-existing-probes) · `d50cd7f88c`
- [research/forkspec](https://github.com/AtomicBot-ai/Strata/tree/research/forkspec) · `8f0ee1eec8`
- [research/forkspec-observer](https://github.com/AtomicBot-ai/Strata/tree/research/forkspec-observer) · `9c83ec7530`
- [research/forkspec-adaptive-observer](https://github.com/AtomicBot-ai/Strata/tree/research/forkspec-adaptive-observer) · `cc33609e04`
- [research/forkspec-factor](https://github.com/AtomicBot-ai/Strata/tree/research/forkspec-factor) · `4aaee271ab`
- [research/final-sprint-inkling](https://github.com/AtomicBot-ai/Strata/tree/research/final-sprint-inkling) · `bf6c7c3fdd`
- [research/final-sprint-qwen](https://github.com/AtomicBot-ai/Strata/tree/research/final-sprint-qwen) · `572c6198ae`
- [research/final-sprint-opencode-fixture](https://github.com/AtomicBot-ai/Strata/tree/research/final-sprint-opencode-fixture) · `679dc4748f`
- [research/flash-next-auto-parent-trace-wip](https://github.com/AtomicBot-ai/Strata/tree/research/flash-next-auto-parent-trace-wip) · `071de979d3` · промежуточный снимок параллельной работы; готовность не проверялась.
