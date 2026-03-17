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


# Load career profile for system context
CAREER_PATH = Path(__file__).parent.parent.parent / "data" / "career"
DB_PATH = Path(__file__).parent.parent.parent / "data" / "jobs.db"


def _load_career_profile() -> str:
    """Load career profile trimmed to 2000 chars to save tokens on every request."""
    parts = []
    if CAREER_PATH.exists():
        for f in CAREER_PATH.iterdir():
            if f.suffix in (".md", ".txt") and f.is_file():
                parts.append(f.read_text(encoding="utf-8"))
    # Fallback: use env var (GitHub Actions scenario)
    if not parts:
        profile = os.getenv("MASTER_PROFILE", "")
        if profile:
            parts.append(profile)
    full_profile = "\n\n---\n\n".join(parts) if parts else "Perfil de carreira não disponível."
    # Trim to 2000 chars to avoid burning free-tier token quota on every request.
    # The full profile is available via the RAG pipeline.
    if len(full_profile) > 2000:
        full_profile = full_profile[:2000] + "\n\n[... perfil truncado | resumo disponível via ferramentas ...]"
    return full_profile


SYSTEM_PROMPT = """Você é o CareerBot, um assistente de carreira pessoal e proativo.

Seu papel é ajudar o usuário a acompanhar as vagas encontradas pelo JobHunter, 
entender quais oportunidades fazem mais sentido para sua trajetória, e se preparar 
para aplicações com cover letters personalizadas.

PERFIL DO USUÁRIO:
{career_profile}

DIRETRIZES:
- Seja direto, analítico e humano. Não seja genérico.
- Você tem acesso ao banco de vagas via ferramentas (tools). USE-AS quando precisar de dados.
- Nunca invente dados de vagas — sempre consulte as ferramentas.
- O usuário DECIDE onde aplicar. Você informa, analisa e prepara, mas não decide.
- Responda em português brasileiro, de forma conversacional.
- Quando o usuário perguntar sobre vagas, sempre use get_recent_jobs ou get_job_detail
  para trazer dados reais, não invente resultados.
- Seja proativo: se o usuário diz "apliquei na Cobli", atualize o status via update_job_status.
- Mantenha o histórico da conversa para responder com contexto.
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
        self.api_keys = os.getenv("GEMINI_API_KEYS", os.getenv("GEMINI_API_KEY", "")).split(",")
        self.api_keys = [k.strip() for k in self.api_keys if k.strip()]
        self.current_key_idx = 0
        
        if not self.api_keys:
            raise ValueError("Nenhuma GEMINI_API_KEY encontrada.")

        career_profile = _load_career_profile()
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

        while attempt < max_attempts:
            attempt += 1
            key_label = f"key {self.current_key_idx + 1}/{len(self.api_keys)}"
            try:
                # Agentic loop — hard cap at 5 tool steps to prevent quota drain
                step_count = 0
                max_steps = 5

                while step_count < max_steps:
                    step_count += 1

                    response = await self.client.aio.models.generate_content(
                        model="gemini-2.0-flash",
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
                        result = self._execute_tool(call.name, dict(call.args))
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
