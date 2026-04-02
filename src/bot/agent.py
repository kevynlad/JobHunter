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

from src.bot.tools import TOOL_DECLARATIONS, TOOL_EXECUTOR
from src.bot.key_router import get_key, get_key_pool


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

1. CHAVES API: Se o usuário não tem chaves configuradas, explique de forma amigável:
   - Chave GRATUITA: usada para buscar e indexar vagas (embeddings).
   - Chave PAGA (opcional, mas recomendada): usada para análise profunda das vagas e conversa.
   - Sem chave paga: o pipeline classifica apenas as Top 5 vagas (modo econômico).
   - Como obter: https://aistudio.google.com/app/apikey
   - Quando o usuário fornecer as chaves (formato AIza...), chame save_api_keys() imediatamente.

2. PERFIL DE CARREIRA: Após as chaves, peça um resumo de carreira livre:
   - Experiência e habilidades
   - Tipos de vaga e áreas de interesse
   - Preferências (remoto, híbrido, senioridade)
   - Quando o usuário enviar o texto, chame update_career_profile() imediatamente.

3. Seja acolhedor, direto e nunca exija use de /comandos.
"""

READY_INSTRUCTIONS = """O usuário está configurado e ativo.
Se em algum momento o usuário mencionar uma nova chave (AIza...) ou quiser atualizar seu perfil, use as ferramentas save_api_keys() ou update_career_profile() imediatamente.
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
        """Initialize chat session system prompt and state."""
        from src.bot.key_router import get_key_pool
        from src.db.users import get_user

        # Determine onboarding state
        user = get_user(self.user_id)
        self.onboarding_step = (user or {}).get("onboarding_step", "new")
        self.has_paid_key = bool((user or {}).get("gemini_paid_key"))

        # Always use the paid key for chat; if missing, use free key (limited experience)
        self.api_keys = get_key_pool("paid", self.user_id)
        if not self.api_keys:
            self.api_keys = get_key_pool("free", self.user_id)

        # If still no user key at all, use system key ONLY for onboarding guidance
        if not self.api_keys:
            try:
                from src.bot.key_router import _get_system_key
                self.api_keys = [_get_system_key("free")]
                self.onboarding_step = "new"  # Force onboarding mode
            except ValueError:
                pass

        self.current_key_idx = 0

        if not self.api_keys:
            raise ValueError(
                "Nenhuma chave Gemini disponível. Configure sua chave Gemini "
                "e defina GEMINI_FREE_API_KEY no ambiente do sistema."
            )

        career_profile = _load_career_profile(self.user_id)
        onboarding_instr = ONBOARDING_INSTRUCTIONS if not career_profile else READY_INSTRUCTIONS
        self.system = SYSTEM_PROMPT.format(
            career_profile=career_profile or "(Perfil ainda não configurado)",
            onboarding_instructions=onboarding_instr,
        )
        self.history = []
        self._get_client()

    def _get_client(self):
        key = self.api_keys[self.current_key_idx]
        self.client = genai.Client(api_key=key)

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

        max_attempts = len(self.api_keys)  # one try per key
        attempt = 0

        # Sliding window: keep only last 20 messages to prevent token explosion
        # Always keep the current user message (last element) and up to 19 history items
        if len(self.history) > 20:
            self.history = self.history[-20:]
            
        # Hard cap on character length to prevent expensive context bloat (~10k tokens)
        while sum(len(str(getattr(h, "parts", []))) for h in self.history) > 40000 and len(self.history) > 1:
            self.history.pop(0)

        while attempt < max_attempts:
            attempt += 1
            key_label = f"key {self.current_key_idx + 1}/{len(self.api_keys)}"
            try:
                # Agentic loop — Reduce to 2 steps to respect Vercel Timeout (10-60s)
                step_count = 0
                max_steps = 2

                while step_count < max_steps:
                    step_count += 1

                    response = await self.client.aio.models.generate_content(
                        model="gemini-3.1-flash-lite-preview",
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
                        final_text = response.text
                        if getattr(self, "using_fallback", False) and not getattr(self, "_fallback_warned", False):
                            self._fallback_warned = True
                            final_text += "\n\n⚠️ <i>Aviso: Você está usando a cota cortesia do sistema. Configure sua própria chave Gemini pelo menu /set_key para pesquisas ilimitadas.</i>"
                        return final_text

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
                # Log full error so Railway logs show the real cause
                print(f"⚠️ [Agent] {key_label} error: {error_str[:300]}")

                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    # Rotate to the next key
                    self.current_key_idx = (self.current_key_idx + 1) % len(self.api_keys)
                    self._get_client()
                    # Clean history: remove everything added in this failed attempt
                    # (pop back past the user message, then re-add it)
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
                    # Non-quota error: surface it directly
                    return f"❌ Erro no agente: {error_str[:200]}"

        return "❌ Cota excedida em todas as chaves. Tente em alguns minutos."


# Global registry of agents per user (in-memory, resets on restart)
_agents: dict[int, CareerAgent] = {}


def get_agent(user_id: int) -> CareerAgent:
    """Get or create a CareerAgent for the given user."""
    if user_id not in _agents:
        _agents[user_id] = CareerAgent(user_id)
    return _agents[user_id]
