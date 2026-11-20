"""Current-turn instructions are usable before their durable memory write finishes."""
from copy import deepcopy
from app.models.user_profile import normalize_profile
from app.models.memory_identity import canonical_key


def turn_memory_context(state):
    profile = deepcopy(normalize_profile(state.get('user_profile') or {}))
    constraints = deepcopy(state.get('active_constraints', []))
    for index, change in enumerate(state.get('pending_memory_changes', [])):
        kind, key, operation = change['kind'], change['key'], change['operation']
        if kind == 'profile':
            if key.startswith('preferences.'):
                field = key.removeprefix('preferences.')
                if operation == 'remove': profile['preferences'].pop(field, None)
                else: profile['preferences'][field] = change['value']
            else:
                profile[key] = ([] if key == 'topics' else 'unknown') if operation == 'remove' else change['value']
        elif kind == 'constraint':
            constraints = [c for c in constraints if not (c.get('scope', 'conversation') == change['scope']
                and canonical_key('constraint', c.get('key')) == key)]
            if operation == 'set':
                constraints.append({'id': f'turn:{index}', 'type': 'constraint', 'key': key,
                    'content': change['value'], 'scope': change['scope'], 'pending': True})
    return {'user_profile': profile, 'active_constraints': constraints}
