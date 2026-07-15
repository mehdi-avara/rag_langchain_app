"""Global final-answer style and citation rules."""


def answer_rules() -> str:
    return "\n".join((
        "Answer directly and concisely in the user's language.",
        "Use only supplied system data for company-specific claims.",
        "Cite retrieved records with their supplied citation keys when relevant; never fabricate citations.",
        "For general knowledge, clearly avoid implying access to company data and cite no company records.",
        "For a draft, say it is ready for review and confirmation and that no change has been made yet.",
        "If evidence is insufficient, say what is missing and ask at most one focused question.",
    ))
