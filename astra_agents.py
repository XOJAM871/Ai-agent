#!/usr/bin/env python3
"""
ASTRA AI — 5 ta agent (Telegram Supergroup Topics) + 3D dashboard uchun API.

Ishga tushirish:
    pip install -r requirements.txt
    python astra_agents.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

import anthropic
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, filters,
)

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("astra")


# ---------------------------------------------------------------- Sozlamalar
def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} muhit o'zgaruvchisi kiritilmagan")
    return value


GROUP_ID = int(os.getenv("TELEGRAM_GROUP_ID", "0") or "0")
ANTHROPIC_MODEL = required("ANTHROPIC_MODEL")
llm = anthropic.AsyncAnthropic(api_key=required("ANTHROPIC_API_KEY"))


@dataclass(frozen=True)
class Agent:
    id: str
    name: str
    token_env: str
    topic_env: str
    prompt: str

    @property
    def token(self) -> str:
        return required(self.token_env)

    @property
    def thread_id(self) -> int:
        return int(os.getenv(self.topic_env, "0") or "0")


AGENTS = (
    Agent(
        "astra", "Astra", "BOT_ASTRA_TOKEN", "TOPIC_ASTRA_ID",
        "Siz Astra — bosh menejer agentsiz. Vazifalarni muvofiqlashtirasiz, "
        "topshiriqlarni agentlar o'rtasida taqsimlaysiz, har doim aniq, "
        "tuzilmali va o'zbek tilida javob berasiz.",
    ),
    Agent(
        "marketing", "Marketing", "BOT_MARKETING_TOKEN", "TOPIC_MARKETING_ID",
        "Siz marketing agentisiz. Strategiya, reklama, kontent-reja, SMM va "
        "auditoriya bo'yicha amaliy, o'lchanadigan tavsiyalar bering. "
        "Javoblaringizda KPI va byudjetni ko'rsating.",
    ),
    Agent(
        "dev", "Dev", "BOT_DEV_TOKEN", "TOPIC_DEV_ID",
        "Siz dasturlash agentisiz. Texnik yechimni xavfsiz, bosqichma-bosqich "
        "va ishlaydigan kod misollari bilan tushuntiring. Xavfsizlik "
        "masalalariga alohida e'tibor bering.",
    ),
    Agent(
        "support", "Mijozlar", "BOT_SUPPORT_TOKEN", "TOPIC_SUPPORT_ID",
        "Siz mijozlar bilan ishlash agentisiz. Xushmuomala, lo'nda va "
        "muammoni yechishga yo'naltirilgan javob bering. Zarur bo'lsa "
        "qadam-baqadam yo'riqnoma bering.",
    ),
    Agent(
        "reports", "Hisobotlar", "BOT_REPORTS_TOKEN", "TOPIC_REPORTS_ID",
        "Siz hisobotlar agentisiz. Ma'lumotni jadval va ro'yxat ko'rinishida, "
        "aniq raqamlar bilan taqdim eting va qisqa xulosa yozing.",
    ),
)


# --------------------------------------------------------------- Ma'lumotlar
db_path = Path(os.getenv("ASTRA_DB_PATH", "data/astra.sqlite3"))
db_path.parent.mkdir(parents=True, exist_ok=True)
DB = sqlite3.connect(db_path, check_same_thread=False)
DB.row_factory = sqlite3.Row
DB.execute("PRAGMA journal_mode=WAL")
DB.execute("""
    CREATE TABLE IF NOT EXISTS agent_stats (
        id        TEXT PRIMARY KEY,
        name      TEXT NOT NULL,
        requests  INTEGER NOT NULL DEFAULT 0,
        completed INTEGER NOT NULL DEFAULT 0,
        errors    INTEGER NOT NULL DEFAULT 0,
        online    INTEGER NOT NULL DEFAULT 0,
        last_seen REAL    NOT NULL DEFAULT 0
    )
""")
for _agent in AGENTS:
    DB.execute(
        "INSERT OR IGNORE INTO agent_stats (id, name) VALUES (?, ?)",
        (_agent.id, _agent.name),
    )
DB.commit()
DB_LOCK = asyncio.Lock()


async def db_exec(sql: str, params: tuple = ()) -> None:
    async with DB_LOCK:
        DB.execute(sql, params)
        DB.commit()


async def set_presence(agent_id: str, online: bool) -> None:
    await db_exec(
        "UPDATE agent_stats SET online = ?, last_seen = ? WHERE id = ?",
        (int(online), time.time(), agent_id),
    )


async def bump(agent_id: str, column: str, step: int = 1) -> None:
    # Ustun nomi faqat shu allowlist'dan olinadi (SQL injection oldini oladi).
    if column not in {"requests", "completed", "errors"}:
        raise ValueError(f"noto'g'ri ustun: {column}")
    await db_exec(
        f"UPDATE agent_stats SET {column} = {column} + ? WHERE id = ?",
        (step, agent_id),
    )


# -------------------------------------------------------------------- API
api = FastAPI(title="ASTRA API", docs_url=None, redoc_url=None)


def _shape(row: sqlite3.Row) -> dict:
    now = time.time()
    return {
        "id": row["id"],
        "name": row["name"],
        "online": bool(row["online"]) and (now - float(row["last_seen"])) < 65,
        "requests": row["requests"],
        "tasks_completed": row["completed"],
        "errors": row["errors"],
        "last_seen": row["last_seen"] or None,
    }


@api.get("/healthz")
async def healthz():
    return {"ok": True, "group_id": GROUP_ID}


@api.get("/api/agents")
async def agents_status():
    async with DB_LOCK:
        rows = DB.execute("SELECT * FROM agent_stats").fetchall()
    order = {a.id: i for i, a in enumerate(AGENTS)}
    rows = sorted(rows, key=lambda r: order.get(r["id"], 99))
    return {"agents": [_shape(r) for r in rows], "group_id": GROUP_ID}


@api.get("/api/agents/{agent_id}")
async def agent_status(agent_id: str):
    async with DB_LOCK:
        row = DB.execute(
            "SELECT * FROM agent_stats WHERE id = ?", (agent_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Agent topilmadi")
    return _shape(row)


# 3D interfeys (static/index.html) — API route'lardan KEYIN ulanadi.
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.is_dir():
    api.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


# -------------------------------------------------------------------- Botlar
def current_agent(context: ContextTypes.DEFAULT_TYPE) -> Agent:
    return context.application.bot_data["agent"]


def is_agent_topic(update: Update, agent: Agent) -> bool:
    chat, msg = update.effective_chat, update.effective_message
    return (
        GROUP_ID != 0
        and agent.thread_id > 0
        and chat is not None
        and msg is not None
        and chat.id == GROUP_ID
        and msg.message_thread_id == agent.thread_id
    )


async def send_topic(
    context: ContextTypes.DEFAULT_TYPE,
    agent: Agent,
    text: str,
    reply_to: int | None = None,
) -> None:
    """Telegram 4096 belgi limitidan kichik bo'laklarga bo'lib yuboradi."""
    chunks = [text[i:i + 3900] for i in range(0, len(text), 3900)] or [text]
    for i, chunk in enumerate(chunks):
        await context.bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=agent.thread_id,
            text=chunk,
            reply_to_message_id=reply_to if i == 0 else None,
        )


async def cmd_whereami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """chat_id va thread_id ni aniqlash uchun: topic ichida /whereami."""
    msg, chat = update.effective_message, update.effective_chat
    if msg is None or chat is None:
        return
    await msg.reply_text(
        f"chat_id = {chat.id}\nthread_id = {msg.message_thread_id or 0}"
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agent = current_agent(context)
    msg = update.effective_message
    if msg is None:
        return
    chat = update.effective_chat
    if chat and chat.type == "private":
        await msg.reply_text(
            f"🤖 {agent.name} agenti tayyor.\n"
            f"Vazifa: {agent.prompt.splitlines()[0][:120]}...\n\n"
            f"Guruhdagi o'z mavzusida yozing."
        )
    elif is_agent_topic(update, agent):
        await send_topic(context, agent, f"✅ {agent.name} agenti faol.", msg.message_id)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agent = current_agent(context)
    msg = update.effective_message
    if msg is None or not is_agent_topic(update, agent):
        return
    async with DB_LOCK:
        row = DB.execute(
            "SELECT * FROM agent_stats WHERE id = ?", (agent.id,)
        ).fetchone()
    s = _shape(row)
    await send_topic(
        context,
        agent,
        f"📊 {agent.name}\n"
        f"Holat: {'🟢 faol' if s['online'] else '⚪ nofaol'}\n"
        f"So'rovlar: {s['requests']}\n"
        f"Bajarilgan vazifalar: {s['tasks_completed']}\n"
        f"Xatolar: {s['errors']}",
        msg.message_id,
    )


async def ask_agent(agent: Agent, text: str) -> str:
    response = await llm.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1200,
        system=agent.prompt,
        messages=[{"role": "user", "content": text}],
    )
    answer = "\n".join(
        block.text for block in response.content
        if getattr(block, "type", "") == "text"
    ).strip()
    return answer or "Javob tayyorlanmadi."


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agent = current_agent(context)
    msg = update.effective_message
    if (
        msg is None
        or not msg.text
        or msg.from_user is None
        or msg.from_user.is_bot
        or not is_agent_topic(update, agent)
    ):
        return

    await bump(agent.id, "requests")
    try:
        await context.bot.send_chat_action(
            chat_id=GROUP_ID,
            message_thread_id=agent.thread_id,
            action=ChatAction.TYPING,
        )
        answer = await ask_agent(agent, msg.text[:12000])
        await send_topic(context, agent, answer, msg.message_id)
        await bump(agent.id, "completed")
    except Exception:
        log.exception("%s agentida vazifa bajarilmadi", agent.id)
        await bump(agent.id, "errors")
        try:
            await send_topic(
                context, agent,
                "⚠️ So'rovni bajarishda xatolik yuz berdi. "
                "Administrator loglarni tekshirsin.",
                msg.message_id,
            )
        except Exception:
            log.exception("xato xabarini guruhga yuborib bo'lmadi")


def build_application(agent: Agent) -> Application:
    app = Application.builder().token(agent.token).build()
    app.bot_data["agent"] = agent
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("whereami", cmd_whereami))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app


async def heartbeat(agent: Agent) -> None:
    while True:
        try:
            await set_presence(agent.id, True)
        except Exception:
            log.exception("%s heartbeat xatosi", agent.id)
        await asyncio.sleep(20)


async def run_agent(agent: Agent) -> None:
    """Botni ishga tushiradi; xato bo'lsa 5 soniyadan keyin qayta urinadi."""
    while True:
        app = None
        initialized = started = polling = False
        pulse = None
        try:
            app = build_application(agent)
            await app.initialize()
            initialized = True
            await app.start()
            started = True
            if app.updater is None:
                raise RuntimeError("Telegram updater topilmadi")
            await app.updater.start_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=False,
            )
            polling = True
            await set_presence(agent.id, True)
            pulse = asyncio.create_task(heartbeat(agent))
            log.info(
                "✅ %s polling boshlandi (topic=%s)",
                agent.id, agent.thread_id or "sozlanmagan",
            )
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("❌ %s ishga tushmadi — 5 s dan keyin qayta urinish", agent.id)
        finally:
            if pulse:
                pulse.cancel()
                await asyncio.gather(pulse, return_exceptions=True)
            if polling and app and app.updater:
                try:
                    await app.updater.stop()
                except Exception:
                    log.exception("%s updater to'xtamadi", agent.id)
            if started and app:
                try:
                    await app.stop()
                except Exception:
                    log.exception("%s application to'xtamadi", agent.id)
            if initialized and app:
                try:
                    await app.shutdown()
                except Exception:
                    log.exception("%s application yopilmadi", agent.id)
            try:
                await set_presence(agent.id, False)
            except Exception:
                log.exception("%s offline holatini yozib bo'lmadi", agent.id)

        await asyncio.sleep(5)


async def main() -> None:
    tasks = [
        asyncio.create_task(run_agent(agent), name=f"bot-{agent.id}")
        for agent in AGENTS
    ]
    server = uvicorn.Server(
        uvicorn.Config(
            api,
            host="0.0.0.0",
            port=int(os.getenv("PORT", "8000")),
            log_level="info",
        )
    )
    try:
        await server.serve()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
