# 登录续签

旧方案只有固定7天JWT，401即清空前端登录状态。新浏览器登录包含：

- 访问JWT默认30分钟，带用户ID和会话摘要sid；原有Authorization调用方式保持一致。
- 256位随机续签凭证仅放入HttpOnly、SameSite=Strict Cookie，Path=/api/auth；Redis仅存凭证SHA-256摘要对应的会话。
- 会话7天未续签失效，单次登录绝对期限30天。Cookie在绝对期限到期，服务端刷新空闲期限，不能超过绝对期限。
- /api/auth/refresh 和 /api/auth/logout 必须POST，携带 X-Auth-Refresh: 1；拒绝浏览器cross-site请求。
- 刷新时检查账号状态及密码版本；退出删除Redis会话，带sid的访问JWT也立即失效。没有启用刷新凭证轮换，采用服务端可撤销的固定浏览器会话凭证。
- HTTPS代理部署必须设置 AUTH_COOKIE_SECURE=true（也可用easyjob.jwt.cookie-secure配置），使Cookie仅通过HTTPS发送。不要开放带凭据的跨站CORS；前端通过同源/api代理访问。

前端Axios、AI fetch/SSE握手、XHR上传共用单次续签；提前60秒检查，明确401最多重试一次。开始收到流式内容后不重新执行AI任务。通知和WebSocket重新连接前获取有效Token。可见页面的近期用户操作、窗口重新获得焦点，以及真实API请求触发检查；后台标签页不持续心跳续签。断网或服务5xx不会清除登录状态。

仍有效的旧JWT在页面启动时可迁移成新会话；已过期旧JWT没有续签Cookie，必须重新登录一次。迁移期内旧无sid JWT继续使用其原有效期，旧Token尚不具备服务端即时撤销能力。刷新后的Cookie响应不反复重写，避免迟到的旧刷新覆盖新登录Cookie；前端也防止迟到的刷新覆盖退出/切换账号后的本地状态。

配置（无需数据库迁移）：

| 配置 | 默认值 |
|---|---:|
| easyjob.jwt.access-ttl | 1800000毫秒 |
| easyjob.jwt.refresh-idle-seconds | 604800秒 |
| easyjob.jwt.refresh-max-seconds | 2592000秒 |

验证：

```powershell
# 仓库根目录，服务运行后：只创建和清理独立临时用户，不记录凭据
python-agent/.venv/Scripts/python.exe scripts/auth-renewal-smoke.py
# 前端并发、网络故障、退出/切换账号竞态
cd frontend
npm run test:auth
```

Redis不可用时受保护API返回503，不伪装成登录过期；服务恢复后可重试。刷新失效时才清理本地登录并提示重新登录。密码变化/账号禁用在续签时核验并撤销该会话；除显式退出外，已签发访问JWT在下次续签前仍可能有效，最长30分钟。当前会话存储需要与现有Redis保持一致的持久化和高可用配置。
