# ASTRA AI — 5 agentli Telegram tizimi + 360° 3D ishxona

## Tarkib
| Fayl | Vazifa |
|---|---|
| `astra_agents.py` | 5 bot + Topics routing + `/api/agents` |
| `static/index.html` | 360° interaktiv 3D ishxona |
| `render.yaml` | Render web service konfiguratsiyasi |

## Ishga tushirish
1. `pip install -r requirements.txt`
2. `.env.example` → `.env` va qiymatlarni to'ldiring
3. `python astra_agents.py` → http://localhost:8000

## Sozlash tartibi
1. @BotFather → `/mybots` → **API Token → Revoke** → yangi token oling
2. Supergroup oching → **Topics** yoqing
3. 5 mavzu: `Astra / Marketing / Dev / Mijozlar / Hisobotlar`
4. 5 botni guruhga qo'shing (Astra'ga topic boshqarish huquqi)
5. Har bir botga `/setprivacy` → **Disable** → guruhdan chiqarib **qayta qo'shing**
6. `TELEGRAM_GROUP_ID=0` bilan ishga tushiring, har topicda `/whereami` yuboring
7. `chat_id` va `thread_id` larni Environment'ga kiriting → redeploy

## Tekshirish
- `Dev` topicida savol → faqat **Dev** boti javob beradi
- 3D ishxonada agent yashil bo'ladi, `so'rov` va `bajarildi` oshadi
- Sichqoncha bilan to'liq 360° aylantirish ishlaydi

## Xavfsizlik
Tokenlar faqat Environment/Secrets orqali. Repoga hech qanday kalit yozilmaydi.
