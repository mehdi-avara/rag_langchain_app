"""Global draft-and-confirm rules."""


def draft_rules() -> str:
    return "\n".join((
        "For any domain write, prepare a draft only; never perform or claim to perform the domain write.",
        "A user must review the draft and the frontend must commit it through the module's own endpoint.",
        "A committable draft must include target_module, target_action, payload, validation, and commit_target.",
        "The commit_target must include method, endpoint, and permission.",
        "If required values are missing, return a partial draft or ask one focused clarification question.",
    ))
