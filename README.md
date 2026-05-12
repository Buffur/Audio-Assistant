# UTOS Audio Assistant Bot

Telegram-бот для перетворення тексту, документів, фотографій з текстом і веб-статей у голосові повідомлення.

Проєкт орієнтований на доступність, зручне прослуховування текстових матеріалів і підтримку користувачів, яким легше сприймати інформацію на слух.

---

## Мета проєкту

Основна мета — створити аудіо-асистента, який допомагає користувачу швидко отримати озвучену версію текстової інформації.

Бот може:

- озвучувати звичайний текст;
- читати PDF, DOCX і TXT документи;
- розпізнавати текст на фотографіях;
- витягувати основний текст зі статей за посиланням;
- розбивати великі тексти на частини;
- генерувати короткий зміст великих матеріалів;
- дозволяти користувачу обирати голос і швидкість читання.

---

## Основний сценарій роботи

1. Користувач надсилає текст, файл, фото або посилання.
2. Бот витягує текст із вхідного матеріалу.
3. Текст очищується та розбивається на частини.
4. Для кожної частини генерується аудіо.
5. Бот надсилає voice-повідомлення в Telegram.
6. Якщо текст великий, користувач може:
   - слухати далі;
   - отримати короткий зміст;
   - завершити читання.

---

## Архітектура проєкту

```mermaid
flowchart TD
    User[Користувач Telegram] --> Bot[Telegram Bot / Aiogram]

    Bot --> Middleware[Middleware Layer]
    Middleware --> RateLimit[RateLimitMiddleware]
    Middleware --> UserAccess[UserAccessMiddleware]

    Bot --> Handlers[Handlers Layer]

    Handlers --> StartHandler[start.py]
    Handlers --> SettingsHandler[settings.py]
    Handlers --> MessagesHandler[messages.py]
    Handlers --> ReadingCallbacks[reading_callbacks.py]
    Handlers --> AdminHandler[admin.py]
    Handlers --> ErrorHandler[errors.py]

    MessagesHandler --> ContentExtractor[content_extractor.py]
    MessagesHandler --> ReadingService[reading_service.py]
    ReadingCallbacks --> ReadingService

    ContentExtractor --> FileProcessor[file_processor.py]
    ContentExtractor --> OCR[ocr.py]
    ContentExtractor --> Parser[parser.py]

    ReadingService --> TTS[tts.py]
    ReadingService --> VoiceSelector[voice_selector.py]
    ReadingService --> VoiceSender[voice_sender.py]
    ReadingService --> SessionStore[reading_session_store.py]

    TTS --> Splitter[splitter.py]
    TTS --> AudioConverter[audio.py / FFmpeg]

    SettingsHandler --> UserSettings[user_settings_service.py]
    UserSettings --> Database[(SQLite Database)]

    UserAccess --> Database
    AdminHandler --> Database

    Parser --> Gemini[Gemini API]
    OCR --> Gemini
    TTS --> EdgeTTS[Edge TTS]
    AudioConverter --> FFmpeg[FFmpeg]