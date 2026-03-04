"""
Demo: Generate a CV by querying the RAG database.

This script pulls information from YOUR career documents
(already stored in ChromaDB) and assembles a CV.

This is a simplified version — the real Module 3 will use
an LLM (Ollama) to create much better, tailored CVs.
"""

import sys
import os

# Fix Windows encoding for emoji/special chars
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
from datetime import datetime

# Import our RAG retriever
from src.rag.retriever import query


def retrieve_career_data() -> dict:
    """
    Query the RAG database with different topics to extract
    a complete picture of the user's career.
    """
    print("Searching your career database...\n")
    
    # We search for different aspects of a career
    queries = {
        "personal_info": "nome contato informacoes pessoais email telefone",
        "summary": "resumo profissional experiencia objetivos",
        "experience": "experiencia profissional trabalho cargo empresa resultados",
        "skills_tech": "habilidades tecnicas ferramentas Python SQL dados tecnologia",
        "skills_soft": "habilidades lideranca gestao comunicacao equipe",
        "education": "formacao educacao universidade curso graduacao",
        "achievements": "resultados conquistas metricas impacto reducao aumento",
        "product": "produto product manager discovery delivery roadmap",
    }
    
    career_data = {}
    for key, search_text in queries.items():
        results = query(search_text, k=3)
        career_data[key] = results
        print(f"  [OK] Found {len(results)} chunks for: {key}")
    
    return career_data


def build_cv_markdown(career_data: dict, target_role: str) -> str:
    """
    Build a CV in Markdown format using the retrieved career data.
    """
    sections = []
    
    # Header
    sections.append(f"# Curriculum Vitae")
    sections.append(f"**Target Role:** {target_role}")
    sections.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    sections.append(f"**Source:** RAG database (your career documents)")
    sections.append("")
    sections.append("---")
    sections.append("")
    
    # Professional Summary - from RAG
    sections.append("## Professional Summary")
    sections.append("")
    if career_data.get("summary"):
        for chunk in career_data["summary"][:2]:
            # Clean up the text (PDF extraction can have weird spacing)
            text = " ".join(chunk["text"].split())  # normalize whitespace
            sections.append(f"> {text[:500]}")
            sections.append(f"> *(Source: {chunk['source']})*")
            sections.append("")
    
    # Experience - from RAG
    sections.append("## Professional Experience")
    sections.append("")
    seen_texts = set()
    if career_data.get("experience"):
        for chunk in career_data["experience"]:
            text = " ".join(chunk["text"].split())
            # Avoid duplicates
            if text[:100] not in seen_texts:
                seen_texts.add(text[:100])
                sections.append(f"### From: {chunk['source']}")
                sections.append(f"*Match distance: {chunk['distance']:.3f}*")
                sections.append("")
                sections.append(text[:600])
                sections.append("")
    
    # Technical Skills - from RAG
    sections.append("## Technical Skills")
    sections.append("")
    if career_data.get("skills_tech"):
        for chunk in career_data["skills_tech"][:2]:
            text = " ".join(chunk["text"].split())
            if text[:100] not in seen_texts:
                seen_texts.add(text[:100])
                sections.append(f"**From: {chunk['source']}**")
                sections.append(text[:400])
                sections.append("")
    
    # Achievements - from RAG
    sections.append("## Key Achievements")
    sections.append("")
    if career_data.get("achievements"):
        for chunk in career_data["achievements"][:2]:
            text = " ".join(chunk["text"].split())
            if text[:100] not in seen_texts:
                seen_texts.add(text[:100])
                sections.append(f"- {text[:300]}")
                sections.append(f"  *(Source: {chunk['source']})*")
                sections.append("")
    
    # Product Experience - from RAG
    sections.append("## Product Management Experience")
    sections.append("")
    if career_data.get("product"):
        for chunk in career_data["product"][:2]:
            text = " ".join(chunk["text"].split())
            if text[:100] not in seen_texts:
                seen_texts.add(text[:100])
                sections.append(f"**From: {chunk['source']}**")
                sections.append(text[:400])
                sections.append("")
    
    # Education - from RAG
    sections.append("## Education")
    sections.append("")
    if career_data.get("education"):
        for chunk in career_data["education"][:1]:
            text = " ".join(chunk["text"].split())
            sections.append(text[:300])
            sections.append(f"*(Source: {chunk['source']})*")
            sections.append("")
    
    # Footer
    sections.append("---")
    sections.append("")
    sections.append("> **Note:** This CV was automatically generated from the RAG database.")
    sections.append("> The real Module 3 will use an LLM (Ollama) to create a much more")
    sections.append("> polished, tailored CV — rewriting and organizing the content properly.")
    
    return "\n".join(sections)


if __name__ == "__main__":
    # Define a sample target role
    target_role = "Product Manager - Data & Analytics"
    
    print("=" * 60)
    print("  CV GENERATOR DEMO (from RAG database)")
    print("=" * 60)
    print(f"\nTarget role: {target_role}\n")
    
    # Step 1: Retrieve career data from RAG
    career_data = retrieve_career_data()
    
    # Step 2: Build the CV
    print("\nBuilding CV...\n")
    cv_content = build_cv_markdown(career_data, target_role)
    
    # Step 3: Save to file
    output_path = Path(__file__).parent.parent / "output" / "demo_cv.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(cv_content, encoding="utf-8")
    
    print(f"CV saved to: {output_path.resolve()}")
    print("\n" + "=" * 60)
    print("  GENERATED CV PREVIEW")
    print("=" * 60)
    print(cv_content)
