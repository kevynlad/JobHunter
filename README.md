# 🎯 JobHunter — Agentic AI Recruiter

**O seu "Agente Autônomo": Varre, rastreia, pontua e notifica as melhores oportunidades direto no seu Telegram.**

O JobHunter ultrapassa os limites de um simples scraper. Ele é uma inteligência artificial agêntica que lê o mercado (LinkedIn, Gupy, Indeed), cruza cada vaga com o seu currículo através de Embeddings (RAG Ultraleve) e raciocina profundamente usando LLMs (Gemini). Ele elimina vagas ruins e envia os "Top Matches" num Bot de Telegram com botões interativos para Aplicações rápidas, Cover Letters instantâneas e resiliência de memória.

---

## ✨ Features Profissionais

- 🖱️ **Telegram UI (Inline Buttons):** Controle total pelo chat. Ao receber um match perfeito, utilize botões integrados para marcar `[✅ Quero Aplicar]`, gerar `[📝 Cover Letter]`, agendar `[⏰ Lembretes]` ou descartar, atualizando seu banco de dados na nuvem sem precisar digitar um comando.
- 🚦 **Hybrid Cost Routing (Free vs Paid):** Escala massiva com custo zero. O JobHunter inteligentemente usa chaves gratuitas do Gemini (Flash-Lite) para escaneamento inicial "sujo", e direciona chaves Pagas limitadas (via Google AI Studio) estritamente para análises de Fit detalhadas com Modelos Premium, assegurando que você extraia o máximo sem exaurir recursos (Denial of Wallet protection).
- 🧠 **Server-less Vector RAG:** A dependência gigante do ChromaDB foi superada! Agora, todo o processo de Extração e Comparação de Sentido Oculto (RAG) é feito nativamente pela API de Embeddings do Gemini, livrando a máquina local de centenas de Mbs e permitindo deploys mais eficientes e baratos.
- 🔗 **Análises On-Demand por URL:** Viu uma vaga perfeita pelo celular? É só colar o link para o Agente no Telegram. A Inteligência (Tools) acessa a URL, processa os dados invisíveis, te dá a nota e arquiva pro seu histórico sem disparar pipelines massivos.
- 🛡️ **DevSecOps Integrado:** Nascido pronto pra produção. Contêineres em Docker processados sem vulnerabilidades Root e requisições HTTP travadas contra Server-Side Request Forgery (SSRF). Privilégio zero, segurança máxima.

---

## ⚡ Como Funciona a Pipeline?

```text
    Mercado (Web)             Vector Embeddings       LLM Reasoning             Você
  ┌────────────┐         ┌────────────────┐      ┌─────────────┐     ┌───────────┐
  │ JobSpy Web │──scrape─│ Gemini API SDK │─RAG──│ Gemini Free/│─────│ Telegram  │
  │ (LinkedIn) │         │ (Zero-Storage) │      │ Paid Router │     │ Agent Bot │
  └────────────┘         └────────────────┘      └─────────────┘     └───────────┘
```

A arquitetura moderna foi pensada para Cloud. O seu `Bot` deve rodar no Railway hospedando o Banco SQLite de memória, enquanto o pesado GitHub Actions pode rodar a esteira diária sem exaurir a sua hospedagem paga.

---

## 🚀 Quick Start (Deploy via Railway)

### 1. Clonar & Pré-Requisitos
```bash
git clone https://github.com/kevynlad/JobHunter.git
cd JobHunter
```

### 2. Configurar o Setup
Copie os modelos do ambiente:
```bash
cp .env.example .env
cp career_summary.example.txt career_summary.txt
```

Preencha seu `.env` com a sua malha de chaves (`GEMINI_API_KEYS` separadas por vírgula pro uso gratuito e sua chave principal paga para funções Premium do bot).
Adicione as informações de Identidade no seu arquivo estruturado na pasta `data/career/`.

### 3. Subir e Rodar
A aplicação já possui os arquivos `Dockerfile` seguro e `railway.toml`. Sincronize com o GitHub, crie o seu projeto no painel do [Railway](https://railway.app), e lembre-se de criar um **Persistent Volume** vinculando a pasta raiz `/app/data/` para que o seu SQLite (`jobs.db`) nunca evapore entre builds.

Caso queira usar apenas no seu PC (Modo Legado CLI):
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .
python -m src.pipeline
```

---

## ⌨️ Interface CLI
Além de você operar interativamente toda a vida digital de recrutamento pelo celular no Telegram, os comandos para uso via terminal permanecem vivos:

```bash
python -m src.cli stats           # 📊 Resumo diário de todas as vagas mapeadas
python -m src.cli new             # 🆕 Vagas prontas para agir
python -m src.cli run             # 🚀 Dá Start a força no Scraper
```

---

## 🗺️ Roadmap Atualizado

O limite para o Agente está longe. Próximas missões de Arquitetura:
- [ ] **SaaS Multi-Tenant:** Migrar do conceito Mono-User para escalada onde cada usuário interage apenas com o seu banco, com os próprios documentos RAG e parâmetros.
- [ ] **Cloud Database Native:** Substituir por definitivo a dependência SQLite volumétrica isolada e escalar os profiles multi-usuários em um SQLaaS tipo Turso ou Neon de baixa latência.
- [ ] **Agentic Crawler:** Substituir os recortes brutos de scraping pela delegação visual direta de um Browser-Use Agent para extrair dados sem limites de captcha.

---

## 📝 License

MIT — Hackeie de volta a sua busca de emprego.
