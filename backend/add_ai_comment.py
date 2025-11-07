import os
import json
import textwrap
import requests
import re
from typing import List, Dict, Any
from openai import OpenAI  # change if you use another client

# =========================
# CONFIG
# =========================
BASE_URL = "http://212.23.201.167:8080"
JWT_TOKEN = os.getenv("APP_JWT_TOKEN", "eyJE")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY","sk-proj-zWD9syf8LXXHohck1E")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

DOC_ID = int(os.getenv("DOC_ID", "95"))   # your example doc
MAX_DOC_PAGES = 14                     # we only want pages 0..9 or 1..10
BIG_PAGE_SIZE = 14                     # big enough to get all chunks in 1 call

def clean_llm_json(text: str) -> str:
    """
    Make LLM JSON parseable:
    - remove ```json ... ``` fences
    - remove ``` ... ``` fences
    - strip leading/trailing backticks
    """
    text = text.strip()

    # remove ```json ... ``` or ``` ... ```
    if text.startswith("```"):
        # remove first fence
        text = re.sub(r"^```(?:json)?\s*", "", text)
        # remove last fence
        text = re.sub(r"\s*```$", "", text)

    # sometimes there's a stray backtick at start or end
    text = text.strip("`").strip()
    return text


def auth_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {JWT_TOKEN}",
        "accept": "application/json",
    }


def get_document(doc_id: int) -> Dict[str, Any]:
    url = f"{BASE_URL}/documents/{doc_id}"
    resp = requests.get(url, headers=auth_headers())
    resp.raise_for_status()
    return resp.json()


def get_all_chunks_one_call(doc_id: int) -> List[Dict[str, Any]]:
    """
    Your endpoint already returns all needed chunks when you hit:
      /documents/{doc_id}/chunks/?page=1&page_size=9
    We'll just make the page_size BIG so we get everything at once.
    """
    url = f"{BASE_URL}/documents/{doc_id}/chunks/"
    params = {
        "page": 1,
        "page_size": BIG_PAGE_SIZE,
    }
    resp = requests.get(url, headers=auth_headers(), params=params)
    resp.raise_for_status()
    return resp.json()


def build_user_prompt(doc: dict, chunks: List[dict]) -> str:
    parts = []
    for c in chunks:
        pg = c.get("page_num")
        content = c.get("content") or ""
        parts.append(f"\n--- PAGE {pg} ---\n{content}")

    # keep context manageable
    full_text = "".join(parts)[:10000]

    return f"""
Document metadata:
- doc_id: {doc["id"]}
- filename: {doc["filename"]}

Below are the first pages of the document (extracted text). Use them to understand the topic, domain, and key terms.

Text:
{full_text}
""".strip()


def call_gpt(user_prompt: str, doc: dict) -> dict:
    client = OpenAI(api_key=OPENAI_API_KEY)

    system_prompt = textwrap.dedent(
        """
        You analyze the textual content of engineering and technical documents.

        Your task is NOT to summarize the company or general introduction,
        but to describe **what the document actually contains** — the
        technical structure, sections, data, and key engineering topics.

        Focus on answering:
        - What types of information or sections does the document include?
        - What main equipment, components, systems, or instructions are covered?
        - What engineering domains (mechanical, electrical, maintenance, etc.) are discussed?
        - What kinds of data, drawings, or tables appear?

        Ignore company introductions, legal disclaimers, or marketing statements.

        Output ONLY valid JSON in this exact structure:
        {
        "title": "...",
        "summary": "...",
        "keywords": ["k1", "k2", "k3"],
        "source": {
            "doc_id": <number>,
            "filename": "<string>"
        }
        }

        Requirements:
        - "summary": 4–8 sentences describing the *contents* of the document (manual sections, tables, drawings, etc.).
        - "keywords": concise, content-based technical terms (equipment, topics, systems).
        - Mention standards, drawings, tables, or manuals if referenced.
        - Return ONLY JSON, no markdown or explanations.
        """
    )

    res = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",  "content": user_prompt},
        ],
        temperature=0.2,
    )

    content = res.choices[0].message.content
    cleaned = clean_llm_json(content)
    
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # fallback to something usable
        data = {
            "title": f"AI Summary for {doc['filename']}",
            "summary": cleaned,
            "keywords": [],
            "source": {"doc_id": doc["id"], "filename": doc["filename"]},
        }
    return data


def json_to_markdown(data: dict) -> str:
    title = data.get("title", "AI Summary")
    summary = (data.get("summary") or "").strip()
    keywords = data.get("keywords") or []
    source = data.get("source") or {}
    filename = source.get("filename", "")
    doc_id = source.get("doc_id", "")

    md = f"""### {title} ({filename}, doc_id: {doc_id})

#### Summary
{summary}

#### Keywords
{" ".join(f"`{k}`" for k in keywords)}

---
*(Automatically generated by AI for semantic search.)*
"""
    return md.strip()


def post_comment(doc_id: int, content: str) -> dict:
    url = f"{BASE_URL}/comments/"
    payload = {
        "doc_id": doc_id,
        "chunk_id": None,
        "content": content,
    }
    resp = requests.post(
        url,
        headers={**auth_headers(), "Content-Type": "application/json"},
        json=payload,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    # 1) get doc info
    doc = get_document(DOC_ID)

    # 2) get ALL chunks in ONE call to your endpoint
    all_chunks = get_all_chunks_one_call(DOC_ID)

    # 3) keep only pages we care about
    # note: your sample had page_num 0,1,2,6,10,... so we filter client-side
    selected = [
        c for c in all_chunks
        if c.get("page_num", 999999) <= MAX_DOC_PAGES
    ]

    # sort them in reading order
    selected.sort(key=lambda c: (c.get("page_num", 0), c.get("start_pos") or 0))

    if not selected:
        raise SystemExit("No chunks found in the requested page range.")

    # 4) build prompt and call GPT
    user_prompt = build_user_prompt(doc, selected)
    ai_data = call_gpt(user_prompt, doc)

    # 5) to Markdown for UI + embedding
    md_comment = json_to_markdown(ai_data)

    # 6) send to your /comments/ route
    created = post_comment(DOC_ID, md_comment)
    print("------ AI Comment ------")
    print(md_comment)
    
    print("✅ AI comment created")
    # print("Comment ID:", created["id"])
    
    print("------ content ------")
    print(md_comment)


if __name__ == "__main__":
    main()