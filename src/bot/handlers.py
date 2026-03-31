"""
CareerBot — Telegram Message & Callback Handlers

Handles incoming messages and button clicks.
Every text message goes to the Gemini agent.
Button callbacks are mapped to specific actions.
"""
import os
import json
import logging
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

from src.bot.agent import get_agent
from src.bot.keyboards import (
    applied_followup_keyboard,
    main_menu_keyboard,
)
from src.bot.tools import update_job_status, get_recent_jobs, get_application_stats


async def handle_pipeline_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /pipeline — Dispatches the job pipeline.
    In the Serverless architecture, this no longer runs the pipeline directly
    to avoid Vercel timeouts. Instead, it triggers a GitHub Action (or a message
    simulating that trigger) which will process jobs for 4+ hours.
    """
    logger.info(f"User {update.effective_user.id} triggered /pipeline")
    
    await update.message.reply_html(
        "⚡ <b>Pipeline Despachado (Modo Nuvem)!</b>\n\n"
        "A solicitação foi enviada para nossos servidores de background (GitHub Actions).\n"
        "O processo de busca e classificação pelo LLM pode demorar algumas horas.\n"
        "Você receberá uma mensagem automática aqui quando as novas vagas forem encontradas!"
    )
    
    # TODO: FUTURE - Implement httpx POST to GitHub Actions workflow_dispatch API
    # import httpx
    # async with httpx.AsyncClient() as client:
    #     await client.post("https://api.github.com/repos/user/repo/actions/workflows/pipeline.yml/dispatches", ...)



async def handle_debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /debug — Testa a conexão ao banco e retorna o erro real (para debugging).
    REMOVER ANTES DE PRODUÇÃO PÚBLICA.
    """
    import traceback
    import os
    user_id = update.effective_user.id
    lines = [f"🔍 <b>Debug Report</b> | user_id: <code>{user_id}</code>\n"]

    # 1. Checar variáveis de ambiente
    db_url = os.environ.get("DATABASE_URL", "❌ NÃO DEFINIDA")
    enc_key = os.environ.get("ENCRYPTION_MASTER_KEY", "❌ NÃO DEFINIDA")
    lines.append(f"DATABASE_URL: <code>{'✅ definida' if 'postgresql' in db_url else db_url}</code>")
    lines.append(f"ENCRYPTION_MASTER_KEY: <code>{'✅ definida' if enc_key != '❌ NÃO DEFINIDA' else enc_key}</code>\n")

    # 2. Testar conexão ao banco
    try:
        from src.db.connection import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM jobs WHERE user_id = %s", (user_id,))
                count = cur.fetchone()[0]
        lines.append(f"✅ <b>Banco OK!</b> {count} vagas encontradas para seu user_id.")
    except Exception:
        tb = traceback.format_exc()
        lines.append(f"❌ <b>Erro ao conectar ao banco:</b>\n<pre>{tb[-1000:]}</pre>")

    # 3. Testar chave Gemini
    try:
        from src.bot.key_router import get_key
        key = get_key("paid", user_id)
        lines.append(f"✅ <b>Chave Gemini OK:</b> <code>{key[:8]}...</code>")
    except Exception as e:
        lines.append(f"❌ <b>Erro na chave Gemini:</b> <code>{e}</code>")

    await update.message.reply_html("\n".join(lines))


async def handle_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /stats — Debug command to show raw database numbers directly.
    """
    user_id = update.effective_user.id
    stats_json = get_application_stats(user_id=user_id)
    try:
        stats = json.loads(stats_json)
        total = stats.get("total_analyzed", 0)
        by_status = stats.get("by_status", {})
        
        text = f"📊 <b>Raw Database Stats:</b>\n\nTotal jobs in DB: {total}\n"
        for status, count in by_status.items():
            text += f"- {status}: {count}\n"
            
        await update.message.reply_html(text)
    except Exception as e:
        await update.message.reply_html(f"Error parsing stats: {e}")



async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle any text message from the user.
    Routes directly to the Gemini agent — no commands needed.
    """
    user = update.effective_user
    user_id = user.id
    text = update.message.text

    # Show typing indicator while agent processes
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    agent = get_agent(user_id)
    response = await agent.chat_async(text)

    await update.message.reply_text(
        response,
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),  # Always show quick-access buttons
    )





async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle button clicks (inline keyboard callbacks).
    Format: "action:job_id" or "menu:section"
    """
    query = update.callback_query
    await query.answer()  # Acknowledge the click (removes loading spinner)

    data = query.data
    user_id = query.from_user.id
    agent = get_agent(user_id)

    if data.startswith("apply:"):
        job_id = data.split(":", 1)[1]
        update_job_status(job_id=job_id, status="interested")
        response = await agent.chat_async(
            f"[SISTEMA INTERNO] O usuário clicou no botão 'Quero Aplicar' na vaga ID={job_id}.\n"
            f"Sua missão agora:\n"
            f"1. IMPORTANTE: Use a ferramenta 'learn_from_job' no ID={job_id} para extrair as "
            f"competências que o usuário achou legal nesta vaga e injetar no cérebro V2.\n"
            f"2. Confirme ao usuário que a vaga foi salva como 'interessante'.\n"
            f"3. Ofereça gerar a Cover Letter."
        )
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_html(response, reply_markup=main_menu_keyboard())

    elif data.startswith("cover:"):
        job_id = data.split(":", 1)[1]
        # Trigger cover letter generation (handled by cv_generator)
        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_chat_action(
            chat_id=query.message.chat_id, action="typing"
        )
        # Import here to avoid circular imports
        from src.bot.cv_generator import generate_cover_letter_pdf
        await generate_cover_letter_pdf(
            bot=context.bot,
            chat_id=query.message.chat_id,
            job_id=job_id,
            user_id=user_id,
        )

    elif data.startswith("remind:"):
        job_id = data.split(":", 1)[1]
        update_job_status(job_id=job_id, status="interested")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_html(
            "⏰ Anotado! Vou te lembrar dessa vaga em 3 dias. 👍"
        )

    elif data.startswith("skip:"):
        job_id = data.split(":", 1)[1]
        update_job_status(job_id=job_id, status="skipped")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("❌ Vaga ignorada.")

    elif data.startswith("applied:"):
        job_id = data.split(":", 1)[1]
        update_job_status(job_id=job_id, status="applied")
        await query.edit_message_reply_markup(reply_markup=None)
        response = await agent.chat_async(
            f"[SISTEMA INTERNO] O usuário clicou no botão 'Já Apliquei' na vaga ID={job_id}.\n"
            f"IMPORTANTE: Use a ferramenta 'learn_from_job' com esse ID para registrar esse perfil "
            f"como o 'padrão ouro' de vagas do usuário. Depois, parabenize-o pela aplicação."
        )
        await query.message.reply_html(response)

    elif data == "menu:recent":
        response = await agent.chat_async(
            "Me mostra as melhores vagas encontradas nos últimos 7 dias."
        )
        await query.message.reply_html(response, reply_markup=main_menu_keyboard())

    elif data == "menu:status":
        response = await agent.chat_async(
            "Me dá um resumo das minhas aplicações e o status de cada uma."
        )
        await query.message.reply_html(response, reply_markup=main_menu_keyboard())

    elif data == "menu:pipeline":
        response = await agent.chat_async(
            "Quais vagas eu marquei como interessante mas ainda não apliquei?"
        )
        await query.message.reply_html(
            response,
            reply_markup=main_menu_keyboard()
        )

    elif data == "menu:cover":
        response = await agent.chat_async(
            "O usuário quer gerar uma cover letter. Pergunte para qual vaga."
        )
        await query.message.reply_html(response, reply_markup=main_menu_keyboard())
