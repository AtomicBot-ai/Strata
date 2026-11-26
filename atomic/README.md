# Atomic Turbine 0.1.0

Локальная сборка для macOS arm64 с Metal на базе Strata 0.1.69. В архиве два исполняемых движка и совместимый с OpenAI HTTP-сервер. Веса и токенизатор предоставляет оператор.

На Apple M4 Max четыре проверяемых вопроса по одному исходнику через HTTP заняли в медиане 3,89 с против 10,14 с у Strata. Это замер поставляемого Python-клиента. Условия и результаты остальных сценариев — в [release notes](RELEASE_NOTES.md).

## Быстрый запуск

Сборка проверена на Apple M4 Max с 48 ГиБ и macOS 27.2.1. Минимальная версия macOS в обоих Mach-O — 27.2. Для установки зависимостей используйте Python 3.11 или новее. Шлюз слушает 127.0.0.1. Скачайте Inkling-2-Mini SQ-10 в родном формате и соответствующие `tokenizer.json` и `chat_template.jinja` из [репозитория весов](https://huggingface.co/strata-engine/Inkling-2-Mini-Strata). Веса распространяются отдельно.

Для SQ-10 шаблон также можно извлечь из весов командой `./atomic-turbine inkling --export-tokenizer "$INKLING_MODEL" hf` и задать `HF_TEMPLATE=hf/chat_template.jinja`. Отдельный HF tokenizer.json нужен и в этом случае.

Из распакованного каталога, указав пути к загруженным файлам:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r terminal/requirements.txt
python terminal/tools/inkling_tokenizer.py --hf-json "$HF_TOKENIZER_JSON" --template "$HF_TEMPLATE" --out tokenizer
./atomic-turbine serve-inkling --model "$INKLING_MODEL" --tokenizer tokenizer --snapshot-mib 1536
```

Во втором терминале из того же каталога:

```sh
curl -fsS http://127.0.0.1:8080/v1/turbine/capabilities
curl -fsS http://127.0.0.1:8080/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"inkling","messages":[{"role":"user","content":"Say hello"}],"max_tokens":32}'
python3 fork_demo.py
```

Демо читает исходник launcher и отправляет четыре вопроса о его настройках. В выводе — ожидаемое значение, фактический ответ и время. Сервер пишет `checkpoint_created`, `checkpoint_restored`, `fork_admitted` и `checkpoint_dropped`. Поле `request_id` у двух событий ветки совпадает с идентификатором ответа после `chatcmpl-`. Для обычного режима передайте демо `--ordinary`. Опция сервера `--snapshot-mib` по умолчанию равна нулю.

## Контракт checkpoint API

- `POST /v1/turbine/checkpoints` принимает точное имя модели, общую историю `messages` и те же настройки шаблона и `tools`, что и запросы веток. Ответ `201` содержит `id`, `tokens` и `ttl_seconds`. Подготовка родителя занимает время. Одновременно у процесса может быть один родитель, следующий получает `409`.
- Для ветки отправьте полную историю в `POST /v1/chat/completions` с заголовком `X-Turbine-Checkpoint: <id>`. Токены начала истории должны совпадать. Несовместимый префикс получает `409` до открытия стрима. Неизвестный, чужой или истёкший ID получает `404`. Клиент может явно повторить запрос без заголовка.
- `DELETE /v1/turbine/checkpoints/{id}` закрывает снимок для новых веток. Ответ `204` подтверждает удаление, `202` означает отложенное освобождение. Через пять минут родитель закрывается автоматически. Начатые ветки завершаются со своими слотами. Перезапуск аннулирует ID.
- Режим alpha обслуживает текст, включая текстовые вызовы инструментов. Один loopback-сервер без ключа образует одну доверенную локальную среду. При настроенных API-ключах снимок привязан к ключу создателя. Бюджет Inkling ограничивает полезную нагрузку снимка; модель и активные слоты потребляют память отдельно.

## OpenCode

Для Flash-Next на Mac запустите сервер из распакованного ZIP с активным Python-окружением:

```sh
./atomic-turbine serve-flash-next --model-dir "$FLASH_NEXT_IQ3_DIR" --pack "$FLASH_NEXT_PACK"
```

В каталоге модели должны лежать обе части IQ3_XXS и `profile.bin`, в подготовленном пакете Strata — `dense.bin` и `tokenizer/`. Профиль резервирует третий слот для истории и оставляет два для запросов. Для Inkling используйте `serve-inkling` из Quick Start.

В конфигурации проекта OpenCode укажите адрес локального сервера и модель:

```json
{
  "provider": {
    "turbine": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Atomic Turbine",
      "options": {"baseURL": "http://127.0.0.1:8080/v1", "apiKey": "local"},
      "models": {"qwen": {"name": "Flash-Next", "limit": {"context": 24576, "output": 1024}}}
    }
  },
  "enabled_providers": ["turbine"],
  "model": "turbine/qwen",
  "small_model": "turbine/qwen"
}
```

Запустите `opencode run -m turbine/qwen "Разбери этот репозиторий"`. Плагин и дополнительные заголовки не нужны. Для сервера Inkling замените имя модели в конфигурации и команде на `inkling`.

Flash-Next может сохранить состояние перед последним вопросом и продолжить с него, если следующий запрос начинается с тех же токенов. Порог задаёт параметр движка `--prompt-cache-root` (по умолчанию 2048 токенов, ноль отключает автоматический снимок). Если уже доступен более длинный префикс, используется штатный кеш. В ответе HTTP поле `usage.prompt_tokens_details.cached_tokens` учитывает все виды повторного использования. Только строка `turbine: automatic parent restored tokens=N` в журнале движка подтверждает чтение из резервного слота. Явный checkpoint владеет слотом до освобождения.

OpenCode выбирает историю и системные инструкции для каждого агента. Одинаковое имя репозитория или файл в середине двух запросов сами по себе не дают общего состояния. Время работы зависит от фактических запросов клиента.

## Flash-Next на CUDA и HIP из исходников

Соберите цель `strata` из этого форка для своей карты. В рабочем JSON-конфиге Strata задайте `exe` с путём к собранному бинарнику, `model_name` со значением `qwen` и `env.TURBINE_QWEN_FORK` со строковым значением `"1"`. В `args` нужны `--batch 3`, `--suffix-draft 0`, один GPU, текстовый профиль с выключенным drafter, фиксированной ёмкостью KV и включённым кешем запросов. Запустите сервер из корня форка:

```sh
python terminal/serve/server.py --engine strata --config qwen.json --host 127.0.0.1 --port 8080 --offline
```

В OpenCode используется тот же провайдер `turbine/qwen`. Для проверки сборки на конкретной карте выполните `python atomic/bench/qwen_auto.py qwen.json` при остановленном сервере. Тест запускает модель с короткой историей, проверяет попадания, промах и совместимость явного снимка. Статусы физических GPU перечислены в `RELEASE_STATUS.md` исходной ветки.

## Ветвление через нативный протокол Inkling

```sh
TURBINE_SNAPSHOT_MIB=1536 ./atomic-turbine inkling --serve --native "$INKLING_MODEL" --draft off --kv fp16 --parallel 2 --max-context 33792 --chunk 128
```

Один доверенный клиент владеет stdin/stdout процесса. При поддерживаемой конфигурации INFO содержит `native_fork=1`. Пример последовательности команд:

```text
BGEN 0 0 ckpt=0 178,179,180
STATE_SAVE 0
STATE_RESTORE 1 <handle>
BGEN 1 8 temperature=0 178,179,180,181
STATE_DROP <handle>
```

Дождитесь `BADM 0 0` перед сохранением. Ответ `SAVED <handle> <tokens> <bytes>` содержит идентификатор снимка. После `RESTORED` в запросе передаётся полный префикс и новое продолжение. Перед повторным восстановлением в занятый слот дождитесь `BDONE` или отмените запрос командой `BSTOP <slot>`. Снимок живёт до DROP или выхода из процесса. Разрешён один снимок на процесс. Лимит учитывает полезную нагрузку KV, рекуррентных буферов и токенов префикса. Отдельно расходуется память модели, слотов и среды выполнения. По умолчанию лимит снимков равен нулю.

## Qwen с выгрузкой экспертов на SSD

Подготовьте pack для Qwen3.8-Flash-Next IQ3_XXS, оба файла GGUF и профиль экспертов соответствующей модели.

```sh
STRATA_METAL_STREAM=1 STRATA_METAL_ARENA_GB=6 ./atomic-turbine qwen --serve \
  --pack "$QWEN_PACK" --native "$QWEN_GGUF_1" --ple-gguf "$QWEN_GGUF_2" \
  --expert-profile "$QWEN_PROFILE" --expert-cache 64 --batch 2 --max-context 512 \
  --prefill auto --spec 2 --suffix-draft 0 --mmap-experts
```

Два слота используют общий кеш экспертов. `STRATA_METAL_ARENA_GB` задаёт размер арены экспертов. `--memory-limit-mib` участвует в штатной проверке запаса RAM при операциях с сессиями. Расход всего процесса зависит также от модели и длины контекста.

Для совмещения snapshot/fork с batching задайте `TURBINE_QWEN_FORK=1` и `--batch 3` в этой же команде. Движок резервирует третий физический слот для одного родителя. Клиент видит `batch_slots=2 native_parent_fork=1` в INFO и подаёт запросы только в слоты 0 и 1. В этом режиме используйте текстовые запросы, один Metal GPU и выключенный drafter.

Прочитайте общий префикс командой `GEN 1 temperature=0 <общие ID>` и дождитесь DONE. Последнее предсказание не входит в сохранённый префикс. Отправьте `STATE_SAVE MAIN` и возьмите handle из ответа `SAVED <handle> <число токенов>`. Перед каждой веткой отправьте `STATE_RESTORE MAIN <handle>`, затем `BGEN <слот> <длина> temperature=0 <общие ID и суффикс>`. Движок копирует восстановленное состояние в слот запроса при приёме ветки, и обе ветки могут продолжать генерацию вместе. `STATE_DROP <handle>` освобождает идентификатор. Физическая память третьего слота зарезервирована до выхода процесса.

### HTTP с Qwen

Для того же HTTP-контракта сохраните следующий JSON в `qwen.json` и замените пути на абсолютные пути вашей машины. Укажите токенизатор именно этого pack. Один процесс, одна Metal GPU, без drafter и изображений.

```json
{
  "exe": "/path/to/package/bin/strata",
  "model_name": "qwen",
  "tokenizer": "/path/to/pack/tokenizer",
  "args": ["--serve", "--pack", "/path/to/pack", "--native", "/path/to/first.gguf",
           "--ple-gguf", "/path/to/second.gguf", "--expert-profile", "/path/to/profile.bin",
           "--max-context", "2048", "--expert-cache", "64", "--batch", "3", "--prefill", "auto",
           "--spec", "2", "--suffix-draft", "0", "--mmap-experts"],
  "env": {"STRATA_METAL_STREAM": "1", "STRATA_METAL_ARENA_GB": "6", "TURBINE_QWEN_FORK": "1"}
}
```

```sh
./atomic-turbine api --engine strata --config qwen.json --host 127.0.0.1 --port 8080 --offline --no-api-key
# Во втором терминале
python3 fork_demo.py --model qwen
```

## Сборка из исходников

В корне форка, с CMake, Apple Command Line Tools и локальными заголовками metal-cpp:

```sh
cmake -S engine/src/inkling2 -B build-inkling -DCMAKE_BUILD_TYPE=Release
cmake --build build-inkling --target strata-inkling
cmake -S engine/metal -B build-qwen -DCMAKE_BUILD_TYPE=Release -DSTRATA_PACKAGED_METAL=ON -DMETAL_CPP_DIR="$METAL_CPP_DIR"
cmake --build build-qwen --target strata
python3 atomic/package.py build-inkling/strata-inkling build-qwen/strata "$METAL_CPP_DIR" --output dist
```

В архиве manifest.json содержит Git-ревизию и SHA-256 каждого файла сборки. Уведомления об авторских правах находятся в LICENSE и THIRD_PARTY.md.

После упаковки рядом с ZIP лежит файл `.sha256`. В каталоге архива выполните `shasum -a 256 -c ИМЯ.zip.sha256` и распакуйте его с сохранением прав исполнения. База — [Strata](https://github.com/Niko1221/Strata).
