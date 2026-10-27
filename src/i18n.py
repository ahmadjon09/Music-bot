"""Tiny i18n engine — Uzbek, Russian, English.

One flat dict per language, identical key sets (enforced by tests).
Missing keys fall back to English, then to the key itself.
"""

from __future__ import annotations

LANGS: dict[str, str] = {"uz": "🇺🇿 O'zbek", "ru": "🇷🇺 Русский", "en": "🇬🇧 English"}
DEFAULT_LANG = "uz"

_STRINGS: dict[str, dict[str, str]] = {
    "uz": {
        "start_title": "🎧 <b>Music Bot</b>ga xush kelibsiz, {name}!",
        "start_body": (
            " menga shunchaki yuboring:\n\n"
            "🔗 <b>Havola</b> — YouTube, TikTok, Instagram, X, Pinterest va 1000+ saytdan video/rasm yuklab beraman\n"
            "🔍 <b>Qo'shiq nomi</b> — yozing, Dydki.net'dan topib beraman\n"
            "🎬 <b>Video</b> — ichidagi qo'shiqni Shazam bilan aniqlayman\n\n"
            "<i>Tez. Bepul. Reklamasiz.</i> ⚡️"
        ),
        "btn_help": "📖 Yordam",
        "btn_settings": "⚙️ Sozlamalar",
        "btn_status": "📊 Holat",
        "btn_admin": "🛠 Admin panel",
        "btn_back": "⬅️ Orqaga",
        "btn_main_menu": "🏠 Bosh menyu",
        "btn_mp3": "🎵 MP3 yuklab olish",
        "btn_video": "🎬 Video yuklab olish",
        "btn_shazam": "🎵 Qo'shiqni aniqlash",
        "btn_audio_from_video": "🎧 Audiosini olish",
        "btn_download": "⬇️ Yuklab olish",
        "btn_search_music": "🔍 Dydki.net'dan qidirish",
        "help_text": (
            "📖 <b>Yordam</b>\n\n"
            "🔗 <b>Havola yuboring</b> — video, rasm yoki karuselni yuklab beraman.\n"
            "🔍 <b>Nom yozing</b> — Dydki.net katalogidan qo'shiq qidiraman (10 daqiqadan qisqa, 20+ natija).\n"
            "🎬 <b>Video yuboring</b> — fon musiqasini aniqlayman.\n\n"
            "<b>Komandalar:</b>\n"
            "/audio &lt;havola&gt; — faqat MP3 olish\n"
            "/video &lt;havola&gt; — video olish\n"
            "/search &lt;nom&gt; — qidiruv\n"
            "/shazam — videoga javob qilib yuboring\n"
            "/lang — tilni almashtirish\n"
            "/settings — sozlamalar\n"
            "/cookies — shaxsiy cookies yuklash (ixtiyoriy)\n"
            "/id — o'z ID'ingiz\n"
            "/status — bot holati\n\n"
            "💡 <i>Katta videolar 50 MB dan oshsa Telegram qabul qilmaydi — sifatni Sozlamalarda pasaytiring.</i>"
        ),
        "settings_title": "⚙️ <b>Sozlamalar</b>",
        "settings_lang": "🌐 Til: <b>{lang}</b>",
        "settings_quality": "🎞 Video sifati: <b>{quality}</b>",
        "btn_language": "🌐 Tilni almashtirish",
        "btn_quality": "🎞 Video sifati",
        "choose_lang": "🌐 Tilni tanlang:",
        "choose_quality": "🎞 Video sifatini tanlang:",
        "lang_saved": "✅ Til o'zbek tiliga o'zgartirildi",
        "quality_saved": "✅ Sifat saqlandi: {quality}",
        "status_text": (
            "📊 <b>Bot holati</b>\n\n"
            "🟢 Holat: <b>ishlayapti</b>\n"
            "⏱ Ish vaqti: <b>{uptime}</b>\n"
            "👥 Foydalanuvchilar: <b>{users}</b>\n"
            "⬇️ Jami yuklab olingan: <b>{downloads}</b>\n"
            "🗄 Keshdagi fayllar: <b>{cached}</b>\n"
            "⚙️ yt-dlp: <code>{ytdlp}</code>\n"
            "🧩 Versiya: <code>{version}</code>"
        ),
        "analyzing": "{spinner} Havola tekshirilmoqda...",
        "searching": "{spinner} <b>{query}</b> qidirilmoqda...",
        "downloading": "{spinner} <b>Yuklanmoqda...</b>\n\n{bar} <b>{perc}%</b>\n⚡️ {speed} · ⏳ {eta}",
        "downloading_simple": "{spinner} <b>Yuklanmoqda...</b>",
        "uploading": "📤 <b>Telegram'ga yuborilmoqda...</b>",
        "processing": "{spinner} Qayta ishlanmoqda (metadata + muqova)...",
        "queue_wait": "⏳ Navbatda kutilmoqda...",
        "search_results": "🔎 <b>«{query}»</b> — {total} ta natija\n📄 Sahifa <b>{page}/{pages}</b>\n\n<i>Raqamni bosing — MP3 shu zahoti keladi</i> 🎧",
        "search_empty": "😕 Hech narsa topilmadi. Boshqa nom bilan urinib ko'ring.",
        "search_expired": "⌛️ Bu qidiruv muddati tugagan. Qayta qidirib yuboring.",
        "send_link_or_name": "🔗 Havola yoki qo'shiq nomini yuboring.",
        "unsupported": "😕 Bu havolani o'qiy olmadim. Boshqa link bilan urinib ko'ring.",
        "error_generic": "⚠️ Xatolik yuz berdi. Birozdan keyin qayta urining.",
        "error_too_large": "🐘 Fayl juda katta (50 MB limit). Sifatni Sozlamalarda pasaytirib ko'ring.",
        "error_private": "🔒 Bu kontent yopiq/maxfiy. Cookies yuklash yordam berishi mumkin (/cookies).",
        "error_age": "🔞 Yosh cheklovi bor kontent. /cookies orqali akkaunt cookies yuklasangiz yuklab bera olaman.",
        "error_unavailable": "🚫 Kontent mavjud emas (o'chirilgan yoki hudud cheklovi).",
        "error_ratelimit": "🐌 Sayt hozir cheklov qo'ymoqda. 1-2 daqiqadan keyin urining.",
        "error_botcheck": "🤖 YouTube bot-tekshiruvi qo'ydi (kirishni talab qilmoqda). Birozdan keyin qayta urining — admin cookies/proxy yangilasa o'tib ketadi.",
        "error_format": "🎞 Bu havola uchun yuklab bo'ladigan format topilmadi. Boshqa havola bilan urining yoki keyinroq qayting.",
        "busy_user": "⏳ Avvalgi yuklash tugashini kuting — men tezkorman, uzoq emas 😉",
        "from_cache": "⚡️ Keshdan yuborildi (0 soniya yuklash!)",
        "carousel_caption": "🖼 {title}",
        "video_received": "🎬 <b>Video qabul qilindi!</b>\n\nNima qilay?",
        "shazam_working": "{spinner} Eshitib ko'ryapman... 🎧",
        "shazam_found": "🎵 <b>Topdim!</b>\n\n🎤 <b>{artist}</b>\n🎼 <b>{title}</b>",
        "shazam_notfound": "🤔 Bu qo'shiqni tanimadim. Balandroq/aniqroq qismidan yuborib ko'ring.",
        "shazam_hint": "🎬 Videoga <b>javob (reply)</b> qilib /shazam yuboring — yoki shunchaki video tashlang, o'zim taklif qilaman.",
        "cookies_prompt": (
            "🍪 <b>Cookies</b>\n\n"
            "Yopiq/yosh-cheklovli kontent uchun brauzeringizdan eksport qilingan "
            "<code>cookies.txt</code> faylini yuboring (Netscape format).\n"
            "Fayl shifrlangan holda saqlanadi 🔐\n\n"
            "Holat: <b>{status}</b>"
        ),
        "cookies_status_on": "✅ yuklangan",
        "cookies_status_off": "❌ yuklanmagan",
        "cookies_saved": "✅ Cookies saqlandi ({total} ta, {domains} domen).",
        "cookies_invalid": "❌ Yaroqsiz fayl: {error}",
        "cookies_deleted": "🗑 Cookies o'chirildi.",
        "btn_delete_cookies": "🗑 Cookies'ni o'chirish",
        "your_id": "🆔 Sizning ID: <code>{id}</code>",
        "admin_only": "⛔️ Bu bo'lim faqat adminlar uchun.",
        "admin_panel_text": "🛠 <b>Admin panel</b>\n\nProxy, cookies, statistika — qizg'in rejimda (restartlarsiz) boshqaring.",
        "profile_reset_done": "♻️ Bot profili (ism, tavsiflar, komandalar) 3 tilda boshidan qayta oʻrnatildi ✅",
        "admin_no_url": "⚠️ PUBLIC_BASE_URL sozlanmagan — Web App tugmasini chiqarib bo'lmadi.",
        "proxy_saved": "✅ Proxy yangilandi: <code>{proxy}</code>",
        "proxy_cleared": "✅ Proxy o'chirildi — to'g'ridan-to'g'ri ulanish.",
        "proxy_invalid": "❌ Proxy formati noto'g'ri: {error}",
        "stats_text": (
            "📊 <b>Statistika</b>\n\n👥 Foydalanuvchilar: <b>{users}</b>\n"
            "⬇️ Yuklashlar: <b>{downloads}</b>\n🗄 Kesh: <b>{cached}</b> ta fayl\n"
            "⏱ Ish vaqti: <b>{uptime}</b>\n🌐 Proxy: <code>{proxy}</code>"
        ),
        "maintenance_on": "🛠 Bot texnik ishlar rejimida. Birozdan keyin qayting 🙏",
        "page_prev": "⬅️",
        "page_next": "➡️",
        "btn_close": "✖️ Yopish",
        "results_for": "natija",
        "track_ready": "🎵 Tayyor!",
    },
    "ru": {
        "start_title": "🎧 Добро пожаловать в <b>Music Bot</b>, {name}!",
        "start_body": (
            "Просто отправьте мне:\n\n"
            "🔗 <b>Ссылку</b> — скачаю видео/фото с YouTube, TikTok, Instagram, X, Pinterest и 1000+ сайтов\n"
            "🔍 <b>Название песни</b> — найду её в каталоге Dydki.net\n"
            "🎬 <b>Видео</b> — распознаю фоновую музыку через Shazam\n\n"
            "<i>Быстро. Бесплатно. Без рекламы.</i> ⚡️"
        ),
        "btn_help": "📖 Помощь",
        "btn_settings": "⚙️ Настройки",
        "btn_status": "📊 Статус",
        "btn_admin": "🛠 Админ-панель",
        "btn_back": "⬅️ Назад",
        "btn_main_menu": "🏠 Главное меню",
        "btn_mp3": "🎵 Скачать MP3",
        "btn_video": "🎬 Скачать видео",
        "btn_shazam": "🎵 Распознать песню",
        "btn_audio_from_video": "🎧 Извлечь аудио",
        "btn_download": "⬇️ Скачать",
        "btn_search_music": "🔍 Искать в каталоге Dydki.net",
        "help_text": (
            "📖 <b>Помощь</b>\n\n"
            "🔗 <b>Отправьте ссылку</b> — скачаю видео, фото или карусель.\n"
            "🔍 <b>Напишите название</b> — найду песню в каталоге Dydki.net (до 10 минут, 20+ результатов).\n"
            "🎬 <b>Отправьте видео</b> — распознаю фоновую музыку.\n\n"
            "<b>Команды:</b>\n"
            "/audio &lt;ссылка&gt; — только MP3\n"
            "/video &lt;ссылка&gt; — видео\n"
            "/search &lt;название&gt; — поиск\n"
            "/shazam — в ответ на видео\n"
            "/lang — сменить язык\n"
            "/settings — настройки\n"
            "/cookies — загрузить личные cookies (необязательно)\n"
            "/id — ваш ID\n"
            "/status — статус бота\n\n"
            "💡 <i>Файлы больше 50 МБ Telegram не примет — снизьте качество в Настройках.</i>"
        ),
        "settings_title": "⚙️ <b>Настройки</b>",
        "settings_lang": "🌐 Язык: <b>{lang}</b>",
        "settings_quality": "🎞 Качество видео: <b>{quality}</b>",
        "btn_language": "🌐 Сменить язык",
        "btn_quality": "🎞 Качество видео",
        "choose_lang": "🌐 Выберите язык:",
        "choose_quality": "🎞 Выберите качество видео:",
        "lang_saved": "✅ Язык изменён на русский",
        "quality_saved": "✅ Качество сохранено: {quality}",
        "status_text": (
            "📊 <b>Статус бота</b>\n\n"
            "🟢 Статус: <b>работает</b>\n"
            "⏱ Аптайм: <b>{uptime}</b>\n"
            "👥 Пользователей: <b>{users}</b>\n"
            "⬇️ Всего скачиваний: <b>{downloads}</b>\n"
            "🗄 Файлов в кэше: <b>{cached}</b>\n"
            "⚙️ yt-dlp: <code>{ytdlp}</code>\n"
            "🧩 Версия: <code>{version}</code>"
        ),
        "analyzing": "{spinner} Проверяю ссылку...",
        "searching": "{spinner} Ищу <b>{query}</b>...",
        "downloading": "{spinner} <b>Скачиваю...</b>\n\n{bar} <b>{perc}%</b>\n⚡️ {speed} · ⏳ {eta}",
        "downloading_simple": "{spinner} <b>Скачиваю...</b>",
        "uploading": "📤 <b>Отправляю в Telegram...</b>",
        "processing": "{spinner} Обработка (метаданные + обложка)...",
        "queue_wait": "⏳ Ожидание в очереди...",
        "search_results": "🔎 <b>«{query}»</b> — {total} результатов\n📄 Страница <b>{page}/{pages}</b>\n\n<i>Нажмите на номер — MP3 прилетит сразу</i> 🎧",
        "search_empty": "😕 Ничего не нашлось. Попробуйте другое название.",
        "search_expired": "⌛️ Этот поиск устарел. Отправьте запрос заново.",
        "send_link_or_name": "🔗 Отправьте ссылку или название песни.",
        "unsupported": "😕 Не смог прочитать эту ссылку. Попробуйте другую.",
        "error_generic": "⚠️ Что-то пошло не так. Попробуйте чуть позже.",
        "error_too_large": "🐘 Файл слишком большой (лимит 50 МБ). Снизьте качество в Настройках.",
        "error_private": "🔒 Контент закрыт/приватен. Могут помочь cookies (/cookies).",
        "error_age": "🔞 Контент с возрастным ограничением. Загрузите cookies аккаунта через /cookies.",
        "error_unavailable": "🚫 Контент недоступен (удалён или заблокирован в регионе).",
        "error_ratelimit": "🐌 Сайт временно ограничил запросы. Попробуйте через 1-2 минуты.",
        "error_botcheck": "🤖 YouTube включил проверку «вы не бот» и требует вход. Попробуйте позже — обычно помогают свежие cookies/прокси у админа.",
        "error_format": "🎞 Для этой ссылки не нашлось скачиваемого формата. Попробуйте другую ссылку или чуть позже.",
        "busy_user": "⏳ Дождитесь конца предыдущей загрузки — я быстрый, честно 😉",
        "from_cache": "⚡️ Отправлено из кэша (0 секунд загрузки!)",
        "carousel_caption": "🖼 {title}",
        "video_received": "🎬 <b>Видео получено!</b>\n\nЧто сделать?",
        "shazam_working": "{spinner} Слушаю внимательно... 🎧",
        "shazam_found": "🎵 <b>Нашёл!</b>\n\n🎤 <b>{artist}</b>\n🎼 <b>{title}</b>",
        "shazam_notfound": "🤔 Не узнал эту песню. Попробуйте фрагмент погромче/почётче.",
        "shazam_hint": "🎬 Отправьте /shazam <b>в ответ на видео</b> — или просто пришлите видео, и я сам предложу.",
        "cookies_prompt": (
            "🍪 <b>Cookies</b>\n\n"
            "Для закрытого контента отправьте файл <code>cookies.txt</code>, "
            "экспортированный из браузера (формат Netscape).\n"
            "Файл хранится в зашифрованном виде 🔐\n\n"
            "Статус: <b>{status}</b>"
        ),
        "cookies_status_on": "✅ загружены",
        "cookies_status_off": "❌ не загружены",
        "cookies_saved": "✅ Cookies сохранены ({total} шт., доменов: {domains}).",
        "cookies_invalid": "❌ Неверный файл: {error}",
        "cookies_deleted": "🗑 Cookies удалены.",
        "btn_delete_cookies": "🗑 Удалить cookies",
        "your_id": "🆔 Ваш ID: <code>{id}</code>",
        "admin_only": "⛔️ Этот раздел только для админов.",
        "admin_panel_text": "🛠 <b>Админ-панель</b>\n\nПрокси, cookies, статистика — всё меняется на лету, без перезапуска.",
        "profile_reset_done": "♻️ Профиль бота (имя, описания, команды) заново применён на 3 языках ✅",
        "admin_no_url": "⚠️ PUBLIC_BASE_URL не настроен — кнопку Web App показать не могу.",
        "proxy_saved": "✅ Прокси обновлён: <code>{proxy}</code>",
        "proxy_cleared": "✅ Прокси отключён — прямое соединение.",
        "proxy_invalid": "❌ Неверный формат прокси: {error}",
        "stats_text": (
            "📊 <b>Статистика</b>\n\n👥 Пользователей: <b>{users}</b>\n"
            "⬇️ Скачиваний: <b>{downloads}</b>\n🗄 Кэш: <b>{cached}</b> файлов\n"
            "⏱ Аптайм: <b>{uptime}</b>\n🌐 Прокси: <code>{proxy}</code>"
        ),
        "maintenance_on": "🛠 Бот на техническом обслуживании. Загляните чуть позже 🙏",
        "page_prev": "⬅️",
        "page_next": "➡️",
        "btn_close": "✖️ Закрыть",
        "results_for": "результатов",
        "track_ready": "🎵 Готово!",
    },
    "en": {
        "start_title": "🎧 Welcome to <b>Music Bot</b>, {name}!",
        "start_body": (
            "Just send me:\n\n"
            "🔗 <b>A link</b> — I'll fetch video/photos from YouTube, TikTok, Instagram, X, Pinterest &amp; 1000+ sites\n"
            "🔍 <b>A song name</b> — I'll search the Dydki.net catalogue\n"
            "🎬 <b>A video</b> — I'll identify the background track with Shazam\n\n"
            "<i>Fast. Free. No ads.</i> ⚡️"
        ),
        "btn_help": "📖 Help",
        "btn_settings": "⚙️ Settings",
        "btn_status": "📊 Status",
        "btn_admin": "🛠 Admin panel",
        "btn_back": "⬅️ Back",
        "btn_main_menu": "🏠 Main menu",
        "btn_mp3": "🎵 Download MP3",
        "btn_video": "🎬 Download video",
        "btn_shazam": "🎵 Identify the song",
        "btn_audio_from_video": "🎧 Extract audio",
        "btn_download": "⬇️ Download",
        "btn_search_music": "🔍 Search Dydki.net",
        "help_text": (
            "📖 <b>Help</b>\n\n"
            "🔗 <b>Send a link</b> — video, photo or carousel, delivered instantly.\n"
            "🔍 <b>Type a name</b> — search the Dydki.net catalogue (under 10 min, 20+ results).\n"
            "🎬 <b>Send a video</b> — I'll name the background track.\n\n"
            "<b>Commands:</b>\n"
            "/audio &lt;url&gt; — MP3 only\n"
            "/video &lt;url&gt; — video\n"
            "/search &lt;name&gt; — search\n"
            "/shazam — reply to a video\n"
            "/lang — change language\n"
            "/settings — settings\n"
            "/cookies — upload personal cookies (optional)\n"
            "/id — your ID\n"
            "/status — bot status\n\n"
            "💡 <i>Telegram rejects files over 50 MB — lower the quality in Settings.</i>"
        ),
        "settings_title": "⚙️ <b>Settings</b>",
        "settings_lang": "🌐 Language: <b>{lang}</b>",
        "settings_quality": "🎞 Video quality: <b>{quality}</b>",
        "btn_language": "🌐 Change language",
        "btn_quality": "🎞 Video quality",
        "choose_lang": "🌐 Choose a language:",
        "choose_quality": "🎞 Choose video quality:",
        "lang_saved": "✅ Language set to English",
        "quality_saved": "✅ Quality saved: {quality}",
        "status_text": (
            "📊 <b>Bot status</b>\n\n"
            "🟢 Status: <b>online</b>\n"
            "⏱ Uptime: <b>{uptime}</b>\n"
            "👥 Users: <b>{users}</b>\n"
            "⬇️ Total downloads: <b>{downloads}</b>\n"
            "🗄 Cached files: <b>{cached}</b>\n"
            "⚙️ yt-dlp: <code>{ytdlp}</code>\n"
            "🧩 Version: <code>{version}</code>"
        ),
        "analyzing": "{spinner} Checking the link...",
        "searching": "{spinner} Searching for <b>{query}</b>...",
        "downloading": "{spinner} <b>Downloading...</b>\n\n{bar} <b>{perc}%</b>\n⚡️ {speed} · ⏳ {eta}",
        "downloading_simple": "{spinner} <b>Downloading...</b>",
        "uploading": "📤 <b>Uploading to Telegram...</b>",
        "processing": "{spinner} Processing (metadata + cover art)...",
        "queue_wait": "⏳ Waiting in queue...",
        "search_results": "🔎 <b>“{query}”</b> — {total} results\n📄 Page <b>{page}/{pages}</b>\n\n<i>Tap a number — the MP3 lands instantly</i> 🎧",
        "search_empty": "😕 Nothing found. Try a different name.",
        "search_expired": "⌛️ This search has expired. Please search again.",
        "send_link_or_name": "🔗 Send a link or a song name.",
        "unsupported": "😕 I couldn't read that link. Try another one.",
        "error_generic": "⚠️ Something went wrong. Please try again shortly.",
        "error_too_large": "🐘 File too large (50 MB limit). Lower the quality in Settings.",
        "error_private": "🔒 This content is private. Uploading cookies may help (/cookies).",
        "error_age": "🔞 Age-restricted content. Upload account cookies via /cookies.",
        "error_unavailable": "🚫 Content unavailable (removed or region-locked).",
        "error_ratelimit": "🐌 The site is rate-limiting us. Try again in a minute or two.",
        "error_botcheck": "🤖 YouTube is running a bot check and asks to sign in. Please try again later — fresh admin cookies/proxy usually fix this.",
        "error_format": "🎞 No downloadable format was available for this link. Try another link, or come back a bit later.",
        "busy_user": "⏳ One download at a time — I'm fast, promise 😉",
        "from_cache": "⚡️ Served from cache (0 seconds of downloading!)",
        "carousel_caption": "🖼 {title}",
        "video_received": "🎬 <b>Video received!</b>\n\nWhat shall I do?",
        "shazam_working": "{spinner} Listening closely... 🎧",
        "shazam_found": "🎵 <b>Found it!</b>\n\n🎤 <b>{artist}</b>\n🎼 <b>{title}</b>",
        "shazam_notfound": "🤔 I couldn't name that tune. Try a louder, clearer snippet.",
        "shazam_hint": "🎬 Reply to a video with /shazam — or just send a video and I'll offer it.",
        "cookies_prompt": (
            "🍪 <b>Cookies</b>\n\n"
            "For restricted content, send a <code>cookies.txt</code> exported from "
            "your browser (Netscape format).\n"
            "It is stored encrypted 🔐\n\n"
            "Status: <b>{status}</b>"
        ),
        "cookies_status_on": "✅ uploaded",
        "cookies_status_off": "❌ not uploaded",
        "cookies_saved": "✅ Cookies saved ({total} cookies, {domains} domains).",
        "cookies_invalid": "❌ Invalid file: {error}",
        "cookies_deleted": "🗑 Cookies deleted.",
        "btn_delete_cookies": "🗑 Delete my cookies",
        "your_id": "🆔 Your ID: <code>{id}</code>",
        "admin_only": "⛔️ Admins only beyond this point.",
        "admin_panel_text": "🛠 <b>Admin panel</b>\n\nProxy, cookies, stats — switched live, no restarts.",
        "profile_reset_done": "♻️ Bot profile (name, descriptions, commands) re-applied from scratch in all languages ✅",
        "admin_no_url": "⚠️ PUBLIC_BASE_URL is not configured — can't show the Web App button.",
        "proxy_saved": "✅ Proxy updated: <code>{proxy}</code>",
        "proxy_cleared": "✅ Proxy cleared — direct connection.",
        "proxy_invalid": "❌ Invalid proxy format: {error}",
        "stats_text": (
            "📊 <b>Statistics</b>\n\n👥 Users: <b>{users}</b>\n"
            "⬇️ Downloads: <b>{downloads}</b>\n🗄 Cache: <b>{cached}</b> files\n"
            "⏱ Uptime: <b>{uptime}</b>\n🌐 Proxy: <code>{proxy}</code>"
        ),
        "maintenance_on": "🛠 The bot is under maintenance. Please check back soon 🙏",
        "page_prev": "⬅️",
        "page_next": "➡️",
        "btn_close": "✖️ Close",
        "results_for": "results",
        "track_ready": "🎵 Done!",
    },
}


def normalize_lang(code: str | None) -> str:
    """Map a Telegram language_code (e.g. 'ru-RU', 'uz') to a supported lang."""
    if not code:
        return DEFAULT_LANG
    short = code.lower().split("-")[0]
    return short if short in _STRINGS else "en"


def t(lang: str, key: str, **kwargs: object) -> str:
    """Translate ``key`` into ``lang`` and format it. Falls back gracefully."""
    template = _STRINGS.get(lang, _STRINGS[DEFAULT_LANG]).get(key)
    if template is None:
        template = _STRINGS["en"].get(key, key)
    return template.format(**kwargs) if kwargs else template
