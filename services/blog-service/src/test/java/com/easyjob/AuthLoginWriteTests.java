package com.easyjob;

import com.easyjob.component.RedisComponent;
import com.easyjob.controller.AuthController;
import com.easyjob.dto.EmailDTO;
import com.easyjob.dto.UserAuthDTO;
import com.easyjob.entity.User;
import com.easyjob.mapper.UserMapper;
import com.easyjob.service.AuthSessionService;
import com.easyjob.service.UserService;
import com.easyjob.utils.JwtUtil;
import com.easyjob.utils.PasswordUtil;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import static org.mockito.Mockito.*;

/** Login with a previously loaded object must not write stale management fields. */
class AuthLoginWriteTests {
    final UserMapper users=mock(UserMapper.class);
    final AuthSessionService sessions=mock(AuthSessionService.class);
    final RedisComponent redis=mock(RedisComponent.class);
    final UserService userService=mock(UserService.class);
    final AuthController controller=new AuthController();
    final User user=new User();
    AuthLoginWriteTests(){
        user.setUserId(7L);user.setEmail("local@example.invalid");user.setNickName("测试账号");
        user.setRole(2);user.setStatus(1);user.setAuthVersion(0L);user.setPassword(PasswordUtil.encode("test-password"));
        ReflectionTestUtils.setField(controller,"userMapper",users);
        ReflectionTestUtils.setField(controller,"sessions",sessions);
        ReflectionTestUtils.setField(controller,"jwtUtil",mock(JwtUtil.class));
        ReflectionTestUtils.setField(controller,"redisComponent",redis);
        ReflectionTestUtils.setField(controller,"userService",userService);
        when(sessions.create(user)).thenReturn(new AuthSessionService.Session("credential","id",user,120));
    }
    @Test void passwordLoginTouchesOnlyLoginTime(){
        when(users.selectOne(any())).thenReturn(user);
        UserAuthDTO body=new UserAuthDTO();body.setEmail(user.getEmail());body.setPassword("test-password");
        controller.login(body,mock(HttpServletRequest.class),mock(HttpServletResponse.class));
        verify(users).touchLogin(7L);verify(users,never()).updateById(any(User.class));
    }
    @Test void verificationCodeLoginAlsoCannotRestoreStaleRoleOrStatus(){
        when(redis.getCheckCode(user.getEmail())).thenReturn("123456");when(userService.getUserByEmail(user.getEmail())).thenReturn(user);
        EmailDTO body=new EmailDTO();body.setEmail(user.getEmail());body.setCode("123456");
        controller.loginByEmail(body,mock(HttpServletRequest.class),mock(HttpServletResponse.class));
        verify(users).touchLogin(7L);verify(users,never()).updateById(any(User.class));
    }
}
