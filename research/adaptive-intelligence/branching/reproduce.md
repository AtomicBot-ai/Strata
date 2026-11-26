# Воспроизведение пилота Strata

Все команды выполнялись из корня turbine-intelligence. Потребуются M4 Max, локальный файл Inkling-2-Mini-SQ-10.strata с SHA-256 `ac4d452ad03e4930abd9d46f9c5eec22b2f75a1da45a1e49bd24ccd58b065934`, соответствующий tokenizer.json, Python с numpy и tokenizers, CMake, Apple Clang и Docker для изолированной оценки решений. Расположение модели, токенизатора и собранного движка задаётся в engine.py. Исходная ревизия Strata `26350e4387b8019b0f6825ba78b87eb6360159e7` плюс экспериментальные изменения в этой рабочей копии.

## Входные данные

Подготовщик читает JSON из четырёх файлов. Исходные наблюдения используют MATH-500 и три диапазона файла test6.jsonl из LiveCodeBench release_v6. Использование диапазонов уменьшает загрузку данных. [MATH-500](https://huggingface.co/datasets/HuggingFaceH4/MATH-500/tree/6e4ed1a2a79af7d8630a6b768ec859cb5af4d3be) · [LiveCodeBench](https://huggingface.co/datasets/livecodebench/code_generation_lite/tree/0fe84c3912ea0c4d4a78037083943e8f0c4dd505)

```sh
data=.work/pilot-data
mkdir -p "$data"
math=https://huggingface.co/datasets/HuggingFaceH4/MATH-500/resolve/6e4ed1a2a79af7d8630a6b768ec859cb5af4d3be/test.jsonl
code=https://huggingface.co/datasets/livecodebench/code_generation_lite/resolve/0fe84c3912ea0c4d4a78037083943e8f0c4dd505/test6.jsonl
curl -fsSL "$math" -o "$data/math.jsonl"
curl -fsSL -r 0-4194303 "$code" -o "$data/code6-prefix.jsonl"
curl -fsSL -r 16777216-29360127 "$code?part=mid" -o "$data/code6-mid.jsonl"
curl -fsSL -r '-8388608' "$code?download=true" -o "$data/code6-tail.jsonl"
python3 -B research/adaptive-intelligence/branching/prepare.py
shasum -a 256 .work/pilot-data/public.json .work/pilot-data/labels.json
```

Ожидаемый хеш публичных задач `1eae152671d23f17bd3861111cd91bea4aa3bdf16d74cbb0d83189a29e6052ce`. Хеш меток `07377f084c68b8ea9691072fc9754406072f36e1012a5f55093b8816d557eb3c`. Файл меток используется внешним оценщиком после генерации. Скрытые кейсы поступают в контейнер только как входные данные, ожидаемые ответы сверяются снаружи. Незаконченные и неизвлекаемые решения засчитываются как ошибки. Время запуска проверочного контейнера включено в стоимость публичной проверки. Скрытое оценивание в стоимость принятия решения не входит.

## Сборка и стадии

Выполнять последовательно. В каждой команде вывода используется новый каталог или новый файл. Исходный пилот занял только часть выделенных двух часов. Наборы ниже относятся к гипотезе о внутренних ветках.

```sh
cmake -S Strata/engine/src/inkling2 -B .work/strata-build -DCMAKE_BUILD_TYPE=Release
cmake --build .work/strata-build --target strata-inkling --parallel 2
lab=research/adaptive-intelligence/branching
out=.work/reproduce-strata
mkdir -p "$out"
docker pull python@sha256:c5ba3deef00c7758561a0f03c26f44f10589263d40e732b8748e0d1f38f6dd89
python3 -B "$lab/check.py" "$out/gate"
python3 -B "$lab/search.py" "$out/debug" --split debug
python3 -B "$lab/grade.py" "$out/debug" "$out/debug/scores.jsonl"
python3 -B "$lab/fixed_cost.py" "$out/debug/raw.jsonl" "$out/cost"
STRATA_PILOT_STARTED="$out/debug/manifest.json" python3 -B "$lab/search.py" "$out/pilot" --split pilot
STRATA_PILOT_STARTED="$out/debug/manifest.json" python3 -B "$lab/grade.py" "$out/pilot" "$out/pilot/scores.jsonl"
python3 -B "$lab/summary.py" "$out/debug/scores.jsonl" "$out/pilot/scores.jsonl" "$out/pilot/comparison.json"
```

## Граница чекпойнта

Флаг `--research-checkpoint` включает в stdin-протокол команды SAVE, RESTORE, DROP и диагностическую LOGITS. Эксперимент рассчитан на один незанятый текстовый слот Metal, FP16 KV и отключённый DSpark. Один снимок принадлежит одному процессу. SAVE заменяет предыдущий снимок. Он хранит физические строки KV по каждому посещению слоя, четыре истории ShortConv и точные ID уже обработанного префикса. Последний выданный, ещё не обработанный токен контроллер снова подаёт обычной командой GEN. GEN получает полный список токенов и seed дочерней ветки, поэтому восстанавливает историю штрафов и инициализирует независимый генератор случайных чисел. Это форк на границе запросов, а не произвольная приостановка активного сэмплера. RESTORE можно повторять. DROP освобождает снимок. LOGITS возвращает байты FP32 последней строки для диагностического сравнения с отключёнными штрафами. Снаружи обычный контроллер использует штатные GEN, GENERATE и повторное использование слота.
