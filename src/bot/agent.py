"""
CareerBot — Gemini Conversational Agent

This is the brain of the CareerBot. It uses Gemini with:
- Context Caching: your career profile is cached for the session
- Function Calling: Gemini decides when to query the jobs database
- Conversation history: multi-turn dialogue within a session

The agent does NOT make decisions for the user — it informs,
prepares, and reminds. All actions are triggered by user input.
"""
import os
import json
from pathlib import Path

from google import genai
from google.genai import types

import os
from src.bot.tools import TOOL_DECLARATIONS, TOOL_EXECUTOR


# Load career profile for system context
CAREER_PATH = Path(__file__).parent.parent.parent / "data" / "career"
DB_PATH = Path(__file__).parent.parent.parent / "data" / "jobs.db"


def _load_career_profile(user_id: int) -> str:
    """Load career profile from the database for the given user."""
    from src.db.users import get_user
    user = get_user(user_id)
    if user and user.get("career_summary"):
        return user["career_summary"]
    return ""  # Empty means onboarding is needed — agent will detect and guide.


SYSTEM_PROMPT = """«CONFIGURAÇÃO DO SISTEMA»
Você é o CareerBot, assistente de carreira pessoal.

PERFIL DO USUÁRIO:
{career_profile}

«FERRAMENTAS DISPONÍVEIS»

1. BUSCA E USO DE VAGAS:
   - get_recent_jobs(days, limit): vagas recentes do banco.
   - get_job_detail(job_id/company/title): detalhes de uma vaga.
   - update_job_status(job_id, status): registrar progressão (applied, interviewing, etc.).
   - get_application_stats(): painel geral com funil de candidaturas.
   - get_pending_followups(): vagas marcadas como interessante sem aplicação.
   - learn_from_job(job_id): extrair palavras-chave estratégicas de uma vaga.

2. CONFIGURAÇÃO (chame estas ferramentas quando o usuário fornecer dados):
   - save_api_keys(free_key, paid_key): salvar chaves Gemini do usuário de forma segura.
   - update_career_profile(summary_text): atualizar resumo de carreira e regenerar vetores.

«ONBOARDING»
{onboarding_instructions}

«LIMITAÇÕES HONESTAS»
- NÃO abre LinkedIn, Gupy ou qualquer site por conta própria.
- NÃO envia candidaturas ou formulários.
- NÃO agenda entrevistas.
- NÃO busca vagas em tempo real — o pipeline roda automaticamente.
- NÃO sabe de vagas ainda não processadas pelo pipeline.

«REGRAS INVIOLAVEIS»
- ANTI-ALUCINAÇÃO: Ao gerar Currículos ou Cover Letters, baseie-se ESTRITAMENTE no perfil acima.
- NUNCA invente graus acadêmicos, cursos, certificações ou experiências.
- Nunca invente vagas, empresas, scores ou status. Use sempre as ferramentas.
- Responda em português brasileiro, de forma direta e conversacional.
- Seja proativo: antecipe o próximo passo útil sem esperar o usuário pedir.
"""

ONBOARDING_INSTRUCTIONS = """O usuário ainda não concluiu o onboarding. Guie-o naturalmente:
1. TRIGGER INICIAL: Se o usuário enviar "[SISTEMA] Novo usuário...", dê as boas-vindas calorosas usando o nome dele e explique que você é o CareerBot, o assistente que vai ajudá-lo a encontrar a vaga ideal.

2. CHAVES API: Explique de forma amigável que você precisa das chaves Gemini dele para funcionar (BYOK):
   - Chave GRATUITA: usada para busca e indexação (embeddings). [OBRIGATÓRIA]
   - Chave PAGA (opcional): usada para análise profunda e chat mais inteligente.
   - Como obter: https://aistudio.google.com/app/apikey
   - Quando o usuário fornecer as chaves (formato AIza...), chame save_api_keys() imediatamente.

3. PERFIL DE CARREIRA: Após as chaves estarem salvas, peça um resumo de carreira livre:
   - Experiência, habilidades, tipos de vaga e preferências (remoto, senioridade).
   - Quando o usuário enviar o texto, chame update_career_profile() imediatamente.

4. NUNCA exija o uso de /comandos. O usuário deve sentir que está conversando com um assistente humano.
"""

READY_INSTRUCTIONS = """O usuário está configurado e ativo.
Se em algum momento o usuário quiser atualizar seu perfil, use a ferramenta update_career_profile() imediatamente.
"""


class CareerAgent:
    """
    Stateful conversational agent per user session.
    Each user gets their own agent instance with conversation history.
    """

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.history = []  # Gemini multi-turn conversation history
        self._setup_model()

    def _setup_model(self):
        """Initialize chat session with system prompt and Gemini client."""
        from src.db.users import get_user

        user = get_user(self.user_id)
        self.onboarding_step = (user or {}).get("onboarding_step", "new")

        from src.db.client import get_vault_secret
        
        # Use system GEMINI_API_KEY for chat (central key, not BYOK)
        api_key = os.getenv("GEMINI_API_KEY", "").strip() or get_vault_secret("GEMINI_API_KEY")
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY não configurada no ambiente nem no Supabase Vault. "
                "Configure a variável de ambiente para o agente de chat funcionar."
            )
        self.api_key = api_key

        career_profile = _load_career_profile(self.user_id)
        onboarding_instr = ONBOARDING_INSTRUCTIONS if not career_profile else READY_INSTRUCTIONS
        self.system = SYSTEM_PROMPT.format(
            career_profile=career_profile or "(Perfil ainda não configurado)",
            onboarding_instructions=onboarding_instr,
        )
        self.history = []
        self._get_client()

    def _get_client(self):
        self.client = genai.Client(api_key=self.api_key)

    def _execute_tool(self, tool_name: str, tool_args: dict) -> str:
        """Execute a Function Calling tool and return the result."""
        fn = TOOL_EXECUTOR.get(tool_name)
        if not fn:
            return json.dumps({"error": f"Tool '{tool_name}' não encontrada"})
        try:
            return fn(**tool_args)
        except Exception as e:
            return json.dumps({"error": str(e)})

    async def chat_async(self, user_message: str) -> str:
        """
        Send a message and get a response, handling multi-step Function Calling
        and rotating API keys if rate limit is exceeded.
        """
        tools = [types.Tool(function_declarations=[
            types.FunctionDeclaration(**d) for d in TOOL_DECLARATIONS
        ])]
        config = types.GenerateContentConfig(
            system_instruction=self.system,
            tools=tools,
        )

        self.history.append(types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_message)]
        ))

        max_attempts = 2  # 1 retry com backoff em caso de quota 429
        attempt = 0

        # Sliding window: keep only last 20 messages to prevent token explosion
        if len(self.history) > 20:
            self.history = self.history[-20:]
            
        # Hard cap on character length to prevent expensive context bloat (~10k tokens)
        while sum(len(str(getattr(h, "parts", []))) for h in self.history) > 40000 and len(self.history) > 1:
            self.history.pop(0)

        while attempt < max_attempts:
            attempt += 1
            try:
                # Agentic loop — max 2 steps to respect Vercel Timeout (10-60s)
                step_count = 0
                max_steps = 2

                while step_count < max_steps:
                    step_count += 1

                    response = await self.client.aio.models.generate_content(
                        model="gemini-2.0-flash-lite",
                        contents=self.history,
                        config=config,
                    )
                    candidate = response.candidates[0].content
                    self.history.append(candidate)

                    tool_calls = [
                        p.function_call for p in candidate.parts
                        if p.function_call is not None
                    ]

                    if not tool_calls or step_count >= max_steps:
                        return response.text

                    tool_parts = []
                    for call in tool_calls:
                        args = dict(call.args)
                        args['user_id'] = self.user_id
                        result = self._execute_tool(call.name, args)
                        tool_parts.append(types.Part.from_function_response(
                            name=call.name,
                            response={"result": result},
                        ))

                    self.history.append(types.Content(
                        role="tool",
                        parts=tool_parts,
                    ))

            except Exception as e:
                error_str = str(e)
                print(f"⚠️ [Agent] attempt {attempt}/{max_attempts} error: {error_str[:300]}")

                if ("429" in error_str or "RESOURCE_EXHAUSTED" in error_str) and attempt < max_attempts:
                    import asyncio as _asyncio
                    await _asyncio.sleep(30)
                    # Reset history to last user message
                    while self.history:
                        popped = self.history.pop()
                        if popped.role == "user":
                            break
                    self.history.append(types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=user_message)]
                    ))
                    continue
                else:
                    return f"❌ Erro no agente: {error_str[:200]}"

        return "❌ Cota excedida. Tente em alguns minutos."


# Global registry of agents per user (in-memory, resets on restart)
_agents: dict[int, CareerAgent] = {}


def get_agent(user_id: int) -> CareerAgent:
    """Get or create a CareerAgent for the given user."""
    if user_id not in _agents:
        _agents[user_id] = CareerAgent(user_id)
    return _agents[user_id]
