"""
src/bot/onboarding.py
━━━━━━━━━━━━━━━━━━━━
Fluxo de onboarding para novos usuários.
Etapas: cadastro → perfil de carreira.

Nota: O fluxo de /set_key (BYOK Gemini) foi removido.
O pipeline agora usa LLM central (NVIDIA NIM + Groq) — sem necessidade de chave por usuário.
Código legado em: legacy/bot/key_router.py
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from src.db.users import upsert_user, set_career_profile, get_user
from src.bot.keyboards import main_menu_keyboard

logger = logging.getLogger(__name__)


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start — Cadastra o usuário e inicia o onboarding via Agente.
    """
    tg_user = update.effective_user
    user_id = tg_user.id

    result = upsert_user(
        user_id=user_id,
        first_name=tg_user.first_name or "",
        username=tg_user.username,
    )

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    from src.bot.agent import get_agent
    agent = get_agent(user_id)

    welcome_prompt = (
        f"[SISTEMA] O usuário {tg_user.first_name} acabou de dar /start. "
        "Dê as boas-vindas de forma calorosa. "
        "Explique que o bot busca vagas personalizadas automaticamente. "
        "Peça que o usuário envie seu resumo de carreira usando /set_profile."
    )
    response = await agent.chat_async(welcome_prompt)

    await update.message.reply_html(
        response,
        reply_markup=main_menu_keyboard() if result.get("onboarding_step") == "ready" else None
    )


async def handle_set_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /set_profile <career summary text>
    Salva o resumo de carreira e gera embeddings para o RAG.
    """
    user_id = update.effective_user.id
    text = " ".join(context.args).strip() if context.args else ""

    # Aceita texto multi-linha após o comando
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

        set_career_profile(user_id, career_summary=text, career_vectors=vectors)

        await update.message.reply_html(
            "✅ <b>Perfil configurado!</b>\n\n"
            "O CareerBot agora está pronto para buscar vagas personalizadas para você.\n\n"
            "Use /pipeline para iniciar uma busca agora, ou aguarde o agendamento automático.",
            reply_markup=main_menu_keyboard(),
        )
    except Exception as e:
        logger.error(f"Error building profile for user {user_id}: {e}")
        await update.message.reply_html(
            "❌ Erro ao gerar embeddings. Verifique se a chave GEMINI_API_KEY está configurada no servidor."
        )


async def handle_set_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /set_search — Inicia a configuração de busca de vagas via agente.

    O usuário descreve o que quer buscar em linguagem natural.
    O agente interpreta e chama update_search_config para salvar no banco.
    Na próxima execução do pipeline, as buscas usarão esses parâmetros.

    Exemplo:
        /set_search quero vagas de Engenheiro de Dados e Analytics Engineer em SP
    """
    user_id = update.effective_user.id
    text = " ".join(context.args).strip() if context.args else ""

    if not text:
        await update.message.reply_html(
            "🔍 <b>Configurar buscas de vagas</b>\n\n"
            "Me diga quais cargos e localização você quer buscar. Exemplo:\n\n"
            "<code>/set_search quero vagas de Engenheiro de Dados e Analytics Engineer "
            "em São Paulo, com remotas incluídas</code>\n\n"
            "Os defaults atuais estão em <code>src/jobs/config.py</code>."
        )
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    from src.bot.agent import get_agent
    agent = get_agent(user_id)

    prompt = (
        f"[SISTEMA] O usuário quer reconfigurar as buscas de vagas com o seguinte pedido:\n"
        f"\"{text}\"\n\n"
        "Sua missão:\n"
        "1. Interprete o pedido e monte um JSON de career_paths com name, queries[] e weight (1.0 default).\n"
        "2. Extraia a localização mencionada (default: 'São Paulo, Brazil').\n"
        "3. Chame a ferramenta update_search_config com career_paths_json (JSON string), "
        "locations (string CSV), include_remote e max_days_old.\n"
        "4. Confirme ao usuário o que foi salvo de forma clara e amigável.\n"
        "Importante: queries deve ter termos tanto em PT quanto em EN quando possível."
    )

    response = await agent.chat_async(prompt)
    await update.message.reply_html(response, reply_markup=None)
