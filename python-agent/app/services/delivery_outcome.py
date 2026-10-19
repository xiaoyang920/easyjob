"""Execution settlement and completion of the user's request are separate facts."""


def incomplete_delivery(result):
    # Older contract stops settled normally but recorded their stopped audit in
    # progress. Project that known outcome without rewriting historical rows.
    return result.get('delivery_status') == 'incomplete' or (
        ((result.get('progress') or {}).get('decision_contract_audit') or {}).get('last_outcome') == 'stopped')
