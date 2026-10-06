package com.easyjob.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.easyjob.component.RedisComponent;
import com.easyjob.constants.RedisConstants;
import com.easyjob.dto.EmailDTO;
import com.easyjob.dto.JwtResponse;
import com.easyjob.dto.UserAuthDTO;
import com.easyjob.exception.BusinessException;
import com.easyjob.service.EmailService;
import com.easyjob.service.UserService;
import com.easyjob.utils.PasswordUtil;
import com.easyjob.utils.StringTools;
import com.easyjob.vo.AuthVO;
import com.easyjob.vo.ResponseVO;
import com.easyjob.entity.User;
import com.easyjob.mapper.UserMapper;
import com.easyjob.utils.JwtUtil;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private static final String REFRESH_COOKIE = "easyjob_refresh";
    @Autowired
    private com.easyjob.service.AuthSessionService sessions;
    @org.springframework.beans.factory.annotation.Value("${easyjob.jwt.cookie-secure:false}")
    private boolean secureCookie;

    private void sessionCookie(jakarta.servlet.http.HttpServletRequest request,
                               jakarta.servlet.http.HttpServletResponse response,
                               String value, long seconds) {
        response.addHeader("Set-Cookie", org.springframework.http.ResponseCookie.from(REFRESH_COOKIE, value)
            .httpOnly(true).secure(secureCookie || request.isSecure()).sameSite("Strict")
            .path("/api/auth").maxAge(seconds).build().toString());
        response.setHeader("Cache-Control", "no-store");
    }

    private String cookie(jakarta.servlet.http.HttpServletRequest request) {
        if (request.getCookies() != null) for (jakarta.servlet.http.Cookie c : request.getCookies())
            if (REFRESH_COOKIE.equals(c.getName())) return c.getValue();
        return null;
    }

    private void requireBrowserHeader(jakarta.servlet.http.HttpServletRequest request) {
        // Non-simple header plus SameSite cookie: a cross-site form cannot refresh or revoke.
        if (!"1".equals(request.getHeader("X-Auth-Refresh"))
                || "cross-site".equals(request.getHeader("Sec-Fetch-Site")))
            throw new BusinessException(403, "不允许跨站登录操作");
    }

    @PostMapping("/refresh")
    public ResponseVO<?> refresh(jakarta.servlet.http.HttpServletRequest request,
                                  jakarta.servlet.http.HttpServletResponse response) {
        requireBrowserHeader(request);
        com.easyjob.service.AuthSessionService.Session session;
        String credential = cookie(request);
        if (credential == null) {
            // One-time migration for still-valid legacy JWTs; expired tokens never extend themselves.
            String token = jwtUtil.getTokenFromAuthorization(request.getHeader("Authorization"));
            try {
                if (jwtUtil.parseToken(token).get("sid") != null) throw new BusinessException(401, "续签凭证不存在");
                session = sessions.create(userMapper.selectById(jwtUtil.getUserIdFromToken(token)));
            } catch (io.jsonwebtoken.JwtException | IllegalArgumentException e) {
                throw new BusinessException(401, "登录已过期，请重新登录");
            }
        } else session = sessions.refresh(credential);
        // The browser cookie expires at the absolute deadline. Sliding the Redis idle
        // deadline needs no Set-Cookie, avoiding old refresh responses overwriting a new login.
        if (credential == null) sessionCookie(request, response, session.credential(), session.remainingSeconds());
        response.setHeader("Cache-Control", "no-store");
        Map<String, Object> data = new HashMap<>();
        data.put("token", jwtUtil.generateSessionToken(session.user().getUserId(), session.id()));
        data.put("userId", session.user().getUserId().toString());
        return ResponseVO.success(data);
    }

    @PostMapping("/logout")
    public ResponseVO<?> logout(jakarta.servlet.http.HttpServletRequest request,
                                 jakarta.servlet.http.HttpServletResponse response) {
        requireBrowserHeader(request);
        sessions.revoke(cookie(request));
        sessionCookie(request, response, "", 0);
        return ResponseVO.success(null);
    }

    @Autowired
    private JwtUtil jwtUtil;
    @Autowired
    private UserMapper userMapper;
    @Autowired
    private RedisComponent redisComponent;
    @Autowired
    private EmailService emailService;
    @Autowired
    private UserService userService;

    @PostMapping("/login")
    public ResponseVO<?> login(@RequestBody UserAuthDTO authDTO,
                              jakarta.servlet.http.HttpServletRequest request,
                              jakarta.servlet.http.HttpServletResponse response) {
        String email = authDTO.getEmail();
        String password = authDTO.getPassword();
        // 根据邮箱查询用户
        User user = userMapper.selectOne(new LambdaQueryWrapper<User>().eq(User::getEmail, email));
        // 验证用户是否存在以及密码是否正确
        boolean passwordMatch;
        if (user == null ) {
            throw new BusinessException(401, "邮箱或密码错误");
        }
        if(PasswordUtil.isEncoded(user.getPassword())){
            //新密码：使用了加密
            passwordMatch = PasswordUtil.matches(password, user.getPassword());
        }else {
            //旧密码：未加密，直接比较
            passwordMatch = password.equals(user.getPassword());
            //如果验证通过，则更新为加密密码
            if (passwordMatch) {
                user.setPassword(PasswordUtil.encode(password));
                userMapper.updateById(user);
            }
        }
        if (!passwordMatch) {
            throw new BusinessException(401, "邮箱或密码错误");
        }
        // 生成token，包含用户ID
        sessions.revoke(cookie(request));
        var session = sessions.create(user);
        sessionCookie(request, response, session.credential(), session.remainingSeconds());
        String token = jwtUtil.generateSessionToken(user.getUserId(), session.id());
        // 返回响应
        Map<String, Object> data = new HashMap<>();
        data.put("token", token);
        data.put("userId", String.valueOf(user.getUserId()));  // 转成字符串避免精度丢失
        data.put("email", email);
        data.put("nickName", user.getNickName());
        data.put("avatar", user.getAvatar());

        // 更新用户信息
        user.setLastLoginTime(LocalDateTime.now());
        userMapper.updateById(user);
        return ResponseVO.success("登录成功", data);
    }

    @PostMapping("/register")
    public ResponseVO<?> register(@RequestBody UserAuthDTO authDTO) {
        String nickName = authDTO.getNickName();
        String email = authDTO.getEmail();
        String password = authDTO.getPassword();
        String code = authDTO.getCode(); // 新增：接收验证码
        
        // 验证昵称长度
        if (nickName == null || nickName.trim().length() < 2 || nickName.trim().length() > 20) {
            throw new BusinessException("昵称长度应在2-20个字符之间");
        }
        
        // 验证密码长度
        if (password == null || password.length() < 6) {
            throw new BusinessException("密码长度至少为6个字符");
        }
        
        // 新增：校验验证码是否为空
        if (StringTools.isEmpty(code)) {
            throw new BusinessException("请输入邮箱验证码");
        }
        
        // 新增：从 Redis 获取验证码并校验
        String checkCode = redisComponent.getCheckCode(email);
        if (StringTools.isEmpty(checkCode)) {
            throw new BusinessException("验证码已过期，请重新获取");
        }
        if (!checkCode.equals(code)) {
            throw new BusinessException("验证码错误");
        }
        
        // 检查邮箱是否已存在
        User existingUser = userMapper.selectOne(new LambdaQueryWrapper<User>().eq(User::getEmail, email));
        if (existingUser != null) {
            throw new BusinessException("该邮箱已被注册");
        }
        
        // 检查昵称是否已存在
        User existingNickName = userMapper.selectOne(new LambdaQueryWrapper<User>().eq(User::getNickName, nickName.trim()));
        if (existingNickName != null) {
            throw new BusinessException("该昵称已被使用");
        }
        
        // 验证码正确，删除 Redis 中的验证码（避免重复使用）
        redisComponent.deleteCheckCode(email);
        
        // 创建新用户
        User newUser = new User();
        newUser.setNickName(nickName.trim());
        newUser.setEmail(email);
        newUser.setPassword(PasswordUtil.encode(password));
        newUser.setJoinTime(LocalDateTime.now());
        newUser.setStatus(1); // 默认正常状态
        newUser.setRole(1); // 默认普通用户
        newUser.setTheme(1); // 默认主题
        newUser.setTotalCoinCount(10); // 初始硬币
        newUser.setCurrentCoinCount(10);
        newUser.setArticleCount(0);
        newUser.setFollowerCount(0);
        newUser.setFollowingCount(0);
        
        // 保存到数据库
        int result = userMapper.insert(newUser);
        if (result <= 0) {
            throw new BusinessException(500, "注册失败，请稍后重试");
        }
        
        // 注册成功
        Map<String, Object> data = new HashMap<>();
        data.put("userId", String.valueOf(newUser.getUserId()));  // 转成字符串避免精度丢失
        data.put("nickName", newUser.getNickName());
        data.put("email", newUser.getEmail());
        return ResponseVO.success("注册成功", data);
    }
    /**
     * 通过邮箱登录
     * @param emailDTO
     * @return
     */
//    @PostMapping("/login-by-email")
//    public ResponseVO loginByEmail(@RequestBody EmailDTO emailDTO) {
//
//    }

    /**
     * 发送验证码
     * @param emailDTO
     * @return
     */
    @PostMapping("/send-code")
    public ResponseVO<?> sendCode(@RequestBody EmailDTO emailDTO) {
        // 验证邮箱格式
        String email = emailDTO.getEmail();
        if (!email.matches("^[a-zA-Z0-9_-]+@[a-zA-Z0-9_-]+(\\.[a-zA-Z0-9_-]+)+$")) {
            throw new BusinessException(400, "邮箱格式错误");
        }
        // 检查是否频繁发送
        if(redisComponent.hasKey(RedisConstants.REDIS_KEY_CHECK_CODE+email)){
            throw new BusinessException(400, "请勿频繁发送验证码");
        }
        // 生成验证码
        String code = StringTools.code(6);
        // 保存验证码到redis
        redisComponent.saveCheckCode(email,code);
        // 记录发送时间，方式频繁发送
        redisComponent.saveTimeKey(email);
        //发送邮件
        try {
            emailService.sendVerificationCode(email, code);
            return ResponseVO.success("验证码已发送");
        } catch (Exception e) {
            return ResponseVO.error("发送失败，请稍后重试");
        }
    }
    @PostMapping("/login-by-email")
    public ResponseVO<?> loginByEmail(@RequestBody EmailDTO emailDTO,
                                     jakarta.servlet.http.HttpServletRequest request,
                                     jakarta.servlet.http.HttpServletResponse response) {
        String email = emailDTO.getEmail();
        String code = emailDTO.getCode();
        if(StringTools.isEmpty( email)|| StringTools.isEmpty(code)){
            throw new BusinessException(400, "邮箱或验证码不能为空");
        }
        String key = RedisConstants.REDIS_KEY_CHECK_CODE + email;
        String checkCode = redisComponent.getCheckCode(email);
        if(StringTools.isEmpty(checkCode)){
            throw new BusinessException(400, "验证码已过期");
        }
        if(!checkCode.equals(code)){
            throw new BusinessException(400, "验证码错误");
        }
        // 验证码正确，删除redis中的验证码
        redisComponent.deleteCheckCode(email);
        User user = userService.getUserByEmail(email);
        if(user == null){
            throw new BusinessException(400, "邮箱尚未注册");
        }
        sessions.revoke(cookie(request));
        var session = sessions.create(user);
        sessionCookie(request, response, session.credential(), session.remainingSeconds());
        String token = jwtUtil.generateSessionToken(user.getUserId(), session.id());

        AuthVO authVO = new AuthVO();
        authVO.setToken(token);
        authVO.setUserId(user.getUserId().toString());
        authVO.setNickName(user.getNickName());
        authVO.setEmail(user.getEmail());
        authVO.setAvatar(user.getAvatar());
        // 更新用户信息
        user.setLastLoginTime(LocalDateTime.now());
        userMapper.updateById(user);
        return ResponseVO.success("登录成功", authVO);
    }
}
