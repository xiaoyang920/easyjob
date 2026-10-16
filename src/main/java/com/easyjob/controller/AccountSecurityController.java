package com.easyjob.controller;
import com.easyjob.service.AccountSecurityService;
import com.easyjob.service.AuthSessionService;
import com.easyjob.utils.JwtUtil;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ResponseVO;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.*;

@RestController @RequestMapping("/api")
public class AccountSecurityController {
    private final AccountSecurityService security;private final AuthSessionService sessions;private final JwtUtil jwt;
    public AccountSecurityController(AccountSecurityService security,AuthSessionService sessions,JwtUtil jwt){this.security=security;this.sessions=sessions;this.jwt=jwt;}
    public record CodeRequest(String email){}
    public record ResetRequest(String email,String code,String password){}
    public record PasswordRequest(String currentPassword,String newPassword){}
    @PostMapping("/auth/password/code") public ResponseVO<?> code(@RequestBody CodeRequest body,HttpServletRequest request){security.sendCode(body.email(),request.getRemoteAddr());return ResponseVO.success("若邮箱已注册，验证码将在几分钟内送达",null);}
    @PostMapping("/auth/password/reset") public ResponseVO<?> reset(@RequestBody ResetRequest body,HttpServletRequest request){security.reset(body.email(),body.code(),body.password(),request.getRemoteAddr());return ResponseVO.success("密码已更新，请重新登录",null);}
    @PutMapping("/account/password") public ResponseVO<?> password(@RequestBody PasswordRequest body){security.change(UserContext.getUserId(),body.currentPassword(),body.newPassword());return ResponseVO.success("密码已更新，请重新登录",null);}
    private String sid(HttpServletRequest request){return jwt.parseToken(jwt.getTokenFromAuthorization(request.getHeader("Authorization"))).get("sid",String.class);}
    @GetMapping("/account/sessions") public ResponseVO<?> list(HttpServletRequest request){return ResponseVO.success(sessions.devices(UserContext.getUserId(),sid(request)));}
    @DeleteMapping("/account/sessions/{id}") public ResponseVO<?> revoke(@PathVariable String id){sessions.revokeDevice(UserContext.getUserId(),id);return ResponseVO.success(null);}
    @PostMapping("/account/sessions/revoke-others") public ResponseVO<?> others(HttpServletRequest request){sessions.revokeOthers(UserContext.getUserId(),sid(request));return ResponseVO.success(null);}
}
