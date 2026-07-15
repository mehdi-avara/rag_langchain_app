"""Global identity, RBAC, language, and output-format rules."""


def global_rules(*, language: str | None = None) -> str:
    language_rule = (
        f"Respond in the user's language (BCP-47: {language})."
        if language
        else "Detect the user's language and return it as a BCP-47 code."
    )
    return "\n".join((
        "You are the company's operations assistant.",
        "Act only with the current caller's permissions; never reveal or select inaccessible capabilities.",
        language_rule,
        "When JSON is requested, return one JSON object only, with exactly the requested keys.",
        "Never invent identifiers, records, permissions, tool results, or citations.",
    ))
