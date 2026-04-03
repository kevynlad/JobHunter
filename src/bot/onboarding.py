"""
src/bot/onboarding.py
━━━━━━━━━━━━━━━━━━━━
Fluxo de onboarding para novos usuários.
Guia o usuário pelas etapas: cadastro → chave Gemini → perfil de carreira.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from src.db.users import upsert_user, set_user_keys, get_user
from src.bot.keyboards import main_menu_keyboard

logger = logging.getLogger(__name__)


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start — Cadastra o usuário e inicia o onboarding CONVERSACIONAL via Agente.
    """
    tg_user = update.effective_user
    user_id = tg_user.id

    # Upsert user (registration)
    result = upsert_user(
        user_id=user_id,
        first_name=tg_user.first_name or "",
        username=tg_user.username,
    )

    # Show typing indicator
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    # Delegate the welcome to the agent
    from src.bot.agent import get_agent
    agent = get_agent(user_id)
    
    # Internal trigger to start onboarding dialogue
    welcome_prompt = (
        f"[SISTEMA] O usuário {tg_user.first_name} acabou de dar /start. "
        "Dê as boas-vindas de forma calorosa e inicie o onboarding conversacional, "
        "explicando a necessidade das chaves API Gemini."
    )
    response = await agent.chat_async(welcome_prompt)

    await update.message.reply_html(
        response,
        reply_markup=main_menu_keyboard() if result.get("onboarding_step") == "ready" else None
    )


async def _send_welcome_new(update: Update, name: str):
    await update.message.reply_html(
        f"Oi, <b>{name}</b>! 👋 Seja bem-vindo ao <b>CareerBot</b>.\n\n"
        "Para começar, você precisa configurar sua chave da API do Gemini (Google AI).\n\n"
        "<b>Como obter sua chave gratuita:</b>\n"
        "1. Acesse: <a href='https://aistudio.google.com/app/apikey'>aistudio.google.com</a>\n"
        "2. Clique em <b>Create API Key</b>\n"
        "3. Copie a chave (começa com <code>AIza...</code>)\n\n"
        "Depois, envie aqui no formato:\n"
        "<code>/set_key AIzaSy...</code>"
    )


async def _send_setup_profile(update: Update, name: str):
    await update.message.reply_html(
        f"Boa, <b>{name}</b>! Chave configurada ✅\n\n"
        "Agora envie seu <b>resumo de carreira</b> para eu personalizar as buscas.\n\n"
        "Pode ser um texto livre descrevendo:\n"
        "• Sua experiência e habilidades\n"
        "• Tipos de vaga que busca\n"
        "• Preferências (remoto, híbrido, senioridade)\n\n"
        "Use o comando: <code>/set_profile SEU TEXTO AQUI</code>"
    )


def _missing_keys(user_id: int) -> bool:
    try:
        user = get_user(user_id)
        return user is None or not user.get("gemini_free_key")
    except Exception:
        return True


async def handle_set_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /set_key AIzaSy... [AIzaSy_paid...]
    Sets free key (required) and optionally paid key.
    """
    user_id = update.effective_user.id
    args = context.args

    if not args:
        await update.message.reply_html(
            "Uso: <code>/set_key CHAVE_FREE [CHAVE_PAID]</code>\n\n"
            "A CHAVE_PAID é opcional (usa conta de pagamento para melhor qualidade)."
        )
        return

    free_key = args[0].strip()
    paid_key = args[1].strip() if len(args) > 1 else None

    if free_key.startswith("[") and free_key.endswith("]"):
        free_key = free_key[1:-1].strip()
    if paid_key and paid_key.startswith("[") and paid_key.endswith("]"):
        paid_key = paid_key[1:-1].strip()

    if not free_key.startswith("AIza"):
        await update.message.reply_html(
            "❌ Chave inválida. Deve começar com <code>AIza...</code>\n"
            "Obtenha em: <a href='https://aistudio.google.com/app/apikey'>aistudio.google.com</a>"
        )
        return

    try:
        set_user_keys(user_id, free_key=free_key, paid_key=paid_key)
        # Delete the message with the key for security
        try:
            await update.message.delete()
        except Exception:
            pass

        await update.effective_chat.send_message(
            "✅ <b>Chave configurada e salva com segurança!</b>\n\n"
            "Agora envie seu resumo de carreira:\n"
            "<code>/set_profile SEU TEXTO AQUI</code>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error setting key for user {user_id}: {e}")
        await update.message.reply_html("❌ Erro ao salvar a chave. Tente novamente.")


async def handle_set_keys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /set_keys — Alias for /set_key (plural variant).
    Some users naturally type /set_keys. Both commands do the same thing.
    """
    await handle_set_key(update, context)


async def handle_set_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /set_profile <career summary text>
    Saves career summary and triggers vector rebuild.
    """
    user_id = update.effective_user.id
    text = " ".join(context.args).strip() if context.args else ""

    # Also accept multi-line text after command
    if not text and update.message.text:
        parts = update.message.text.split(None, 1)
        text = parts[1].strip() if len(parts) > 1 else ""

    if len(text) < 100:
        await update.message.reply_html(
            "❌ Resumo muito curto. Descreva sua experiência em pelo menos 100 caracteres.\n\n"
            "Exemplo:\n"
            "<code>/set_profile Sou analista de dados com 2 anos de experiência em SQL, "
            "Python e Power BI. Busco vagas de Analista de Dados ou Product Ops em SP, "
            "preferencialmente híbrido.</code>"
        )
        return

    await update.message.reply_html("⏳ Salvando seu perfil e gerando embeddings...")

    try:
        from src.rag.ingest import build_vector_db_for_user
        vectors = await build_vector_db_for_user(user_id, career_text=text)

        from src.db.users import set_career_profile
        set_career_profile(user_id, career_summary=text, career_vectors=vectors)

        from src.bot.keyboards import main_menu_keyboard
        await update.message.reply_html(
            "✅ <b>Perfil configurado!</b>\n\n"
            "O CareerBot agora está pronto para buscar vagas personalizadas para você.\n\n"
            "Use /pipeline para iniciar uma busca agora, ou aguarde o agendamento automático.",
            reply_markup=main_menu_keyboard(),
        )
    except Exception as e:
        logger.error(f"Error building profile for user {user_id}: {e}")
        await update.message.reply_html(
            "❌ Erro ao gerar embeddings. Verifique sua chave Gemini com /set_key"
        )
