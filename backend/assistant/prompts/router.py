"""Global staged-router rules; domain task content is injected as descriptors."""


def module_router_rules(*, allowed_modules: tuple[str, ...]) -> str:
    allowed = ", ".join((*allowed_modules, "general", "clarify"))
    return "\n".join((
        "Select exactly one accessible module that controls the user's request.",
        f"Allowed module values: {allowed}.",
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
        "Never invent or guess numeric database IDs.",
        "For a reference supplied as a name, code, label, or text, use a *_query, *_name, or *_code slot.",
        "Use a *_id slot only when the user literally supplied a numeric ID for that reference.",
        "Choose a clear write task even when required fields are missing; the draft builder will validate them.",
        "Use clarify when the intended task is unclear or no permitted task applies.",
        "Return JSON: {\"intent\": string, \"language\": string, \"confidence\": number, \"slots\": object, \"clarify_question\": string|null}.",
    ))
