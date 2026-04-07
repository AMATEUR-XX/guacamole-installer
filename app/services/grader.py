import re


def grade_config(config_text: str, check_rules_text: str) -> tuple[int, str]:
    rules = [r.strip() for r in check_rules_text.splitlines() if r.strip()]
    if not rules:
        return 0, "No rules configured for this lab"

    matched = 0
    feedback = []
    for rule in rules:
        if re.search(rule, config_text, flags=re.IGNORECASE | re.MULTILINE):
            matched += 1
            feedback.append(f"[OK] {rule}")
        else:
            feedback.append(f"[FAIL] {rule}")

    score = int((matched / len(rules)) * 100)
    return score, "\n".join(feedback)
