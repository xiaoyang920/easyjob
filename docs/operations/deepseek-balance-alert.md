# DeepSeek 余额邮件预警

Java 后端启动完成后，独立线程定期读取 DeepSeek 官方 `GET https://api.deepseek.com/user/balance`。使用现有 `spring.ai.deepseek.api-key`，不会调用模型或消耗模型 token。接口说明：https://api-docs.deepseek.com/zh-cn/api/get-user-balance/ 。

## 本地启用

在 `python-agent/.env.runtime.local` 配置以下键（已为本次需求启用）：

```dotenv
DEEPSEEK_BALANCE_ALERT_ENABLED=true
DEEPSEEK_BALANCE_ALERT_THRESHOLD=2.00
DEEPSEEK_BALANCE_ALERT_CURRENCY=CNY
DEEPSEEK_BALANCE_ALERT_RECIPIENT=2752683077@qq.com
DEEPSEEK_BALANCE_ALERT_INTERVAL_SECONDS=600
```

`scripts/prepare-local.py` 将这些配置写入 `temp/application-runtime.yml` 的 `deepseek.balance-alert`。修改配置后重新生成本地配置并重启 Java。源码示例默认关闭，未配置收件人时不可启用。SMTP 复用 `spring.mail` 账户；API 密钥和邮件授权码不能写入代码或日志。

启用前应用迁移 `python-agent/migrations/028_provider_balance_monitor.sql`，通过 `app.migrate.apply_product_features` 记录版本和校验和。已有数据库只需应用此新增迁移，无须重建表。

## 判断与重试

- 只判断指定币种的 `total_balance`，包含未过期赠金与充值余额；不混加人民币和美元。
- **余额 < 2 元**发邮件；正好 2 元不触发。低余额持续期间不重复发，恢复到 >= 2 元后重新启用。
- 请求失败、响应格式错误、找不到指定币种不会被当成余额为零，保留最后一次成功结果。
- 正常每 600 秒检查；失败按 60、120、240、480、600 秒退避。独立工作线程每 15 秒判断是否到期，因此实际检查会有少量延迟。
- 邮件失败保留待发提醒，重试前重新查余额；如果已充值恢复则取消待发提醒。
- 后端需要持续在线；停机期间无法检查或发送，重启后会处理已到期检查。

## 持久化与并发

MySQL `provider_balance_monitor` 保存最后余额、检查时间、下次执行时间、失败原因、提醒编号与发送状态。`low + alert_id + alert_sent_at IS NULL` 表示待发邮件。使用行锁和 120 秒租约避免多个实例重复检查，过期执行者不能覆盖当前执行者状态。更换 API 账户、收件人或阈值会重置提醒周期。账户只保存密钥的 SHA-256 指纹，不保存密钥。

HTTP 禁止跳转且有限时；邮件客户端使用现有 SMTP 配置的副本，设置连接、读写超时，不改变验证码邮件配置。

普通轮询和重启可以去重。SMTP 接受邮件和数据库更新不能组成一个事务，若恰在两者之间崩溃，恢复后可能重复发送；不能承诺严格的“恰好一次”。邮件内带提醒编号便于核对。SMTP 接受也不等于收件箱投递成功，仍可能被邮箱归为垃圾邮件。

查看运行状态（时间统一存为 UTC）：

```sql
SELECT monitor_key, currency, threshold_amount, balance_amount, alert_state,
       last_checked_at, next_check_at, alert_sent_at, failure_count, last_error_code
FROM provider_balance_monitor WHERE monitor_key = 'deepseek-default:CNY';
```

关闭功能：将 `DEEPSEEK_BALANCE_ALERT_ENABLED=false`，重新生成配置并重启 Java，数据库历史保留。

## 验证

`BalanceAlertTest` 检查金额边界、响应格式、固定 API 地址、邮件内容与客户端配置隔离。
`BalanceAlertDatabaseTest` 在真实 MySQL 的独立 `balance-test-*` 行上验证去重、恢复重置、失败重试、并发抢占和租约隔离。API 与 SMTP 均为模拟，不发送测试邮件，测试结束删除自己的状态行。

数据库测试需要环境变量 `BALANCE_ALERT_DB_TEST=true`、`BALANCE_ALERT_DB_URL`、`BALANCE_ALERT_DB_USER`、`BALANCE_ALERT_DB_PASSWORD`，后者应从本地配置注入进程，禁止把密码作为命令行参数。

2026-10-26 本地验证：5 项单元测试、5 项真实 MySQL 测试及 7 项已有账户安全测试全部通过，打包成功。SMTP 完成连接、STARTTLS 和身份验证，未发送测试邮件。启用后的首次后台自动检查在北京时间 11:13:32 查得余额 4.79 元，失败数 0，下一次检查为 11:23:32，未触发邮件。测试状态行已清理。
