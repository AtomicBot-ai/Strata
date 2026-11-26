# Компоненты локальной сборки

Atomic Turbine основан на Strata 0.1.69, commit `b28ca95e3e6847f2d5e317994f253b66716deeaa`. Авторские уведомления и исходная лицензия MIT сохранены в LICENSE. История Git доступна в исходном форке.

- В Inkling встроен декодер Zstandard (BSD) и используются заголовки stb (выбрана лицензия MIT). Тексты находятся в каталоге licenses.
- Код квантования и форматы данных включают производные от ggml (MIT). Лицензии vendored ggml и заголовков прилагаются. Qwen собран со штатным CPU-кодом Strata, отдельная динамическая библиотека ggml не требуется.
- Слой Metal использует заголовки Apple metal-cpp (Apache License 2.0). Текст прилагается в licenses. Системные фреймворки предоставляет macOS.
- Веб-интерфейс Strata содержит KaTeX (MIT). Уведомление остаётся в terminal/serve/web/vendor/katex. Сведения Strata о происхождении дополнительного DFlash2 находятся в terminal/data/dflash2-tuned.
- Шрифт Outfit поставляется с SIL Open Font License 1.1 в terminal/serve/web/fonts/OFL.txt.
- Веса целевых моделей, их токенизаторы и OpenCode устанавливаются отдельно. Python-пакеты API и их версии перечислены в terminal/requirements.txt и распространяются их авторами.
