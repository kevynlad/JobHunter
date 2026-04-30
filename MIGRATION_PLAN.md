# Plano de Migração: GitHub Actions → VPS (Oracle)

## Visão Geral

**Objetivo**: Migrar o JobHunter de GitHub Actions + Vercel para VPS (Oracle) com Docker, mantendo Blue/Green durante transição.

**Arquitetura Atual (GitHub Actions + Vercel + Supabase)**:
```
GitHub Actions (schedule 8h, 18h) → Vercel Functions → Supabase → Telegram
```

**Arquitetura Alvo (VPS Docker)**:
```
Docker Compose (VPS Oracle)
├── bot (Telegram)
├── pipeline (cron jobs)
├── worker (fila)
└── postgres (local, espelho Supabase)
         ↓
     Supabase (apenas DB, não Functions)
```

---

## Step-by-Step da Migração

### Fase 1: Preparação (Semana 1)

#### 1.1 Configurar VPS Oracle
- [ ] Criar instância sempre-gratuita (ARM ou x86)
- [ ] Configurar security groups (22, 80, 443, 5432)
- [ ] Instalar Docker + Docker Compose
- [ ] Configurar subdomain (ex: jobhunter.seudominio.com)

#### 1.2 Criar Dockerfiles e Compose
```yaml
# docker-compose.yml
services:
  bot:
    build: ./docker/bot
    ports:
      - "8000:8000"
    env_file: .env
    restart: unless-stopped

  pipeline:
    build: ./docker/pipeline
    env_file: .env
    restart: unless-stopped

  postgres:
    image: postgres:15
    volumes: ./data/postgres:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: jobhunter
      POSTGRES_USER: jobhunter
      POSTGRES_PASSWORD: ${DB_PASSWORD}
```

#### 1.3 Dockerizar o Bot
- Criar `Dockerfile.bot` baseado no atual entrypoint
- Expor porta para healthcheck
- Garantir que recebe webhooks do Telegram

#### 1.4 Dockerizar o Pipeline
- Criar `Dockerfile.pipeline`
- Script de entrypoint: `python -m scripts.github_worker`
- Suporte a múltiplos schedules (cron inside container)

### Fase 2: Migração do Banco (Semana 2)

#### 2.1 Espelhar Supabase → VPS
- dump do Supabase:
  ```bash
  pg_dump -h db.xxx.supabase.co -U postgres -d postgres > backup.sql
  ```
- Importar na VPS:
  ```bash
  psql -h localhost -U jobhunter -d jobhunter < backup.sql
  ```

#### 2.2 Configurar Replicação (opcional)
- Manter Supabase como backup durante Blue/Green
- Eventually sync para consistency

### Fase 3: Deploy na VPS (Semana 2-3)

#### 3.1 Deploy Inicial (ambientedev)
- Build das imagens
- Testar bot respondendo localmente
- Testar uma execução do pipeline manualmente

#### 3.2 Configurar DNS e SSL
- Nginx reverso com Let's Encrypt
- Health endpoints para monitoring

#### 3.3 Configurar Cron na VPS
```bash
# /etc/cron.d/jobhunter
0 8 * * * root docker exec jobhunter-pipeline-1 python -m scripts.github_worker
0 18 * * * root docker exec jobhunter-pipeline-1 python -m scripts.github_worker
```
**Ou**: Usar cron dentro do container com `cron` + `supervisord`

### Fase 4: Blue/Green (Semana 3-4)

#### 4.1 Rodar Ambos em Paralelo
- GitHub Actions continua executando (produção)
- VPS pipeline executa paralelamente (shadow mode)
- Comparar resultados por 1-2 semanas

#### 4.2 Validação
- Comparar scores RAG/LLM
- Verificar se vagas encontradas são equivalentes
- Testar bot na VPS manualmente

#### 4.3 Cutover
- Desabilitar schedule no GitHub Actions
- Promover VPS para produção
- Manter GitHub Actions como backup por 30 dias

---

## Refatorações Necessárias

### Prioridade 1: Multi-tenant correto

**Problema atual**: Queries hardcoded em `config.py`
**Solução**: Usar `search_config` do banco para todos usuários

```python
# src/jobs/matcher.py
def _get_user_search_config(user_id: int) -> dict:
    """Carregar config do banco, não do config.py"""
    user = get_user(user_id)
    if user and user.get("search_config"):
        return user["search_config"]
    # Fallback para default
    return DEFAULT_SEARCH_CONFIG
```

### Prioridade 2: Extrair config do código

**Arquivo**: `src/jobs/config.py` → migration config for database
- Career paths
- Locations
- Filters
- weights

**Tabela no banco**:
```sql
CREATE TABLE user_search_configs (
    user_id BIGINT PRIMARY KEY REFERENCES users(user_id),
    career_paths JSONB NOT NULL,
    locations JSONB NOT NULL,
    include_remote BOOLEAN DEFAULT true,
    max_days_old INTEGER DEFAULT 7,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Prioridade 3: Limpar dependências Vercel-specific

- Remover referências a `vercel.json` (não usado mais)
- Limpar código de fallback para "local file" do RAG
- Remover adaptações de `supabase-py` se migrar para postgres local

### Prioridade 4: Type hints e type safety

```python
# Antes
def score_job(job_description, user_id=None):

# Depois
def score_job(job_description: str, user_id: int | None = None) -> ScoreResult:
```

---

## Orquestração na VPS

### Opção A: Cron externo (recomendado simples)

```bash
# /etc/cron.d/jobhunter
0 8 * * * cd /opt/jobhunter && docker compose run --rm pipeline
0 18 * * * cd /opt/jobhunter && docker compose run --rm pipeline
```

### Opção B: Cron interno (Supervisord)

```ini
# supervisord.conf
[program:pipeline]
command = /bin/sh -c "while true; do python -m src.pipeline; sleep 43200; done"
```

### Opção C: Fila (mais robusto para scale)

```yaml
# docker-compose.yml
services:
  worker:
    build: ./docker/worker
    environment:
      - QUEUE=redis
```

**Escolha recomendada**: Opção A (cron externo) para iniciar, migrar para C se precisar scale.

---

## Checklist de Migração

### Preparação
- [ ] VPS Oracle configurada e acessível
- [ ] Docker + Docker Compose instalados
- [ ] Domínio DNS configurado
- [ ] SSL Let's Encrypt funcionando

### Código
- [ ] Dockerfiles criados (bot, pipeline)
- [ ] docker-compose.yml estruturado
- [ ] Variáveis de ambiente documentadas
- [ ] Health checks implementados

### Dados
- [ ] Dump do Supabase criado
- [ ] Restore no PostgreSQL da VPS
- [ ] Dados de users migrados
- [ ] career_vectors migrados

### Execução
- [ ] Pipeline testado manualmente na VPS
- [ ] Bot respondendo corretamente
- [ ] Cron jobs configurados

### Validação (Blue/Green)
- [ ] Resultados do GitHub Actions comparados com VPS
- [ ] Scores RAG equivalentes
- [ ] Vagas similares encontradas
- [ ] Notificações Telegram funcionando

### Cutover
- [ ] Schedule do GitHub Actions desabilitado
- [ ] VPS promoção para produção
- [ ] Monitoramento ativo por 30 dias

---

## Variáveis de Ambiente (Para documentar)

```bash
# Database
DATABASE_URL=postgresql://jobhunter:senha@localhost:5432/jobhunter

# Telegram
TELEGRAM_BOT_TOKEN=xxx

# Gemini (free tier)
GEMINI_FREE_API_KEY=xxx
GEMINI_PAID_API_KEY=xxx

# Supabase (backup/sync)
SUPABASE_URL=xxx
SUPABASE_SERVICE_KEY=xxx
```

---

## Riscos e Mitigações

| Risco | Mitigação |
|-------|-----------|
| Perda de dados na migração | Manter Supabase como source of truth por 30 dias |
| Jobs não rodar no schedule | Alerting + healthcheck na VPS |
| Performance degradada | Monitoramento + capacidade reserva |
| Rate limits no Gemini | Implementar retry com backoff |

---

## Próximos Passos

1. **Finalizar decisão**: Qual provedor VPS (Oracle Gratuito confirmado?)
2. **Setup VPS**: Criar instância e configurar acesso SSH
3. **Criar Dockerfiles**: Bot + Pipeline
4. **Primeiro deploy teste**: Apenas verificar se container sobe

---

*Documento vivo — atualizar conforme evolução do projeto*