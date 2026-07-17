"""Global staged-router rules; domain task content is injected as descriptors."""


def module_router_rules(*, allowed_modules: tuple[str, ...]) -> str:
    allowed = ", ".join((*allowed_modules, "general", "clarify"))
    return "\n".join((
        "Select exactly one accessible module that controls the current user message.",
        f"Allowed module values: {allowed}.",
        "The latest user message has priority. Conversation history is context only and must not become a new request.",
        "Do not select a search module merely because the previous assistant message contained search results.",
        "When the current message supplies missing values after a clarification question, continue the same write workflow.",
        "Use only the accessible module descriptors below to interpret domain vocabulary and abbreviations.",
        "Do not mention, infer, compare, or route to a module that is absent from the accessible descriptors.",
        "Interpret Persian and English operational terms from the accessible descriptors and their task examples.",
        "Use general only for model-knowledge or assistant-capability questions.",
        "Use clarify when no allowed module can be selected safely.",
        "Do not infer that an inaccessible module is available and do not name inaccessible modules.",
        "Return JSON: {\"module\": string, \"language\": string, \"confidence\": number, \"clarify_question\": string|null}.",
    ))


def task_router_rules(*, allowed_intents: tuple[str, ...]) -> str:
    allowed = ", ".join((*allowed_intents, "clarify"))
    return "\n".join((
        "Select exactly one task from the selected module; never select a task from another module.",
        f"Allowed intent values: {allowed}.",
        "The latest user message has priority. Use history only to resolve references such as this, that, previous, همان, قبلی, or آخرین.",
        "Do not repeat a search merely because the previous assistant output contained records.",
        "When the user supplies missing draft fields, select the same write task rather than a read or search task.",
        "Words such as بساز، ایجاد کن، اضافه کن، ثبت کن, create, add, and prepare normally indicate a write task.",
        "Words such as پیدا کن، جستجو کن، نمایش بده, find, search, list, and show normally indicate a read task.",
        "Never invent or guess numeric database IDs.",
        "For a reference supplied as a name, code, label, or text, use a *_query, *_name, or *_code slot.",
        "Use a *_id slot only when the user literally supplied a numeric ID for that reference.",
        "Choose a clear write task even when required fields are missing; the draft builder will validate them.",
        "Use clarify when the intended task is unclear or no permitted task applies.",
        "Return JSON: {\"intent\": string, \"language\": string, \"confidence\": number, \"slots\": object, \"clarify_question\": string|null}.",
    ))
