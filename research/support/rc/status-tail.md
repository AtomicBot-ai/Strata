
## Воспроизведение

Взять Strata `b28ca95e` и Atomic Turbine из manifest.json. Собрать два Release-бинарника Strata теми же CMake-командами, что в Quick Start продукта, с исходниками Strata. На стороне продукта использовать файлы `bin/strata-inkling` и `bin/strata` из ZIP вместе с их ресурсами. На стороне Strata оставить доступ к штатному дереву Metal-ресурсов. На обоих профилях используется штатный scheduler.

Задать `PACKAGE`, `STOCK_SERVER` (upstream terminal/serve/server.py), `STOCK_INKLING`, `STOCK_QWEN`, `INKLING_MODEL`, `INKLING_TOKENIZER`, а также `QWEN_PACK`, `QWEN_GGUF_1`, `QWEN_GGUF_2` и `QWEN_PROFILE`. Из корня продуктового репозитория в окружении с runtime requirements выполнить последовательно для нового каталога результатов:

```sh
python atomic/bench/native.py inkling atomic/bench/profiles.json "$STOCK_INKLING" "$PACKAGE/bin/strata-inkling" results/native
python atomic/bench/native.py qwen atomic/bench/profiles.json "$STOCK_QWEN" "$PACKAGE/bin/strata" results/native
python atomic/bench/http_runs.py "$STOCK_SERVER" "$STOCK_INKLING" "$PACKAGE" "$INKLING_MODEL" "$INKLING_TOKENIZER" results/http
```

[Inkling, исходные прогоны](atomic/bench/results/inkling.json) · [Qwen, исходные прогоны](atomic/bench/results/qwen.json) · [Клиент, ответы и серверные подтверждения](atomic/bench/results/agent.json) · [Результаты инженерных проверок](atomic/bench/results/engineering.json)
