"""
CareerBot — CV & Cover Letter Generator

Generates ATS-optimized documents tailored for each job opening.

Two outputs:
  1. cover_letter.pdf — personalized cover letter (ATS-safe plain layout)
  2. cv_jobcompany.pdf — 1-page tailored CV with keywords from the job description

Both are:
  - Sent directly to the user via Telegram (sendDocument)
  - Saved as BLOBs in the SQLite database (cover_letter_pdf, cv_pdf columns)
    for future retrieval (interview prep, reference)

ATS Strategy:
  - Gemini extracts required keywords from the job description
  - CV explicitly mirrors those keywords in the professional summary and skills
  - No tables, no columns, no headers/footers (ATS parsers hate those)
  - Clean, parseable text layout via reportlab
"""
import io
import json
import os
import sqlite3
from pathlib import Path

from google import genai
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.colors import HexColor

from src.bot.key_router import get_key


DB_PATH = Path(__file__).parent.parent.parent / "data" / "jobs.db"
CAREER_PATH = Path(__file__).parent.parent.parent / "data" / "career"


def _get_gemini_client():
    return genai.Client(api_key=get_key("paid"))


def _load_career_profile() -> str:
    """Load career profile from files or env vars (Railway scenario)."""
    parts = []
    if CAREER_PATH.exists():
        for f in sorted(CAREER_PATH.iterdir()):
            if f.suffix in (".md", ".txt") and f.is_file():
                parts.append(f.read_text(encoding="utf-8"))
    if not parts:
        master = os.getenv("MASTER_PROFILE", "")
        if master:
            parts.append(master)
        product_ops = os.getenv("PRODUCT_OPS_PROFILE", "")
        if product_ops:
            parts.append(f"## Competências de Product Ops\n{product_ops}")
    return "\n\n---\n\n".join(parts) if parts else ""


def _get_job_from_db(job_id: str) -> dict | None:
    """Fetch job details from SQLite."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


def _save_documents_to_db(job_id: str, cover_letter_text: str,
                           cover_letter_bytes: bytes, cv_bytes: bytes | None):
    """Persist generated documents as BLOBs in the database."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("""
            UPDATE jobs
            SET cover_letter_text = ?,
                cover_letter_pdf  = ?,
                cv_pdf            = ?
            WHERE job_id = ?
        """, (cover_letter_text, cover_letter_bytes, cv_bytes, job_id))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[!] Failed to save documents to DB: {e}")


# ─────────────────────────── PROMPTS ───────────────────────────

COVER_LETTER_PROMPT = """Você é um redator especialista em cartas de apresentação ATS-otimizadas para o mercado tech brasileiro.

VAGA ALVO:
Título: {job_title}
Empresa: {job_company}
Nível: {seniority}
Descrição completa da vaga:
{job_description}

Análise prévia do nosso pipeline:
{fit_reason}

INSTRUÇÕES — COVER LETTER ATS-OTIMIZADA:
1. Extraia as 5-8 palavras-chave mais importantes da descrição da vaga
2. Incorpore NATURALMENTE essas palavras-chave na carta
3. Estrutura:
   - Abertura: conecte o candidato à empresa e cargo de forma específica (não genérica)
   - Corpo (2 parágrafos):
     * Parágrafo 1: impactos concretos com números reais (ex: +2% GMV, 95% redução operacional)
     * Parágrafo 2: conexão direta entre a experiência e os requisitos desta vaga específica
   - Fechamento: proativo, confiante, chama para ação
4. Tom: analítico, direto, confiante — nunca subserviente
5. Máximo 280 palavras
6. Nunca use "venho por meio desta", "prezado(a)", ou fórmulas genéricas
7. Mencione a empresa pelo nome real
8. NÃO inclua saudação com [Nome] nem data — será preenchido manualmente

Responda APENAS com o texto da carta, sem comentários extras."""


CV_PROMPT = """Você é um especialista em criação de currículos ATS-otimizados para o mercado tech brasileiro.

VAGA ALVO:
Título: {job_title}
Empresa: {job_company}
Descrição:
{job_description}

MISSÃO:
1. Extraia TODAS as palavras-chave técnicas e comportamentais da descrição da vaga
2. Gere um currículo de UMA PÁGINA que maximize o match ATS com essa vaga específica
3. Adapte o resumo profissional para espelhar a linguagem da vaga
4. Priorize as experiências e habilidades mais relevantes para este cargo

REGRAS ATS OBRIGATÓRIAS:
- Use as MESMAS palavras-chave da vaga (ATS faz match exato)
- Seção de habilidades com as tecnologias listadas na vaga
- Sem tabelas, sem colunas, sem caracteres especiais
- Datas no formato MM/AAAA — PRESENTE
- Verbos de ação no passado (construiu, implementou, reduziu, liderou)

FORMATO DE SAÍDA — responda APENAS com JSON válido:
{{
  "ats_keywords": ["lista", "das", "palavras-chave", "extraídas", "da", "vaga"],
  "header": {{
    "name": "Kevyn Costa Lima",
    "title": "título adaptado para esta vaga específica",
    "email": "kevynlad1@gmail.com",
    "phone": "(11) 94646-8589",
    "linkedin": "linkedin.com/in/kevyn-ladeira",
    "location": "São Paulo, SP"
  }},
  "summary": "Resumo profissional de 3 linhas com palavras-chave da vaga incorporadas naturalmente",
  "experience": [
    {{
      "company": "Nome da empresa",
      "role": "Cargo exato",
      "period": "MM/AAAA — PRESENTE",
      "highlights": [
        "Bullet point com número concreto e palavra-chave da vaga",
        "Bullet point com impacto mensurável"
      ]
    }}
  ],
  "skills": {{
    "technical": ["habilidades técnicas priorizadas pela vaga"],
    "product_ops": ["habilidades de produto/ops relevantes"],
    "tools": ["ferramentas mencionadas na vaga ou no perfil"]
  }},
  "education": [
    {{
      "institution": "nome",
      "course": "curso",
      "period": "período"
    }}
  ]
}}"""


# ─────────────────────────── PDF BUILDERS ───────────────────────────

def _build_cover_letter_pdf(text: str, job_title: str, company: str) -> bytes:
    """Render a clean ATS-safe PDF from cover letter text."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=2.5*cm, rightMargin=2.5*cm,
        topMargin=2.5*cm, bottomMargin=2.5*cm,
    )
    styles = getSampleStyleSheet()
    accent = HexColor("#1a1a2e")

    title_style = ParagraphStyle("title", parent=styles["Normal"],
                                  fontSize=14, fontName="Helvetica-Bold",
                                  textColor=accent, spaceAfter=4)
    sub_style = ParagraphStyle("sub", parent=styles["Normal"],
                                fontSize=10, textColor=HexColor("#555555"), spaceAfter=12)
    body_style = ParagraphStyle("body", parent=styles["Normal"],
                                 fontSize=11, leading=16, spaceAfter=10)

    elements = [
        Paragraph("Kevyn Costa Lima", title_style),
        Paragraph(f"Candidatura: {job_title} — {company}", sub_style),
        Spacer(1, 0.3*cm),
    ]
    for para in text.strip().split("\n\n"):
        if para.strip():
            elements.append(Paragraph(para.strip().replace("\n", " "), body_style))

    doc.build(elements)
    return buffer.getvalue()


def _build_cv_pdf(cv_data: dict, company: str) -> bytes:
    """Render a clean 1-page ATS-safe CV from structured JSON."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=1.8*cm, bottomMargin=1.8*cm,
    )
    styles = getSampleStyleSheet()
    accent = HexColor("#1a1a2e")
    gray = HexColor("#555555")

    name_style = ParagraphStyle("name", fontSize=18, fontName="Helvetica-Bold",
                                 textColor=accent, spaceAfter=2, alignment=TA_CENTER)
    contact_style = ParagraphStyle("contact", fontSize=9, textColor=gray,
                                    spaceAfter=8, alignment=TA_CENTER)
    section_style = ParagraphStyle("section", fontSize=11, fontName="Helvetica-Bold",
                                    textColor=accent, spaceBefore=10, spaceAfter=4,
                                    borderPad=2)
    body_style = ParagraphStyle("body", fontSize=9, leading=13, spaceAfter=3)
    bullet_style = ParagraphStyle("bullet", fontSize=9, leading=13,
                                   leftIndent=12, spaceAfter=2)

    h = cv_data.get("header", {})
    exp_list = cv_data.get("experience", [])
    skills = cv_data.get("skills", {})
    edu_list = cv_data.get("education", [])

    elements = [
        Paragraph(h.get("name", ""), name_style),
        Paragraph(
            f"{h.get('title','')} | {h.get('email','')} | {h.get('phone','')} | "
            f"{h.get('linkedin','')} | {h.get('location','')}",
            contact_style
        ),
        Spacer(1, 0.2*cm),
        Paragraph("RESUMO PROFISSIONAL", section_style),
        Paragraph(cv_data.get("summary", ""), body_style),
        Paragraph("EXPERIÊNCIA PROFISSIONAL", section_style),
    ]

    for exp in exp_list:
        elements.append(Paragraph(
            f"<b>{exp.get('company','')}</b> — {exp.get('role','')} | {exp.get('period','')}",
            body_style
        ))
        for bullet in exp.get("highlights", []):
            elements.append(Paragraph(f"• {bullet}", bullet_style))

    # Skills
    elements.append(Paragraph("HABILIDADES", section_style))
    all_skills = []
    for category, items in skills.items():
        if items:
            all_skills.append(", ".join(items))
    elements.append(Paragraph(" | ".join(all_skills), body_style))

    # Education
    elements.append(Paragraph("FORMAÇÃO", section_style))
    for edu in edu_list:
        elements.append(Paragraph(
            f"<b>{edu.get('institution','')}</b> — {edu.get('course','')} | {edu.get('period','')}",
            body_style
        ))

    # ATS keywords footer (invisible-sized, helps ATS scanners)
    if cv_data.get("ats_keywords"):
        kw_style = ParagraphStyle("kw", fontSize=1, textColor=HexColor("#ffffff"))
        elements.append(Paragraph(" ".join(cv_data["ats_keywords"]), kw_style))

    doc.build(elements)
    return buffer.getvalue()


# ─────────────────────────── PUBLIC API ───────────────────────────

async def generate_cover_letter_pdf(bot, chat_id: int, job_id: str):
    """
    Generate and send a cover letter for a given job.
    Saves the result to the database for future retrieval.
    """
    await bot.send_message(chat_id=chat_id, text="📝 Gerando cover letter com Gemini...")

    job = _get_job_from_db(job_id)
    if not job:
        await bot.send_message(chat_id=chat_id, text="❌ Vaga não encontrada no banco.")
        return

    career_profile = _load_career_profile()
    client = _get_gemini_client()

    prompt = COVER_LETTER_PROMPT.format(
        job_title=job.get("title", ""),
        job_company=job.get("company", ""),
        seniority=job.get("seniority", ""),
        job_description=job.get("description", "") or "Descrição não disponível.",
        fit_reason=job.get("fit_reason", ""),
    )

    response = client.models.generate_content(
        model="gemini-3.0-flash",
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            system_instruction=career_profile
        )
    )
    cover_text = response.text.strip()

    # Build PDF
    pdf_bytes = _build_cover_letter_pdf(
        text=cover_text,
        job_title=job.get("title", ""),
        company=job.get("company", ""),
    )

    # Save to database
    _save_documents_to_db(
        job_id=job_id,
        cover_letter_text=cover_text,
        cover_letter_bytes=pdf_bytes,
        cv_bytes=None,  # CV not generated yet
    )

    # Send the PDF via Telegram
    filename = f"cover_letter_{job.get('company','').replace(' ','_')}.pdf"
    await bot.send_document(
        chat_id=chat_id,
        document=io.BytesIO(pdf_bytes),
        filename=filename,
        caption=(
            f"📄 Cover Letter — {job.get('title')} @ {job.get('company')}\n"
            f"💾 Salva no banco para referência futura."
        ),
    )


async def generate_cv_pdf(bot, chat_id: int, job_id: str):
    """
    Generate and send an ATS-optimized 1-page CV for a given job.
    Saves the result to the database for future retrieval.
    """
    await bot.send_message(chat_id=chat_id, text="📋 Gerando CV ATS-otimizado com Gemini...")

    job = _get_job_from_db(job_id)
    if not job:
        await bot.send_message(chat_id=chat_id, text="❌ Vaga não encontrada no banco.")
        return

    career_profile = _load_career_profile()
    client = _get_gemini_client()

    prompt = CV_PROMPT.format(
        job_title=job.get("title", ""),
        job_company=job.get("company", ""),
        job_description=job.get("description", "") or "Descrição não disponível.",
    )

    response = client.models.generate_content(
        model="gemini-3.0-flash",
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            system_instruction=career_profile
        )
    )
    raw = response.text.strip()

    # Extract JSON from response
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()

    try:
        cv_data = json.loads(raw)
    except json.JSONDecodeError:
        await bot.send_message(
            chat_id=chat_id,
            text="⚠️ Erro ao processar o CV. Tente novamente."
        )
        return

    # Build PDF
    pdf_bytes = _build_cv_pdf(cv_data, company=job.get("company", ""))

    # Save to database
    _save_documents_to_db(
        job_id=job_id,
        cover_letter_text=job.get("cover_letter_text", ""),
        cover_letter_bytes=job.get("cover_letter_pdf") or b"",
        cv_bytes=pdf_bytes,
    )

    # Send ATS keywords as a tip message first
    keywords = cv_data.get("ats_keywords", [])
    if keywords:
        await bot.send_message(
            chat_id=chat_id,
            text=f"🎯 <b>Palavras-chave ATS incorporadas:</b>\n<code>{', '.join(keywords)}</code>",
            parse_mode="HTML",
        )

    # Send the CV PDF
    filename = f"cv_{job.get('company','').replace(' ','_')}_{job.get('title','').replace(' ','_')[:20]}.pdf"
    await bot.send_document(
        chat_id=chat_id,
        document=io.BytesIO(pdf_bytes),
        filename=filename,
        caption=(
            f"📋 CV ATS-Otimizado — {job.get('title')} @ {job.get('company')}\n"
            f"💾 Salvo no banco para preparação de entrevistas."
        ),
    )
