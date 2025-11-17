"""
Knowledge Base RAG Handler - Query hotel knowledge bases via function calling.

This module provides the RAG (Retrieval-Augmented Generation) function
that Pipecat voice assistants can call to answer guest questions using
the hotel's knowledge base documents.

Pattern follows Pipecat's function calling standard (FunctionCallParams).
"""

import os
from typing import Dict, Any
from loguru import logger
from openai import AsyncOpenAI

from pipecat.services.llm_service import FunctionCallParams


RAG_MODEL = "gpt-4o-mini"
RAG_MAX_TOKENS = 100
MAX_KNOWLEDGE_CHARS = 50000  # ~12.5k tokens - safe limit for context window


async def query_hotel_knowledge(params: FunctionCallParams) -> None:
    """
    Query the hotel's knowledge base to answer guest questions.
    
    This function is called by Pipecat when the voice LLM needs to
    look up information from the hotel's knowledge base.
    
    Args:
        params: FunctionCallParams containing:
            - arguments["question"]: The guest's question
            - arguments["hotel_id"]: Hotel UUID
            - result_callback: Async function to return the answer
    
    Returns:
        None (result returned via params.result_callback)
    """
    question = params.arguments.get("question", "")
    hotel_id = params.arguments.get("hotel_id", "")
    
    if not question:
        logger.warning("Knowledge base query called without question")
        await params.result_callback({"answer": "I didn't catch your question. Could you please repeat that?"})
        return
    
    if not hotel_id:
        logger.warning("Knowledge base query called without hotel_id")
        await params.result_callback({"answer": "I'm sorry, I don't have access to hotel information right now."})
        return
    
    logger.info(f"Querying knowledge base for hotel {hotel_id}: {question}")
    
    try:
        knowledge_content = await load_hotel_knowledge(hotel_id)
        
        if not knowledge_content:
            logger.warning(f"No knowledge base content found for hotel {hotel_id}")
            await params.result_callback({"answer": "I don't have that information available. Let me connect you with our front desk."})
            return
        
        answer = await query_with_rag(knowledge_content, question)
        
        logger.info(f"Knowledge base answered: {answer[:100]}...")
        await params.result_callback({"answer": answer})
        
    except Exception as e:
        logger.error(f"Error querying knowledge base: {e}")
        await params.result_callback({"answer": "I'm having trouble accessing that information. Please ask the front desk for assistance."})


async def load_hotel_knowledge(hotel_id: str) -> str:
    """
    Load all knowledge base documents for a hotel.
    
    Args:
        hotel_id: Hotel UUID
    
    Returns:
        Combined text content from all knowledge base documents
    """
    from botelier.database import SessionLocal
    from botelier.models.knowledge_base import KnowledgeBase
    from botelier.models.knowledge_document import KnowledgeDocument
    
    db = SessionLocal()
    
    try:
        knowledge_bases = db.query(KnowledgeBase).filter(
            KnowledgeBase.hotel_id == hotel_id
        ).all()
        
        if not knowledge_bases:
            return ""
        
        kb_ids = [kb.id for kb in knowledge_bases]
        
        documents = db.query(KnowledgeDocument).filter(
            KnowledgeDocument.knowledge_base_id.in_(kb_ids)
        ).all()
        
        if not documents:
            return ""
        
        combined_content = "\n\n---\n\n".join([
            f"# {doc.filename}\n\n{doc.content}"
            for doc in documents
        ])
        
        if len(combined_content) > MAX_KNOWLEDGE_CHARS:
            logger.warning(f"Knowledge base too large ({len(combined_content)} chars), truncating to {MAX_KNOWLEDGE_CHARS}")
            combined_content = combined_content[:MAX_KNOWLEDGE_CHARS] + "\n\n[... content truncated for length]"
        
        logger.info(f"Loaded {len(documents)} documents ({len(combined_content)} chars) for hotel {hotel_id}")
        
        return combined_content
        
    finally:
        db.close()


async def query_with_rag(knowledge_content: str, question: str) -> str:
    """
    Query the knowledge base using OpenAI for RAG.
    
    This uses a separate OpenAI call (not the voice LLM) to:
    1. Inject the knowledge base into the context
    2. Ask the question
    3. Return a concise answer (optimized for TTS)
    
    Args:
        knowledge_content: Combined text from knowledge base documents
        question: Guest's question
    
    Returns:
        Concise answer (max 100 words for voice)
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    
    if not api_key:
        logger.error("OPENAI_API_KEY not set for RAG queries")
        raise ValueError("OpenAI API key not configured")
    
    client = AsyncOpenAI(api_key=api_key)
    
    rag_prompt = f"""
You are a helpful hotel assistant answering guest questions based on the hotel's knowledge base.

**Instructions:**
1. Answer questions ONLY using information from the Knowledge Base below
2. Keep responses under 50 words - this will be spoken aloud
3. Use natural, conversational language (no bullet points or special characters)
4. If the answer isn't in the knowledge base, say "I don't have that information available."
5. Do not introduce your response - just provide the answer

**Knowledge Base:**
{knowledge_content}

**Guest Question:**
{question}
"""
    
    response = await client.chat.completions.create(
        model=RAG_MODEL,
        messages=[
            {"role": "user", "content": rag_prompt}
        ],
        temperature=0.1,
        max_tokens=RAG_MAX_TOKENS,
    )
    
    answer = response.choices[0].message.content.strip()
    
    return answer
