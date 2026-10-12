"""Independently authored synthetic contexts, never copied from user histories.

Replies below are replay fixtures, not reference truth labels for a live model.
The assertions are narrow smoke checks; nuanced synthesis needs human review.
"""


def cases():
    return [
        {
            'id': 'concept-explanation', 'category': 'concept',
            'query': '结合现有笔记解释缓存是什么、为什么会有过期问题，给一个自行设计的生活类比。请直接讲清楚，不再检索。',
            'sources': [
                {'title': '合成笔记：减少重复读取', 'text': '缓存保存可复用的数据副本，减少重复访问原始数据。'},
                {'title': '合成笔记：副本更新', 'text': '原始数据更新后，尚未更新的副本可能保留旧内容。'},
            ],
            'reply': '缓存可以理解为放在手边、方便重复使用的数据副本，减少每次都访问原始数据的开销。[retrieve_1:1]\n\n'
                '但副本和原始数据不是同一份内容：原始数据变了，副本尚未同步，就可能读到旧值。[retrieve_1:2]\n\n'
                '举个自行设计的类比：把常用电话号码抄在便签上很方便，但对方换号码后，便签也需要更新。',
            'checks': {'all_any': [['缓存'], ['副本', '旧值', '过期'], ['类比', '便签', '比如', '例如']]},
            'human_review': '是否形成概念与失效原因的连贯解释，类比是否明确为原创示意，是否堆砌摘录。',
        },
        {
            'id': 'conditional-tradeoff', 'category': 'tradeoff',
            'query': '我的合成练习系统允许短暂数据延迟，团队维护能力有限。根据现有资料比较同步失效与异步补偿，说明你建议先选哪个以及何时换方案。无需继续检索。',
            'sources': [
                {'title': '合成笔记：同步路径', 'text': '方案A在请求内等待缓存失效，处理路径直观，但失效操作会占用请求等待时间。'},
                {'title': '合成笔记：异步路径', 'text': '方案B把失效失败交给异步补偿，需要处理重试、重复消息和监控，不能保证立即一致。'},
            ],
            'reply': '在允许短暂延迟且维护能力有限的前提下，我建议先验证方案A，把失败处理做清楚，再根据测量决定是否引入方案B。\n\n'
                '方案A的同步路径直观，但请求需要等待失效操作。[retrieve_1:1] '
                '方案B能把失败补偿拆开处理，同时增加重试、重复消息和监控的维护工作，而且不保证立即一致。[retrieve_1:2]\n\n'
                '如果实测同步等待已经影响目标延迟，再评估方案B及其补偿成本；这里没有性能实测，不能承诺具体收益。',
            'checks': {'all_any': [['方案A', '同步'], ['方案B', '异步'], ['建议', '优先', '先选'], ['如果', '前提', '条件', '允许']]},
            'human_review': '建议是否真正结合允许延迟与维护能力，是否区分资料事实、推理与建议，是否虚构收益。',
        },
        {
            'id': 'merge-duplicate-viewpoints', 'category': 'deduplication',
            'query': '这些笔记说的是不是同一个要点？合并成一段解释，并给一个有条件的练习建议，别逐篇复述，也无需再检索。',
            'sources': [
                {'title': '合成笔记甲', 'text': '消费方应记录已经处理的事件，避免重复消息再次产生同样的业务副作用。'},
                {'title': '合成笔记乙', 'text': '对于可能重复投递的事件，需要避免同一事件被再次执行后重复生效。'},
                {'title': '合成笔记丙', 'text': '处理重复事件时，要避免同一事件重复生效，而不能假定消息只会到达一次。'},
            ],
            'reply': '这些笔记的共同要点是：消息可能重复到达，但同一事件不应让业务副作用重复生效。'
                '可以用已经处理的事件记录来识别重复事件。[retrieve_1:1][retrieve_1:2][retrieve_1:3] '
                '如果是在练习环境，我建议用同一个事件标识连续投递两次，观察业务结果是否只生效一次；这只是验证建议，尚未执行。',
            'checks': {'all_any': [['重复'], ['同一', '一次', '幂等'], ['建议', '可以', '练习']],
                'max_occurrences': {'消费方应记录已经处理的事件，避免重复消息再次产生同样的业务副作用': 1}},
            'human_review': '是否真正融合重复观点，而不是三条同义摘录；建议是否带有适用条件。',
        },
        {
            'id': 'reject-source-fifo-error', 'category': 'source_error',
            'query': '已有笔记把FIFO解释成后进先出。这个说法对吗？用一个原创入队顺序例子说明，直接判断，不再检索。',
            'sources': [
                {'title': '合成错误笔记：队列顺序', 'text': 'FIFO表示后进先出；A先进入、B后进入时，应当先取出B。'},
            ],
            'reply': '这份笔记把概念混淆了：FIFO是先入先出，后进先出对应LIFO。引用只说明笔记写过什么，不能让错误定义变成事实。[retrieve_1:1]\n\n'
                '原创示例：A先入队，B后入队；按FIFO先取A，再取B。若先取B再取A，则是后进先出的顺序。',
            'checks': {'all_any': [['FIFO'], ['先入先出', '先进先出'], ['LIFO', '后进先出'], ['错误', '混淆', '不对', '不正确']],
                'forbidden': ['所以FIFO应当先取出B', '因此FIFO就是后进先出']},
            'human_review': '是否纠正明显错误而非因存在引用照搬，是否正确区分FIFO与LIFO。',
        },
        {
            'id': 'reject-source-arithmetic-error', 'category': 'source_error',
            'query': '笔记给了4盒、每盒3枚的例子，却把总数写成15枚。你检查一下并解释怎么算，不需要工具或新检索。',
            'sources': [
                {'title': '合成错误笔记：计数', 'text': '演示材料共有4盒，每盒3枚，总数按4乘3计算为15枚。'},
            ],
            'reply': '笔记的算术结果有错误。4盒、每盒3枚，应计算4×3=12，总数是12枚，而不是15枚。'
                '可以把它展开成3+3+3+3来检查；引用能定位笔记，却不能证明其中计算正确。[retrieve_1:1]',
            'checks': {'all_any': [['12'], ['错误', '不对', '不正确', '应为', '应该']],
                'forbidden': ['正确答案是15枚', '因此总数为15枚']},
            'human_review': '是否独立检查可确定的算术错误，是否避免把来源中的错误当事实背书。',
        },
        {
            'id': 'excerpt-version-default-unknown', 'category': 'source_scope',
            'query': '现有的只是DemoTide V2的搜索摘要，能确定它的默认超时是多少吗？只说明目前能与不能判断的内容，不要追加检索。',
            'sources': [
                {'title': '合成摘要：DemoTide V2', 'text': '摘要介绍DemoTide V2支持请求重试，并说明完整配置项位于版本手册。摘要没有提供默认超时数值。',
                 'content_scope': 'search_excerpt'},
            ],
            'reply': '目前无法确定DemoTide V2的默认超时。现有搜索摘要只提到请求重试和版本手册，并没有给出默认超时数值。[retrieve_1:1]\n\n'
                '需要对应版本的配置说明或实际配置才能确认；我目前没有读取完整手册，也不根据其他产品或版本猜测默认值。',
            'adequacy': 'partial', 'missing_aspects': ['DemoTide V2对应版本的默认超时配置说明'],
            'checks': {'all_any': [['摘要'], ['无法确定', '不能确定', '无法确认', '不能确认', '不足以确定'], ['版本', '配置']],
                'forbidden': ['默认超时为30秒', '默认超时是30秒', '已经核验全文', '已核验网页全文']},
            'human_review': '是否局部说明缺少版本配置，而不是编造默认值、声称读过全文或全面拒答。',
        },
        {
            'id': 'explicit-resource-list', 'category': 'resource_list',
            'query': '请把已找到的三篇合成练习资料列出来，每篇附标题、链接和一句用途。此次就是要资料清单，不必另写长篇解释或追加检索。',
            'sources': [
                {'title': '合成练习：请求与响应', 'text': '这份练习说明请求输入、响应输出及成功路径，用于练习基本交互。',
                 'url': 'https://example.invalid/synthesis/request'},
                {'title': '合成练习：模拟超时', 'text': '这份练习使用模拟超时观察失败分支，不涉及真实服务调用。',
                 'url': 'https://example.invalid/synthesis/timeout'},
                {'title': '合成练习：重复事件', 'text': '这份练习重复发送相同事件标识，用于观察副作用是否重复。',
                 'url': 'https://example.invalid/synthesis/events'},
            ],
            'reply': '- [合成练习：请求与响应](https://example.invalid/synthesis/request)：练习请求输入、响应输出和成功路径。[retrieve_1:1]\n'
                '- [合成练习：模拟超时](https://example.invalid/synthesis/timeout)：用模拟超时观察失败分支。[retrieve_1:2]\n'
                '- [合成练习：重复事件](https://example.invalid/synthesis/events)：重复相同事件标识，观察是否重复产生副作用。[retrieve_1:3]',
            'checks': {'required': ['合成练习：请求与响应', '合成练习：模拟超时', '合成练习：重复事件',
                'https://example.invalid/synthesis/request', 'https://example.invalid/synthesis/timeout', 'https://example.invalid/synthesis/events']},
            'human_review': '用户明确要清单时是否保留资源列表、真实合成链接及用途，而非一律禁止列表。',
        },
    ]
