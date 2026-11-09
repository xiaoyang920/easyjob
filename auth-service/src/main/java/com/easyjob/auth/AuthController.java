package com.easyjob.auth;

import com.easyjob.security.*;
import com.easyjob.security.IdentityTokens.Principal;
import com.nimbusds.jose.jwk.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.oauth2.jwt.JwtEncoder;
import jakarta.servlet.http.*;
import java.util.*;
import java.nio.charset.StandardCharsets;
import com.easyjob.auth.AccountStore.Account;
import com.easyjob.auth.AuthController.Check;
import com.easyjob.auth.Sessions.Session;
import com.nimbusds.jose.jwk.JWK;
import com.nimbusds.jose.jwk.RSAKey;
import jakarta.servlet.http.Cookie;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.stream.Stream;

@RestController
public class AuthController {
    private final AccountStore accounts;private final Sessions sessions;private final VerificationCodes codes;
    private final RSAKey signing;private final JwtEncoder encoder;private final String issuer;private final boolean secure;private final int accessSeconds;private final java.nio.file.Path keyFolder;
    private static final String COOKIE="easyjob_refresh";private static final BCryptPasswordEncoder PASSWORD=new BCryptPasswordEncoder();
    public AuthController(AccountStore accounts,Sessions sessions,VerificationCodes codes,@Value("${auth.private-key-file}")String path,@Value("${auth.issuer}")String issuer,@Value("${auth.cookie-secure:false}")boolean secure,@Value("${auth.access-seconds:1800}")int ttl){this.accounts=accounts;this.sessions=sessions;this.codes=codes;this.issuer=issuer;this.secure=secure;accessSeconds=ttl;signing=IdentityTokens.key(path);encoder=IdentityTokens.encoder(signing);keyFolder=java.nio.file.Path.of(path).toAbsolutePath().getParent();}
    public record Login(String email,String password,String nickName,String code){}
    public record Password(String currentPassword,String newPassword){}
    public record Reset(String email,String code,String password){}
    public record Check(String userId,String sid,long version){}
    public record Security(long expectedVersion,int role,int status,String commandId,String reason){}
    static Map<String,Object> ok(Object data){LinkedHashMap<String, Object> body=new LinkedHashMap<String,Object>();body.put("code",200);body.put("message","操作成功");body.put("data",data);return body;}
    static Principal identity(HttpServletRequest request){return (Principal)request.getAttribute("identity");}
    static String cookie(HttpServletRequest request){if(request.getCookies()!=null)for(Cookie cookie:request.getCookies())if(COOKIE.equals(cookie.getName()))return cookie.getValue();return null;}
    private void cookie(HttpServletRequest req,HttpServletResponse res,String value,long seconds){res.addHeader("Set-Cookie",ResponseCookie.from(COOKIE,value).httpOnly(true).secure(secure||req.isSecure()).sameSite("Strict").path("/api/auth").maxAge(seconds).build().toString());res.setHeader("Cache-Control","no-store");}
    private void browser(HttpServletRequest request){if(!"1".equals(request.getHeader("X-Auth-Refresh"))||"cross-site".equals(request.getHeader("Sec-Fetch-Site")))throw new AuthFailure(403,"不允许跨站登录操作");}
    static void password(String text,int minimum){if(text==null||text.length()<minimum||text.getBytes(StandardCharsets.UTF_8).length>72)throw new AuthFailure(400,"密码长度不符合要求，最多72字节");}
    private boolean matches(String raw,String hash){if(raw==null||hash==null||raw.getBytes(StandardCharsets.UTF_8).length>72)return false;return hash.startsWith("$2")?PASSWORD.matches(raw,hash):java.security.MessageDigest.isEqual(raw.getBytes(StandardCharsets.UTF_8),hash.getBytes(StandardCharsets.UTF_8));}
    private String token(Sessions.Session session){Account user=session.account();return IdentityTokens.issue(encoder,signing.getKeyID(),issuer,"easyjob-api",IdentityTokens.ACCESS,new Principal(Long.toString(user.id()),session.sid(),user.version(),List.of()),accessSeconds,null,null,null);}
    private Map<String,Object> signedIn(AccountStore.Account user,HttpServletRequest req,HttpServletResponse res){
        Sessions.enabled(user);sessions.logout(cookie(req));Session session=sessions.create(user,req.getHeader("User-Agent"));accounts.touch(user.id());cookie(req,res,session.credential(),session.remaining());
        LinkedHashMap<String, Object> data=new LinkedHashMap<String,Object>();data.put("token",token(session));data.put("userId",Long.toString(user.id()));data.put("email",user.email());data.put("nickName",user.name());data.put("avatar",user.avatar());return ok(data);
    }
    @PostMapping("/api/auth/login") public Map<String,Object> login(@RequestBody Login input,HttpServletRequest req,HttpServletResponse res){
        String email=VerificationCodes.email(input.email());codes.limit("login:"+email,20,300);Account user=accounts.byEmail(email);
        if(user==null||!matches(input.password(),user.password()))throw new AuthFailure(401,"邮箱或密码错误");
        if(!user.password().startsWith("$2")){user=accounts.upgrade(user,PASSWORD.encode(input.password()));if(user==null||!matches(input.password(),user.password()))throw new AuthFailure(401,"账号信息已变化");}
        return signedIn(user,req,res);
    }
    @PostMapping("/api/auth/register") public Map<String,Object> register(@RequestBody Login input,HttpServletRequest req,HttpServletResponse res){
        String email=VerificationCodes.email(input.email());password(input.password(),8);String name=input.nickName()==null?"":input.nickName().strip();if(name.length()<2||name.length()>20)throw new AuthFailure(400,"昵称需为2至20字");
        codes.consume(email,"login",input.code());long id;do{id=new java.security.SecureRandom().nextLong()&Long.MAX_VALUE;}while(id==0);
        return signedIn(accounts.register(id,email,name,PASSWORD.encode(input.password())),req,res);
    }
    @PostMapping("/api/auth/send-code")public Map<String,Object> code(@RequestBody Login input){codes.send(VerificationCodes.email(input.email()),"login",true);return ok(null);}
    @PostMapping("/api/auth/login-by-email")public Map<String,Object> email(@RequestBody Login input,HttpServletRequest req,HttpServletResponse res){String email=VerificationCodes.email(input.email());codes.consume(email,"login",input.code());Account user=accounts.byEmail(email);if(user==null)throw new AuthFailure(401,"邮箱或验证码无效");return signedIn(user,req,res);}
    @PostMapping("/api/auth/refresh")public Map<String,Object> refresh(HttpServletRequest req,HttpServletResponse res){browser(req);Session session=sessions.refresh(cookie(req));res.setHeader("Cache-Control","no-store");return ok(Map.of("token",token(session),"userId",Long.toString(session.account().id())));}
    @PostMapping("/api/auth/logout")public Map<String,Object> logout(HttpServletRequest req,HttpServletResponse res){browser(req);sessions.logout(cookie(req));cookie(req,res,"",0);return ok(null);}
    @PostMapping("/api/auth/password/code")public Map<String,Object> resetCode(@RequestBody Login input){String email=VerificationCodes.email(input.email());Account user=accounts.byEmail(email);codes.send(email,"reset",user!=null&&user.status()==1);return ok(null);}
    @PostMapping("/api/auth/password/reset")public Map<String,Object> reset(@RequestBody Reset input){String email=VerificationCodes.email(input.email());password(input.password(),8);codes.limit("reset:"+email,20,600);codes.consume(email,"reset",input.code());Account user=accounts.byEmail(email);Sessions.enabled(user);accounts.password(user,PASSWORD.encode(input.password()),"password_reset");return ok(null);}
    @PutMapping("/api/account/password")public Map<String,Object> change(@RequestBody Password input,HttpServletRequest req){Principal p=identity(req);codes.limit("password:"+p.userId(),5,300);password(input.newPassword(),8);Account user=accounts.byId(Long.parseLong(p.userId()));if(!matches(input.currentPassword(),user.password()))throw new AuthFailure(400,"当前密码不正确");accounts.password(user,PASSWORD.encode(input.newPassword()),"password_change");return ok(null);}
    @GetMapping("/api/account/sessions")public Map<String,Object> devices(HttpServletRequest req){Principal p=identity(req);return ok(sessions.devices(Long.parseLong(p.userId()),p.sid()));}
    @DeleteMapping("/api/account/sessions/{sid}")public Map<String,Object> revoke(@PathVariable String sid,HttpServletRequest req){sessions.revoke(Long.parseLong(identity(req).userId()),sid);return ok(null);}
    @PostMapping("/api/account/sessions/revoke-others")public Map<String,Object> others(HttpServletRequest req){Principal p=identity(req);sessions.revokeOthers(Long.parseLong(p.userId()),p.sid());return ok(null);}
    @GetMapping("/api/auth/jwks")public Map<String,Object> jwks()throws java.io.IOException{
        LinkedHashMap<String, JWK> keys=new LinkedHashMap<String,JWK>();keys.put(signing.getKeyID(),signing.toPublicJWK());
        try(Stream<Path> files=java.nio.file.Files.list(keyFolder)){files.filter(p->p.getFileName().toString().matches("auth-published-public-[a-zA-Z0-9_-]+\\.json")).sorted().limit(8).forEach(p->{RSAKey key=IdentityTokens.key(p.toString()).toPublicJWK();keys.put(key.getKeyID(),key);});}
        return new JWKSet(new ArrayList<>(keys.values())).toJSONObject();
    }
    @PostMapping("/internal/auth/session/check")public Map<String,Object> check(@RequestBody Check input){return ok(sessions.check(input.userId(),input.sid(),input.version()));}
    @PostMapping("/internal/auth/session/batch")public Map<String,Object> batch(@RequestBody List<Check> input){if(input.size()>100)throw new AuthFailure(400,"检查数量过多");LinkedHashMap<String, Boolean> result=new LinkedHashMap<String,Boolean>();for(Check item:input)try{sessions.check(item.userId(),item.sid(),item.version());result.put(item.sid(),true);}catch(AuthFailure inactive){result.put(item.sid(),false);}return ok(result);}
    @GetMapping("/api/admin/accounts/{id}/security")public Map<String,Object> security(@PathVariable long id,HttpServletRequest req){if(!identity(req).roles().contains("2"))throw new AuthFailure(403,"需要管理员权限");Account user=accounts.byId(id);if(user==null)throw new AuthFailure(404,"用户不存在");return ok(Map.of("role",user.role(),"status",user.status(),"version",Long.toString(user.version())));}
    @PutMapping("/api/admin/accounts/{id}/security")public Map<String,Object> security(@PathVariable long id,@RequestBody Security input,HttpServletRequest req){if(input.commandId()==null||!input.commandId().matches("[a-fA-F0-9-]{36}")||input.reason()==null||input.reason().isBlank()||input.reason().length()>300)throw new AuthFailure(400,"操作编号或原因无效");accounts.security(Long.parseLong(identity(req).userId()),id,input.expectedVersion(),input.role(),input.status(),input.commandId(),input.reason());return ok(null);}
    @RestControllerAdvice public static class Errors {
        @ExceptionHandler(AuthFailure.class)ResponseEntity<?> auth(AuthFailure e){return ResponseEntity.status(e.status).body(Map.of("code",e.status,"message",e.getMessage()));}
        @ExceptionHandler(org.springframework.dao.DuplicateKeyException.class)ResponseEntity<?> duplicate(){return ResponseEntity.status(409).body(Map.of("code",409,"message","账号信息已存在，请重新检查"));}
        @ExceptionHandler(org.springframework.http.converter.HttpMessageNotReadableException.class)ResponseEntity<?> bad(){return ResponseEntity.badRequest().body(Map.of("code",400,"message","请求参数无效"));}
        @ExceptionHandler(Exception.class)ResponseEntity<?> unavailable(Exception e){org.slf4j.LoggerFactory.getLogger(Errors.class).warn("Auth operation failed: {}",e.getClass().getSimpleName());return ResponseEntity.status(503).body(Map.of("code",503,"message","认证服务暂不可用，请稍后重试"));}
    }
}
