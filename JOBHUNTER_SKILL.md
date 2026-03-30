---
name: jobhunter-architect
description: Diretrizes de arquitetura, segurança e limites para o projeto JobHunter (Multi-Tenant Serverless). Consute sempre esta skill ao implementar novas features.
risk: high
source: local
date_added: '2026-03-30'
---

# 🎯 JobHunter Multi-Tenant - Native Skill & Architecture Guide

Você é um Arquiteto de Software Sênior especializado em sistemas Serverless, Python Assíncrono e Integrações de LLMs (Gemini). Use esta skill sempre que trabalhar na base de código do **JobHunter** para garantir que as restrições de infraestrutura, segurança (BYOK), e orquestração sejam respeitadas.

## 🏗️ 1. Arquitetura do Sistema (Visão Geral)

O JobHunter passou de um script local síncrono para uma arquitetura descentralizada, dividida em dois grandes blocos:

### A. Vercel (Bot / Webhooks) - "O Atendente Rápido"
- **Função:** Receber os comandos do Telegram (`/start`, `/set_key`, `/set_profile`, botões).
- **Regra de Ouro:** A Vercel **MATA** qualquer requisição que dure mais do que 10 a 60 segundos (dependendo do plano).
- **Proibido:** NUNCA execute scraping (`jobspy`) ou chamadas pesadas do LLM (`gemini`) dentro do escopo da chamada da Vercel.
- **Padrão:** Receber o JSON do Telegram, salvar preferências no banco e devolver um `HTTP 200 OK` em menos de 3 segundos.

### B. GitHub Actions (Background Workers) - "O Trabalhador Braçal"
- **Função:** Rodar o `pipeline.py` completo (Scraping -> RAG -> Gemini LLM -> Notificação).
- **Limite:** Permite rodar de graça por até 6 horas ininterruptas.
- **Gatilho:** Agendamento Cron (Deploy) ou via `workflow_dispatch` (acionado pela Vercel).
- **Multiusuário:** Faz um isolamento via Loop: executa individualmente para cada `user_id` cadastrado e ativo.

---

## 🔐 2. Segurança e BYOK (Bring Your Own Key)

Como o sistema é multi-tenant, gerenciar chaves de API com segurança é a prioridade zero.

*   **Criptografia Obrigatória:** A chave de API do Gemini de cada usuário NUNCA deve ser salva em texto puro no Supabase.
*   **Mestre das Chaves:** O sistema usa a biblioteca `cryptography.fernet` com a variável ambiental `ENCRYPTION_MASTER_KEY` (injetada apenas na Vercel e no GitHub Actions) para criptografar/descriptografar chaves em voo.
*   **Fluxo de Inserção:** Usuário envia a chave no Telegram -> Vercel criptografa -> Salva no banco.
*   **Isolamento de Dados:** Cada vaga inserida na tabela `jobs` deve carregar obrigatoriamente a coluna `user_id`. Queries de leitura DEVEM filtrar pelo `user_id`. Falsificar acesso lateral é um erro gravíssimo.

---

## 🧠 3. Arquitetura da Chamada do Gemini API

A camada do LLM (`src/jobs/classifier.py`) é o coração inteligente da aplicação e a causa principal de *timeouts*. Siga estes mandamentos fielmente:

1.  **Chave API Dinâmica:** Diferente do modelo single_tenant, não existe um `genai.configure(api_key=...)` global! A cada iteração sobre uma vaga, você deve instanciar o cliente LLM (`genai.GenerativeModel`) especificamente injetando a chave do usuário atual em tempo de execução.
2.  **Identidade Dinâmica (RAG):** O bot não sabe quem é o usuário até ver o `user_id`. O `career_summary` (o Perfil e experiência do usuário) deve ser puxado ativamente do banco para o Prompt do Gemini. Se Kevyn é "Produto" e a namorada for "Backend", a nota da mesma vaga para os dois será radicalmente diferente.
3.  **Tolerância a Falhas (Resiliência):** O Gemini impõe *Rate Limits* (ex: "Resource Exhausted 429"). Como o Pipeline do GitHub roda um fluxo contínuo de centenas de vagas:
    *   Sempre envolva `model.generate_content()` em blocos `try/except`.
    *   Defina *retries* com `time.sleep` inteligente ou *Exponential Backoff* se esbarrar no limite por minuto.
    *   Exemplo: Se a API cair, a nota devolvida deve ser `0` e o `reasoning` deve explicar o *Error*. Não paralise o script por causa de uma falha de rede da API.

---

## 🔌 4. Gerenciamento Banco de Dados (Supabase/PostgreSQL)

-   **O Problema do Pooling:** No Railway o bot ficava ligado 24/7. No Serverless, o código "nasce" e "morre" a cada clique no Telegram.
-   **Regra em Serverless (Vercel):** Não use Connection Pooling duradouros (como `ThreadedConnectionPool`) em memória do Python se ele for re-instanciado a cada request HTTP. A conexão ao banco deve ser estabelecida, utilizada (Transação Completa ou Error Rollback) e FECHADA antes da Vercel retornar o Response.
-   **Anti-Queda (Worker):** No lado do GitHub Actions, que passa 2 horas rodando, o banco Supabase na nuvem costuma matar conexões "ociosas" enquanto o Python está rodando coisas lentas do LLM. Utilize a técnica implementada de *Pinging* (`SELECT 1`) e "Reconexão Transparente" antes de aplicar o `conn.commit()`.
-   **Dica Extra:** Prefira usar o link de conexão **Transaction Pooler** do Supabase (`porta 6543`) ao invés do Session.

---

## 🚧 5. Checklist de Nova Feature

Antes de criar qualquer nova feature no JobHunter, confira se não está quebrando esses alicerces:
- [ ] Eu coloquei algum `time.sleep()` ou processamento pesado (Scraping) no código que responde ao Webhook Vercel? *(Se sim, refatore e envie para a fila do GitHub Actions)*.
- [ ] Criei um fluxo que acessa os dados da tabela `user_api_configs`? *(Se sim, eu me certifiquei de usar a master key para o Fernet?)*
- [ ] A chamada do LLM está recebendo de fato as variáveis do usuário X ou caiu no _hardcoded_ de uma variável global?
- [ ] A conexão com o banco de dados tem tratamento adequado contra *stale connections* (Idle in transaction)?
