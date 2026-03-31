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
    
    # Fallback text if user has no profile mapped
    return "Perfil de carreira ainda não configurado. Por favor, solicite ao usuário para usar o comando /set_profile."


SYSTEM_PROMPT = """Você é o CareerBot, assistente de carreira pessoal do usuário abaixo.

PERFIL DO USUÁRIO:
{career_profile}

=== O QUE VOCÊ CONSEGUE FAZER (use as ferramentas) ===

1. get_recent_jobs(days, limit)
   → Busca as vagas mais recentes do banco. Use quando o usuário pedir "melhores vagas",
     "o que tem de novo", "vagas da semana" etc.

2. get_job_detail(job_id / company / title)
   → Retorna detalhes completos de uma vaga específica. Use quando o usuário perguntar
     sobre uma empresa ou cargo específico.

3. update_job_status(job_id, status)
   → Atualiza o status de uma vaga: interested | applied | interviewing | rejected | skipped | offer
   → Use SEMPRE que o usuário disser "apliquei", "passei pra entrevista", "desisti dessa" etc.

4. get_application_stats()
   → Mostra painel completo: total de vagas analisadas, distribuição por status,
     últimas aplicações. Use quando o usuário pedir "meu status", "meu funil" etc.

5. get_pending_followups()
   → Lista vagas marcadas como interessante há mais de 3 dias sem aplicação.
     Use quando o usuário pedir "pendências", "não apliquei ainda".

6. learn_from_job(job_id)
   → Extrai palavras-chave estratégicas da vaga e salva em memória de longo prazo.
     Use quando o usuário clicar em "Quero Aplicar" ou elogiar muito uma vaga.

=== O QUE VOCÊ NÃO CONSEGUE FAZER (seja honesto, não alucine) ===

- NÃO abre o LinkedIn, Gupy ou qualquer site de vagas por conta própria
- NÃO envia candidaturas ou formulários em nome do usuário
- NÃO agenda entrevistas
- NÃO busca vagas em tempo real — o pipeline roda às 08h e 18h automaticamente
- NÃO sabe de vagas que ainda não foram processadas pelo pipeline
- NÃO tem acesso a e-mails ou calendário do usuário
- NÃO pode alterar o perfil de carreira armazenado (apenas lê o que foi configurado)

=== REGRAS INVIOLÁVEIS ===

- ANTI-ALUCINAÇÃO: Ao gerar Currículos ou Cover Letters, baseie-se ESTRITAMENTE
  no histórico do PERFIL DO USUÁRIO acima. NUNCA invente graus acadêmicos, cursos,
  faculdades, certificações ou experiências que não estejam explicitamente no perfil.
- DADOS REAIS: Nunca invente vagas, empresas, scores ou status. Sempre use as ferramentas.
- O usuário DECIDE onde aplicar. Você informa, analisa e prepara — nunca decide.
- Responda em português brasileiro, de forma direta e conversacional.
- Seja proativo: antecipe o próximo passo útil sem esperar o usuário pedir.
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
        # Paid key for interactive user-facing conversations
        self.api_keys = get_key_pool("paid", self.user_id)
        self.using_fallback = False
        self._fallback_warned = False
        if not self.api_keys:
            # Fallback to legacy pool if paid key not configured
            self.using_fallback = True
            pool = os.getenv("GEMINI_API_KEYS", os.getenv("GEMINI_API_KEY", "")).split(",")
            self.api_keys = [k.strip() for k in pool if k.strip()]
        self.current_key_idx = 0
        
        if not self.api_keys:
            raise ValueError("Nenhuma GEMINI_API_KEY encontrada.")

        career_profile = _load_career_profile(self.user_id)
        self.system = SYSTEM_PROMPT.format(career_profile=career_profile)
        self.history = []  # list of types.Content objects
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
