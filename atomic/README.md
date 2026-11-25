# Atomic Turbine 0.1.0

Локальная сборка для macOS arm64 с Metal на базе Strata 0.1.69. В архиве два исполняемых движка и совместимый с OpenAI HTTP-сервер. Веса и токенизатор предоставляет оператор.

## Запуск API с Inkling

Из распакованного каталога, в Python-окружении с пакетами из `terminal/requirements.txt`:

```sh
./atomic-turbine --version
./atomic-turbine serve-inkling --model "$INKLING_MODEL" --tokenizer "$INKLING_TOKENIZER" --port 8080
```

Укажите путь к файлу Inkling-2-Mini SQ-10 в `INKLING_MODEL` и каталог подготовленного токенизатора в `INKLING_TOKENIZER`. Для конвертации исходных файлов используйте `python3 terminal/tools/inkling_tokenizer.py --help`. Адрес сервера — `http://127.0.0.1:8080/v1`, модель — `inkling`. Профиль открывает два слота для запросов и слушает только loopback.

Для OpenCode задайте в конфигурации проекта локального провайдера и запустите `opencode run -m turbine/inkling "Опиши этот репозиторий"`.

```json
{
  "provider": {
    "turbine": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Atomic Turbine",
      "options": {"baseURL": "http://127.0.0.1:8080/v1", "apiKey": "local"},
      "models": {"inkling": {"name": "Inkling", "limit": {"context": 24576, "output": 1024}}}
    }
  },
  "enabled_providers": ["turbine"],
  "model": "turbine/inkling",
  "small_model": "turbine/inkling"
}
```

HTTP-сервер управляет обычным повторным использованием префикса. Для явного native fork интеграции нужен клиент, который знает родительский запрос и владеет процессом движка через нативный протокол.

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

## Сборка из исходников

В корне форка, с CMake, Apple Command Line Tools и локальными заголовками metal-cpp:

```sh
cmake -S engine/src/inkling2 -B build-inkling -DCMAKE_BUILD_TYPE=Release
cmake --build build-inkling --target strata-inkling
cmake -S engine/metal -B build-qwen -DCMAKE_BUILD_TYPE=Release -DMETAL_CPP_DIR="$METAL_CPP_DIR"
cmake --build build-qwen --target strata
python3 atomic/package.py build-inkling/strata-inkling build-qwen/strata "$METAL_CPP_DIR" --output dist
```

В архиве manifest.json содержит Git-ревизию и SHA-256 каждого файла сборки. Уведомления об авторских правах находятся в LICENSE и THIRD_PARTY.md.
