package com.easyjob;

import com.easyjob.component.RedisComponent;
import com.easyjob.controller.AuthController;
import com.easyjob.dto.UserAuthDTO;
import com.easyjob.entity.User;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.UserMapper;
import com.easyjob.service.AuthSessionService;
import com.easyjob.utils.JwtUtil;
import com.easyjob.utils.PasswordUtil;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.data.redis.core.script.RedisScript;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Duration;
import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class AuthRegistrationTests {
    private final AuthController controller = new AuthController();
    private final UserMapper users = mock(UserMapper.class);
    private final RedisComponent codes = mock(RedisComponent.class);
    private final AuthSessionService sessions = mock(AuthSessionService.class);
    private final JwtUtil jwt = mock(JwtUtil.class);
    private final MockHttpServletRequest request = new MockHttpServletRequest();
    private final MockHttpServletResponse response = new MockHttpServletResponse();

    AuthRegistrationTests() {
        ReflectionTestUtils.setField(controller, "userMapper", users);
        ReflectionTestUtils.setField(controller, "redisComponent", codes);
        ReflectionTestUtils.setField(controller, "sessions", sessions);
        ReflectionTestUtils.setField(controller, "jwtUtil", jwt);
        when(codes.getCheckCode("register@example.invalid")).thenReturn("123456");
        when(users.insert(any(User.class))).thenAnswer(invocation -> {
            User user = invocation.getArgument(0);
            user.setUserId(9007199254740993L);
            return 1;
        });
        when(sessions.create(any(User.class))).thenAnswer(invocation ->
            new AuthSessionService.Session("browser-credential", "session-id", invocation.getArgument(0), 2592000));
        when(jwt.generateSessionToken(9007199254740993L, "session-id")).thenReturn("access-token");
    }

    private UserAuthDTO body() {
        UserAuthDTO body = new UserAuthDTO();
        body.setNickName("  新读者  "); body.setEmail("register@example.invalid");
        body.setPassword("test-password"); body.setCode("123456");
        return body;
    }

    @Test void registrationReturnsLoginIdentityAndRenewableHttpOnlyCookie() {
        request.setCookies(new Cookie("easyjob_refresh", "previous-session"));
        var result = controller.register(body(), request, response);
        assertEquals(200, result.getCode());
        Map<?, ?> data = (Map<?, ?>) result.getData();
        assertEquals("access-token", data.get("token"));
        assertEquals("9007199254740993", data.get("userId"));
        assertEquals("新读者", data.get("nickName"));
        assertEquals("register@example.invalid", data.get("email"));
        assertTrue(data.containsKey("avatar"));
        assertFalse(data.containsKey("password"));
        assertFalse(data.containsKey("credential"));
        String cookie = response.getHeader("Set-Cookie");
        assertNotNull(cookie);
        assertTrue(cookie.contains("easyjob_refresh=browser-credential"));
        assertTrue(cookie.contains("HttpOnly"));
        assertTrue(cookie.contains("SameSite=Strict"));
        assertTrue(cookie.contains("Path=/api/auth"));
        assertTrue(cookie.contains("Max-Age=2592000"));
        assertEquals("no-store", response.getHeader("Cache-Control"));
        verify(sessions).revoke("previous-session");
        verify(users).touchLogin(9007199254740993L);
        verify(codes).deleteCheckCode("register@example.invalid");
        var saved = ArgumentCaptor.forClass(User.class);
        verify(users).insert(saved.capture());
        assertTrue(PasswordUtil.matches("test-password", saved.getValue().getPassword()));
        assertEquals(1, saved.getValue().getStatus());
        assertEquals(1, saved.getValue().getRole());
    }

    @Test void secureRequestsAlsoProtectTheRegistrationCookie() {
        request.setSecure(true);
        controller.register(body(), request, response);
        assertTrue(response.getHeader("Set-Cookie").contains("Secure"));
    }

    @Test void invalidCodeCannotCreateUserOrSignIn() {
        var body = body(); body.setCode("000000");
        assertThrows(BusinessException.class, () -> controller.register(body, request, response));
        verify(users, never()).insert(any(User.class));
        verifyNoInteractions(sessions, jwt);
        assertNull(response.getHeader("Set-Cookie"));
    }

    @Test void duplicateAccountCannotReceiveAnAutomaticLoginSession() {
        when(users.selectOne(any())).thenReturn(new User());
        assertThrows(BusinessException.class, () -> controller.register(body(), request, response));
        verify(users, never()).insert(any(User.class));
        verifyNoInteractions(sessions, jwt);
        assertNull(response.getHeader("Set-Cookie"));
    }

    @Test void failedInsertCannotIssueCredentials() {
        doReturn(0).when(users).insert(any(User.class));
        assertThrows(BusinessException.class, () -> controller.register(body(), request, response));
        verifyNoInteractions(sessions, jwt);
        assertNull(response.getHeader("Set-Cookie"));
    }

    @Test @SuppressWarnings("unchecked")
    void registrationTokenCanRefreshAndIsRevokedByLogoutWithoutAnotherLogin() {
        // Use the real session and JWT implementations; substitute only external stores.
        var redis = mock(StringRedisTemplate.class);
        ValueOperations<String, String> values = mock(ValueOperations.class);
        Map<String, String> stored = new HashMap<>();
        Map<Long, User> accounts = new HashMap<>();
        when(redis.opsForValue()).thenReturn(values);
        doAnswer(invocation -> { stored.put(invocation.getArgument(0), invocation.getArgument(1)); return null; })
            .when(values).set(anyString(), anyString(), any(Duration.class));
        when(values.get(anyString())).thenAnswer(invocation -> stored.get(invocation.getArgument(0)));
        when(redis.delete(anyString())).thenAnswer(invocation -> stored.remove(invocation.getArgument(0)) != null);
        when(redis.execute(any(RedisScript.class), anyList(), any(), any())).thenReturn(1L);
        doAnswer(invocation -> {
            User user = invocation.getArgument(0); user.setUserId(7L); accounts.put(7L, user); return 1;
        }).when(users).insert(any(User.class));
        when(users.selectById(anyLong())).thenAnswer(invocation -> accounts.get(invocation.getArgument(0)));
        var realSessions = new AuthSessionService(redis, users);
        var realJwt = new JwtUtil();
        ReflectionTestUtils.setField(realJwt, "secret", "isolated-registration-test-signing-key-".repeat(3));
        ReflectionTestUtils.setField(realJwt, "sessions", realSessions);
        ReflectionTestUtils.setField(controller, "sessions", realSessions);
        ReflectionTestUtils.setField(controller, "jwtUtil", realJwt);

        Map<?, ?> identity = (Map<?, ?>) controller.register(body(), request, response).getData();
        String token = (String) identity.get("token");
        assertEquals(7L, realJwt.getUserIdFromToken(token));
        String credential = response.getHeader("Set-Cookie").split(";", 2)[0].split("=", 2)[1];
        var refresh = new MockHttpServletRequest();
        refresh.addHeader("X-Auth-Refresh", "1");
        refresh.setCookies(new Cookie("easyjob_refresh", credential));
        var renewed = controller.refresh(refresh, new MockHttpServletResponse());
        assertEquals("7", ((Map<?, ?>) renewed.getData()).get("userId"));
        assertTrue(realJwt.validateToken((String) ((Map<?, ?>) renewed.getData()).get("token")));
        controller.logout(refresh, new MockHttpServletResponse());
        assertFalse(realJwt.validateToken(token));
        assertThrows(BusinessException.class, () -> controller.refresh(refresh, new MockHttpServletResponse()));
    }
}
