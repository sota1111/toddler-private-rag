"""RAG (ベクトル検索＋LLM回答生成) package.

Provides an embedding/LLM provider abstraction, a lightweight in-process vector
store (pure-Python cosine similarity), document chunking, and a RagService that
ties retrieval and answer generation together.

The default providers are deterministic and dependency-free (``fake``), so the
whole pipeline runs and is testable offline with no external API key. A real
``gemini`` provider path is wired behind environment variables and lazily imports
its SDK, so a missing SDK never breaks module import.
"""
