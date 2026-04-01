"""
scripts/github_worker.py
━━━━━━━━━━━━━━━━━━━━━━━━
Master Background Worker para execuções Serverless Multi-Tenant (GitHub Actions).
Este script busca todos os usuários cadastrados com chave do Gemini ativa
e executa o pipeline individualmente para cada um deles.
"""

import sys
import os
import logging
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("BackgroundWorker")

from src.db.users import get_active_users
from src.pipeline import run_pipeline
from src.db.connection import get_conn


def run_all_tenants():
    """Busca todos os usuários ativos no Supabase e executa a esteira."""
    logger.info("=" * 60)
    logger.info("   🚀 INICIANDO BACKGROUND WORKER (MULTI-TENANT)")
    logger.info("=" * 60)
    
    target_user_id = os.environ.get("TARGET_USER_ID", "").strip()
    
    users = get_active_users()
    if not users:
        logger.warning("Nenhum usuário ativo com chave do Gemini encontrado.")
        return
        
    if target_user_id:
        logger.info(f"Filtro ativo: Executando apenas para o usuário {target_user_id}.")
        users = [u for u in users if str(u["user_id"]) == target_user_id]
        if not users:
            logger.warning(f"Usuário {target_user_id} não encontrado ou inativo.")
            return

    logger.info(f"Encontrados {len(users)} tenants para processamento.")
    
    for i, user in enumerate(users, start=1):
        user_id = user["user_id"]
        first_name = user["first_name"]
        
        logger.info(f"\n[Tenant {i}/{len(users)}] Iniciando Pipeline para {first_name} (ID: {user_id})...")
        
        try:
            # Roda as coletas, o RAG e a LLM de classificação injetando as chaves locais do tenant (via bot)
            # Mas o pipeline importa `get_user` e etc... tudo isolado pelo user_id!
            run_pipeline(user_id)
            
            # TODO: Aqui chamamos a conferência de Follow-ups ("lembretes de vagas interested")
            # process_follow_ups(user_id)
            
        except Exception as e:
            logger.error(f"❌ Erro fatal ao rodar pipeline para o tenant {user_id}: {e}")
            continue

    logger.info("=" * 60)
    logger.info("   ✅ BACKGROUND WORKER FINALIZADO")
    logger.info("=" * 60)

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    run_all_tenants()
