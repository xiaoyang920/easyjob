"""Render the completed, synthetic loopback benchmark without inventing production metrics."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def summarize(source, destination):
    report = json.loads(Path(source).read_text(encoding='utf-8'))
    if report.get('passed') is not True or len(report.get('results', [])) != 72:
        raise ValueError('A complete, successful 72-comparison report is required')
    rows = report['results']
    total = sum(sum(row['outcomes'].values()) for row in rows)
    lines = ['## 本机模拟实测结果', '',
        f"记录时间：{datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M %z')}。"
        f"Java {report['java_version']}；{report['available_processors']} 个可用逻辑处理器。"
        f"72组对比，每组3次，共{total}次文章处理。", '',
        '以下耗时是整个文章向量化阶段，包含排队；全部任务（包含失败）计入P95。'
        '模拟接口延迟60～100ms，常规并发容量4，不代表真实智谱接口或生产环境。', '',
        '四消费者、混合文章积压场景，每种配置36篇任务：', '',
        '| 配置：核心/最大/队列/每篇窗口 | 成功/总数 | 文章P95(ms) | 实际最大线程 | 采样排队峰值 |',
        '|---|---:|---:|---:|---:|']
    for row in rows:
        if row['workload'] != 'burst_four_consumers': continue
        success = row['outcomes'].get('success', 0)
        count = sum(row['outcomes'].values())
        lines.append(f"| {row['core']}/{row['max']}/{row['queue']}/{row['article_window']} "
            f"| {success}/{count} | {row['article_p95_ms']:.1f} | {row['largest_pool_size']} | {row['peak_queue_depth']} |")
    burst = {row['profile']: row for row in rows if row['workload'] == 'burst_four_consumers'}
    baseline, default = burst['serial'], burst['fixed4_q8']
    reduction = (1-default['article_p95_ms']/baseline['article_p95_ms'])*100
    lines += ['', f"旧基线4/4/8、每篇2批的P95相对串行配置降低{reduction:.1f}%。"
        '低耗时但大量失败的配置不算性能更好。2/4/16在这一负载下未充分扩容；'
        '8线程突破模拟配额产生429；每篇4批在四消费者同时提交时可能挤满队列；'
        '取消排队会让正常波动直接变成拒绝。', '',
        '同一旧基线配置在不同负载下的结果：', '',
        '| 场景 | 成功/总数 | 文章P95(ms) | 失败类型及数量 |', '|---|---:|---:|---|']
    for row in rows:
        if row['profile'] != 'fixed4_q8': continue
        failures = ', '.join(f'{name}: {count}' for name, count in row['outcomes'].items() if name != 'success') or '无'
        lines.append(f"| {row['workload']} | {row['outcomes'].get('success',0)}/{sum(row['outcomes'].values())} "
            f"| {row['article_p95_ms']:.1f} | {failures} |")
    lines += ['', '容量只有2的模拟供应商下，4线程也会限流；容量8时，8线程可能更快。'
        '因此旧4线程只是当时的保守并发预算，不是未知真实供应商的已测最优值。'
        '队列大小、每篇窗口和消费者数需要一起调整，多实例还要分摊总配额。', '',
        '完整逐任务记录：`logs/embedding-pool-benchmark.json`。收费模型调用次数0，数据库/ES写入次数0。', '']
    consumer_path = ROOT/'logs/embedding-consumer-benchmark.json'
    if consumer_path.exists():
        consumer = json.loads(consumer_path.read_text(encoding='utf-8'))
        if consumer.get('passed') is True and len(consumer.get('results', [])) == 9:
            lines += ['## 相同文章下的消费者数量对比', '',
                '额外对照固定线程池4/4/8、每篇2批，使用同样的文章组合，只改变消费者1/2/4；'
                '每组重复3次，共27次负载运行、252次文章处理。下表是整组文章完成耗时的平均值，'
                '不是文章处理P95。向量接口仍为本机HTTP模拟，200ms存储等待也为模拟，不含真实数据库或ES。', '',
                '| 相同输入场景 | 1消费者(ms) | 2消费者(ms) | 4消费者(ms) |', '|---|---:|---:|---:|']
            for scenario, label in [('short_articles','12篇短文章，每篇8～16块'),
                    ('long_articles','8篇长文章，每篇64块'),
                    ('long_with_storage_wait','同样8篇长文，每篇增加200ms存储等待')]:
                compared = sorted((row for row in consumer['results'] if row['scenario'] == scenario), key=lambda row: row['consumers'])
                if [row['consumers'] for row in compared] != [1,2,4] or any(
                        row['same_article_chunks'] != compared[0]['same_article_chunks'] for row in compared):
                    raise ValueError('Consumer comparison must use identical article inputs')
                lines.append('| '+label+' | '+' | '.join(f"{row['mean_whole_workload_ms']:.1f}" for row in compared)+' |')
            lines += ['', '在这组容量4、共享线程4的旧对照下，消费者2～4是保守选择：两篇多批次文章已能用满4个向量化线程；'
                '短文章或写入等待时，增加到4可填补空闲。实际动态扩容不是瞬间发生，'
                '上表模拟固定消费者数量，未验证真实RabbitMQ容器扩容速度。'
                '现有文章锁在整个索引期间持有数据库连接，不能仅按CPU核数继续增加消费者。', '',
                '只运行本对照：`EASYJOB_EMBEDDING_BENCHMARK=1 mvn -Dtest=EmbeddingPoolBenchmarkTests#compareConsumerLimitsOnSameInputs test`。'
                '原始结果：`logs/embedding-consumer-benchmark.json`。', '']
    window_path = ROOT/'logs/embedding-window-benchmark.json'
    if window_path.exists():
        windows = json.loads(window_path.read_text(encoding='utf-8'))
        if windows.get('passed') is True and len(windows.get('results', [])) == 6:
            lines += ['## 每篇并行窗口与大队列的直接对比', '',
                '补充对照固定共享线程池4/4、模拟供应商容量4，只调整每篇窗口和队列。'
                '每个场景使用相同输入重复3次；单篇场景为512块，混合场景为4消费者处理'
                '[512,8,16,64,128,8,32,16]块的8篇文章。', '',
                '| 每篇窗口/队列 | 单篇512块平均完成(ms) | 混合场景整组平均完成(ms) | 混合场景短文章P95(ms) |',
                '|---|---:|---:|---:|']
            for profile,label in [('window2_q8','2批/8'),('window4_q16','4批/16'),('all_batches_q128','整篇全部提交/128')]:
                single = next(row for row in windows['results'] if row['profile'] == profile and row['scenario'] == 'single_512_chunks')
                mixed = next(row for row in windows['results'] if row['profile'] == profile and row['scenario'] == 'mixed_with_short_articles')
                lines.append(f"| {label} | {single['mean_whole_workload_ms']:.1f} | {mixed['mean_whole_workload_ms']:.1f} "
                    f"| {mixed['short_article_processing_p95_ms']:.1f} |")
            lines += ['', '如果目标更偏向当前单机博客的单篇索引速度，4批/队列16是更均衡的候选：'
                '单篇速度接近整篇全部提交，短文章等待明显更少。2批/队列8更偏向文章间公平性，'
                '但只有一篇长文时只能使用2个工作线程。当时仅新增对照测试，后续容量100的联合对照与默认参数调整见下文。'
                '该结论仍来自模拟接口，不代表真实供应商的最优配置。', '',
                '原始结果：`logs/embedding-window-benchmark.json`。只运行本对照：'
                '`EASYJOB_EMBEDDING_BENCHMARK=1 mvn -Dtest=EmbeddingPoolBenchmarkTests#compareArticleWindowsOnSameInputs test`。', '']
    capacity_summary = None
    capacity_path = ROOT/'logs/embedding-capacity100-benchmark.json'
    if capacity_path.exists():
        capacity = json.loads(capacity_path.read_text(encoding='utf-8'))
        if capacity.get('passed') is True and len(capacity.get('results', [])) == 81:
            capacity_rows = capacity['results']
            article_trials = sum(sum(row['outcomes'].values()) for row in capacity_rows)
            for scenario in {row['scenario'] for row in capacity_rows}:
                compared = [row for row in capacity_rows if row['scenario'] == scenario]
                if any(row['same_article_chunks'] != compared[0]['same_article_chunks'] for row in compared):
                    raise ValueError('Capacity comparison must use identical article inputs')
            if any(set(row['outcomes']) != {'success'} or row['provider_429'] for row in capacity_rows):
                raise ValueError('Capacity comparison contains failures; do not rank it solely by latency')
            lines += ['## 容量100时，消费者与工作线程的联合对照', '',
                f"新增81组配置与场景对比，每组重复3次，共{capacity['completed_workload_runs']}次负载运行、"
                f"{article_trials}次文章处理，全部成功。模拟接口允许100并发，服务端也配置100个处理线程，"
                '避免模拟服务本身把高并发压到16。接口延迟仍为60～100ms，HTTP只发送批次标识并返回成功状态；'
                '2048维向量由夹具生成，不包含真实向量JSON响应的传输与解析成本。未调用真实向量模型，'
                '未测真实数据库、Redis、RabbitMQ或ES。截图中的embedding-3-pro额度不能证明项目所配置embedding-3的额度。', '',
                '固定消费者数量2/4/8、固定工作线程4/8/16、每篇窗口2/4做联合对照。'
                '队列取max(8, 消费者数×每篇窗口)，为窗口内的任务提供足够等待空间。'
                '消费者由调用线程模拟，未测RabbitMQ从2扩容到最大值的等待时间。'
                '每轮随机化配置执行顺序，使用相同文章组合。', '',
                '| 消费者/线程/每篇窗口/队列 | 24短文完成(ms) | 12长文完成(ms) | 12长文＋存储等待(ms) | 24混合＋存储等待(ms) | 混合端到端P95(ms) |',
                '|---|---:|---:|---:|---:|---:|']
            for consumers in [2,4,8]:
                for threads in [4,8,16]:
                    for window in [2,4]:
                        compared = {row['scenario']: row for row in capacity_rows
                            if row['consumers'] == consumers and row['core'] == threads and row['article_window'] == window}
                        mixed = compared['mixed_with_storage_wait']
                        values = [compared[name]['mean_whole_workload_ms'] for name in
                            ['short_backlog','long_backlog','long_with_storage_wait','mixed_with_storage_wait']]
                        lines.append(f"| {consumers}/{threads}/{window}/{mixed['queue']} | "
                            +' | '.join(f'{value:.1f}' for value in values)
                            +f" | {mixed['article_end_to_end_p95_ms']:.1f} |")
            lines += ['', '以上“完成耗时”是整组文章全部处理完的平均值；端到端P95从文章进入模拟待处理队列开始，'
                '包含等待消费者、向量化排队、执行和模拟存储等待。原来的processing指标从消费者接手后开始，'
                '本报告同时保留两种口径及每篇文章的等待时间，避免增加消费者仅改变统计起点而误判。', '']
            mixed_by_profile = {row['profile']: row for row in capacity_rows if row['scenario'] == 'mixed_with_storage_wait'}
            original_mix = mixed_by_profile['c4_t4_w2_q8']
            eight_mix = mixed_by_profile['c4_t8_w4_q16']
            sixteen_mix = mixed_by_profile['c4_t16_w4_q16']
            improvement_eight = (1-eight_mix['mean_whole_workload_ms']/original_mix['mean_whole_workload_ms'])*100
            improvement_sixteen = (1-sixteen_mix['mean_whole_workload_ms']/eight_mix['mean_whole_workload_ms'])*100
            lines += [f"固定4消费者时，8线程/每篇4批/队列16在混合场景比4线程/每篇2批/队列8平均耗时降低{improvement_eight:.1f}%；"
                f"继续从8增加到16线程，混合场景平均耗时再降低{improvement_sixteen:.1f}%。"
                '现已按用户要求将4消费者、8线程、每篇4批、队列16设为默认值，仍需真实联调验证；批量长文导入可进一步评估16线程。'
                '原2～4表示初始2消费者、动态最多4，不能将固定4消费者的耗时直接当成原2～4配置的实际耗时。', '',
                '单篇512块诊断，只有一个消费者，使用不同线程数与每篇窗口：', '',
                '| 共享线程数 | 每篇窗口 | 平均完成(ms) | 服务端在途峰值 |', '|---|---:|---:|---:|']
            for row in capacity_rows:
                if row['scenario'] == 'single_512_chunks':
                    lines.append(f"| {row['core']} | {row['article_window']} | {row['mean_whole_workload_ms']:.1f} "
                        f"| {row['peak_provider_concurrency']} |")
            lines += ['', '服务端在途计数包含发送响应后的清理过程，客户端收到完整响应、开始下一批时，'
                '旧服务端处理器可能尚未退出，因此服务端峰值可以短暂高于客户端工作线程数。'
                '线程池上限按本地活跃线程和队列校验，服务端计数按供应商容量校验。', '',
                '此对照检验“100额度时原参数是否仍有性能余量”，不能直接证明真实生产最优配置。'
                'API额度是上限，当前文章索引还会在整个处理期间占用文章锁的数据库连接；'
                '提高到8个消费者前需验证连接池余量和真实ES吞吐。短文章每篇只有一个批次，'
                '增加每篇窗口不能让它同时提交更多批次。单篇长文的并发受每篇窗口限制。', '',
                '测量完成后已更新代码、本地配置及示例配置的默认值为8/8/16、每篇4批、固定4消费者，重启Java后生效。'
                '原始结果：`logs/embedding-capacity100-benchmark.json`。'
                '只跑本组：`powershell -ExecutionPolicy Bypass -File scripts/embedding-pool-benchmark.ps1 -Capacity100Only`。', '']
            if capacity.get('validation_replayed_from_completed_measurements'):
                lines += ['全部243次测量与3915次文章处理完成后，首次最终校验错误地要求“服务端在途峰值≤客户端线程数”。'
                    '修正该统计断言后，对保存的完整测量记录复核成功，耗时数据未改动；另外重新执行8线程的本机HTTP冒烟测试，'
                    '连同36条相关功能回归共37条测试通过。首次运行日志为`logs/embedding-capacity100-benchmark.log`，'
                    '修正后的校验日志为`logs/embedding-capacity100-validation.log`。', '']
            capacity_summary = {'synthetic': True, 'provider_capacity_assumption': 100,
                'comparisons': len(capacity_rows), 'workload_runs': capacity['completed_workload_runs'],
                'article_trials': article_trials, 'paid_model_calls': 0,
                'mixed_results': [{key: row[key] for key in ['profile','consumers','core','queue','article_window',
                    'mean_whole_workload_ms','article_end_to_end_p95_ms','short_article_end_to_end_p95_ms',
                    'peak_provider_concurrency','peak_queued_batches']} for row in capacity_rows
                    if row['scenario'] == 'mixed_with_storage_wait']}
    target = Path(destination)
    original = target.read_text(encoding='utf-8')
    marker = '<!-- measured-results -->'
    if marker not in original: raise ValueError('Missing results marker')
    target.write_text(original.split(marker)[0]+marker+'\n\n'+'\n'.join(lines), encoding='utf-8')
    summary = {'synthetic': True, 'article_trials': total, 'comparisons': len(rows),
        'historical_baseline': {key: default[key] for key in ['core','max','queue','article_window']},
        'current_defaults': {'core': 8, 'max': 8, 'queue': 16, 'article_window': 4, 'consumers': 4},
        'burst_serial_p95_ms': baseline['article_p95_ms'], 'burst_default_p95_ms': default['article_p95_ms'],
        'burst_p95_reduction_percent': reduction, 'paid_model_calls': 0}
    if capacity_summary is not None:
        summary['capacity100_comparison'] = capacity_summary
    (ROOT/'logs/embedding-pool-summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default=str(ROOT/'logs/embedding-pool-benchmark.json'))
    parser.add_argument('--destination', default=str(ROOT/'docs/embedding-pool.md'))
    args = parser.parse_args()
    summarize(args.source, args.destination)
