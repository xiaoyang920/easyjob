# 后台长期记忆写入

Main 的一次结构化输出可同时包含业务 action 和 memory_changes。画像和约束仍在请求开始时读取；替换未知历史决策仍需要 retrieve(memory)，取得真实旧 ID 后由下一轮 Main 同时安排业务和变更。后台写入不调用 LLM，也不消耗 Main 的决策轮次。

## 接受与执行

1. 前台核验当前用户原话、已知记录 ID、字段及有效执行代次。在短事务中写入已有的 agent_background_job 表，kind=memory_write，唯一键由 run_id 派生。重复入队复用任务，变更内容不一致则拒绝。
2. LangGraph 中的 user_profile / active_constraints 保留已读取快照。pending_memory_changes 单独保存本轮明确要求，turn_memory_context 为下一轮 Main、检索、子代理和写作构造本轮覆盖。该覆盖不表示长期记忆已保存，也不授予后端关闭的工具权限。
3. 后台用租约领取任务。提交前按 conversation → run → job → profile 的顺序校验和锁定；正常结束的运行仍可保存，已取消、过期或删除会话的任务停止保存。
4. 对画像按字段比较提交时预期值；当前值已等于目标则幂等成功，不同且被其他会话修改则 conflict。约束及决策核验相同范围、稳定 key、真实旧 record_id；替换旧记录与插入新记录在同一事务中完成。
5. MySQL 变更、user_memory_change 回执、memory_index 任务和 memory_write 完成状态一起提交。后台索引任务读取最新有效记录再同步 ES；业务不等待网络同步。技术故障按既有指数退避和最多 8 次尝试重试，语义冲突作为终态处理，不反复重试覆盖。

## 结果反馈

入队成功只确认“后台保存已提交”，不确认已记住。Main 提示词及答复修正禁止提前承诺持久化。入队存储故障保留本轮覆盖并继续业务，同时明确长期记忆未更新；取消或授权失效仍终止执行。

记忆管理接口只向当前用户返回最近任务的公开状态和时间，不返回任务快照、原始错误或执行令牌。页面显示正在保存、已保存、冲突、失败及取消；存在 pending 时每 3 秒刷新，编辑期间不自动刷新。

## 验证

- python-agent/tests/test_background_memory.py：入队无副作用、重放、租约失效、正常结束后保存、取消、并发修改、事务回滚及本轮工具约束。
- test_structured_memory.py：同一次 Main 调用附带变更，不额外调用模型，保存故障不阻断业务，提前成功声明被修正。
- scripts/background-memory-check.py：隔离的本地 MySQL、真实后台 worker 与 Java HTTP。决策 ES 阶段使用模拟适配器，避免调用付费嵌入服务；不代表新增的 ES 性能或模型质量测评。

无需新增记忆表或新服务，复用现有后台任务表和 FastAPI 生命周期中的 worker。
