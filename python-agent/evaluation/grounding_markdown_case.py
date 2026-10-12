"""Independently authored synthetic formatting regression; no production data."""


def markdown_case():
    source = ('A cache stores copies of data. A cache miss may load from authoritative storage. '
              'Failed invalidation can leave a stale value. Retry can help recover failed invalidation, '
              'but does not guarantee strong consistency. TTL limits the lifetime of a cached entry, '
              'but is not an immediate invalidation guarantee. A retry consumer should tolerate duplicate work. '
              'Monitoring and reconciliation can help discover failed work.')
    code = '''```java
void update(Item item) {
    repository.update(item);

    try {
        cache.invalidate(item.id());
    } catch (RuntimeException failure) {
        retries.enqueue(item.id());
    }
}
```'''
    table = ('| Requirement | Conditional suggestion |\n|---|---|\n'
             '| Short stale reads acceptable | Evaluate retry and TTL |\n'
             '| Strict reads needed | Read authoritative storage |')
    cited = ['A cache stores copies of data.',
             'A cache miss may load from authoritative storage.',
             'Failed invalidation can leave a stale value.',
             'Retry does not guarantee strong consistency.',
             'TTL is not an immediate invalidation guarantee.',
             'A retry consumer should tolerate duplicate work.',
             'Monitoring and reconciliation can help discover failed work.']
    sections = [
        ('Overview', cited[0] + '[retrieve_1:1]\n\nThe examples below illustrate options. They are not executed code.'),
        ('Read path', cited[1] + '[retrieve_1:1]\n\nA missing key and an unavailable cache are distinct conditions. Choose a fallback appropriate for the application.'),
        ('Failure', cited[2] + '[retrieve_1:1]\n\nAvoid assuming every dependency succeeds. Consider how to handle an exception and a later retry.'),
        ('Retry boundary', cited[3] + '[retrieve_1:1]\n\nIf immediate visibility is essential, prefer authoritative reads. This is a conditional design suggestion.'),
        ('Illustrative write path', code),
        ('Expiration', cited[4] + '[retrieve_1:1]\n\nChoose expiration based on tolerance for stale data. Measure the behavior before selecting a value.'),
        ('Duplicate work', cited[5] + '[retrieve_1:1]\n\nFor an invalidation consumer, consider repeatable processing. Include duplicate messages in testing.'),
        ('Observability', cited[6] + '[retrieve_1:1]\n\nConsider alerting on retry backlog. Check that reconciliation can locate missing work.'),
        ('Conditional comparison', table),
        ('Validation checklist', '- Simulate a cache outage.\n- Inject an invalidation failure.\n- Deliver a duplicate retry.\n- Compare reads during recovery.'),
        ('Limits', 'This is an illustrative design discussion. It reports no deployment result or measured latency.'),
    ]
    candidate = '\n\n'.join(f'## {title}\n\n{body}' for title, body in sections)
    return {'id': 'long-code-and-table', 'category': 'long_markdown',
        'query': 'Using the provided demonstration notes, explain cache invalidation with illustrative code, conditional recommendations and a table.',
        'source': source, 'candidate': candidate, 'expected': 'verified', 'web': 'not_requested',
        'scripted_kind': 'general_knowledge',
        'scripted_units': {text: {'kind': 'source_fact'} for text in cited},
        'required': [code, table], 'forbidden': ['以下仅为本次已获取的来源摘录']}
