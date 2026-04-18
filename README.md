# Audio Transcriber

Десктоп-приложение для транскрипции и диаризации русскоязычного аудио на
ноутбуке с GTX 1650 Ti 4 GB. CustomTkinter UI поверх faster-whisper +
pyannote 3.1.

## Установка

```bash
pip install -r requirements.txt
# Требуется ffmpeg в PATH (https://ffmpeg.org/download.html)
```

Версии в `requirements.txt` зафиксированы, потому что воркараунды
для speechbrain/lightning/pyannote/cuDNN привязаны к конкретным
комбинациям. Не обновляйте без проверки на 62-минутном файле с
диаризацией.

## Hugging Face токен

Для диаризации нужен токен с принятыми условиями
[`pyannote/speaker-diarization-3.1`](https://huggingface.co/pyannote/speaker-diarization-3.1).
Токен подхватывается в таком порядке (первый непустой выигрывает):

1. Поле «HF Token» в UI (после нажатия «Вставить» сохраняется в `config.json`).
2. Переменная окружения `HF_TOKEN`.

Рекомендуется хранить токен в env (не в `config.json`), чтобы он не
попал в git. `config.json` уже в `.gitignore`. Шаблон без секретов —
`config.example.json`.

## Запуск

```bash
python app.py
```

## Тесты

```bash
pip install -r requirements-dev.txt
pytest
```

## Документы

- Дизайн-спека: `docs/superpowers/specs/2026-04-02-audio-transcriber-design.md`
- План улучшений: см. историю коммитов / `C:\Users\<you>\.claude\plans\`
