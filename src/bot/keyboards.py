"""
CareerBot — Inline Keyboard Definitions

Quick-access buttons that appear on job notifications
and in the main menu.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def job_notification_keyboard(job_id: str) -> InlineKeyboardMarkup:
    """
    Buttons shown on every job notification card.
    The agent handles the logic; these are just shortcuts.
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Quero Aplicar", callback_data=f"apply:{job_id}"),
            InlineKeyboardButton("📝 Cover Letter", callback_data=f"cover:{job_id}"),
        ],
        [
            InlineKeyboardButton("⏰ Lembrar em 3 dias", callback_data=f"remind:{job_id}"),
            InlineKeyboardButton("❌ Não interessa", callback_data=f"skip:{job_id}"),
        ],
    ])


def applied_followup_keyboard(job_id: str) -> InlineKeyboardMarkup:
    """Buttons shown on follow-up messages after the user said they'd apply."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Sim, apliquei!", callback_data=f"applied:{job_id}"),
            InlineKeyboardButton("⏰ Ainda vou aplicar", callback_data=f"remind:{job_id}"),
        ],
        [
            InlineKeyboardButton("❌ Desisti dessa vaga", callback_data=f"skip:{job_id}"),
        ],
    ])


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Quick-access menu available at any time."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎯 Ver vagas da semana", callback_data="menu:recent"),
            InlineKeyboardButton("📊 Meu status", callback_data="menu:status"),
        ],
        [
            InlineKeyboardButton("📋 Aplicações pendentes", callback_data="menu:pipeline"),
            InlineKeyboardButton("📝 Gerar cover letter", callback_data="menu:cover"),
        ],
    ])
