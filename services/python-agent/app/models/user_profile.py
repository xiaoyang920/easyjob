"""Blog-oriented profile with lossless reads of the two legacy topic columns."""
import json


def merge_topics(*groups):
    topics, seen = [], set()
    for group in groups:
        for value in group or []:
            text = value.strip()
            if text and text.casefold() not in seen:
                topics.append(text)
                seen.add(text.casefold())
    return topics


def normalize_profile(profile):
    def field(name, default):
        value = profile.get(name)
        return json.loads(value) if isinstance(value, str) and name != 'experience' else value or default
    # Physical interests is retained for schema compatibility. All new writes
    # put topics there and empty tech_stack, so deleted topics cannot reappear.
    topics = merge_topics(field('topics', []), field('interests', []), field('tech_stack', []))
    return {'topics': topics, 'experience': profile.get('experience') or 'unknown',
            'preferences': field('preferences', {})}
