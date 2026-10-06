"""Conservative identities for known fields; no fuzzy merging of user decisions."""
CONSTRAINT_ALIASES = {
    'article_audience': ('article_audience', 'audience', 'target_audience', 'reader_level', 'article_reader'),
    'response_language': ('response_language', 'answer_language', 'reply_language'),
    'response_detail': ('response_detail', 'answer_detail', 'reply_detail', 'detail_level'),
    'web_search': ('web_search',),
}
VALUE_ALIASES = {
    'article_audience': {'初学者': '面向初学者', '新手': '面向初学者', '面向新手': '面向初学者',
                         '入门读者': '面向初学者', '面向入门读者': '面向初学者'},
    'response_language': {'zh': '中文', 'zh-cn': '中文', 'en': '英文', 'english': '英文'},
    'response_detail': {'brief': '简洁', '简短': '简洁', 'detailed': '详细'},
}


def canonical_value(kind, key, value):
    if kind != 'constraint' or not isinstance(value, str): return value
    return VALUE_ALIASES.get(canonical_key(kind, key), {}).get(value.strip().lower(), value.strip())


def canonical_key(kind, key):
    if kind == 'constraint':
        return next((canonical for canonical, aliases in CONSTRAINT_ALIASES.items() if key in aliases), key)
    return key


def key_aliases(kind, key):
    key = canonical_key(kind, key)
    return CONSTRAINT_ALIASES.get(key, (key,)) if kind == 'constraint' else (key,)


class MemoryConflict(ValueError):
    """A rolled-back mutation needs user clarification, not an automatic overwrite."""
