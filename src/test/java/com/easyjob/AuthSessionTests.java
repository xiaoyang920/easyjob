package com.easyjob;

import com.easyjob.entity.User;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.UserMapper;
import com.easyjob.service.AuthSessionService;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.data.redis.core.script.RedisScript;
import java.time.Duration;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class AuthSessionTests {
    private final StringRedisTemplate redis = mock(StringRedisTemplate.class);
    @SuppressWarnings("unchecked")
    private final ValueOperations<String,String> values = mock(ValueOperations.class);
    private final UserMapper users = mock(UserMapper.class);
    private final AuthSessionService service = new AuthSessionService(redis, users);
    private User user() {
        User user = new User(); user.setUserId(7L); user.setStatus(1); user.setPassword("encoded-password"); return user;
    }
    private void session(long absolute) {
        when(redis.opsForValue()).thenReturn(values);
        when(values.get(anyString())).thenReturn("7:" + absolute + ":" + AuthSessionService.digest("encoded-password"));
        when(users.selectById(7L)).thenReturn(user());
    }
    @Test void opaqueCredentialsAreHashedAndIdleExpiryIsBounded() {
        when(redis.opsForValue()).thenReturn(values);
        var session = service.create(user());
        assertEquals(43, session.credential().length());
        assertEquals(AuthSessionService.digest(session.credential()), session.id());
        verify(values).set(eq("auth:session:" + session.id()), anyString(), eq(Duration.ofDays(7)));
        assertEquals(30 * 86400L, session.remainingSeconds());
    }
    @Test void refreshCannotExtendAbsoluteDeadline() {
        session(System.currentTimeMillis() + 120000);
        when(redis.execute(any(RedisScript.class), anyList(), any(), any())).thenReturn(1L);
        var result = service.refresh("a".repeat(43));
        assertTrue(result.remainingSeconds() <= 120);
        assertTrue(result.remainingSeconds() > 0);
        verify(redis).execute(any(RedisScript.class), eq(List.of("auth:session:" + result.id())), any(), eq(String.valueOf(result.remainingSeconds())));
    }
    @Test void logoutRacingRefreshDoesNotRecreateSession() {
        session(System.currentTimeMillis() + 120000);
        when(redis.execute(any(RedisScript.class), anyList(), any(), any())).thenReturn(0L);
        assertThrows(BusinessException.class, () -> service.refresh("a".repeat(43)));
        verify(values, never()).set(anyString(), anyString(), any(Duration.class));
    }
    @Test void passwordChangeInvalidatesRefresh() {
        session(System.currentTimeMillis() + 120000);
        User changed = user(); changed.setPassword("new-password");
        when(users.selectById(7L)).thenReturn(changed);
        assertThrows(BusinessException.class, () -> service.refresh("a".repeat(43)));
        verify(redis).delete("auth:session:" + AuthSessionService.digest("a".repeat(43)));
    }
    @Test void disabledAccountInvalidatesRefresh() {
        session(System.currentTimeMillis() + 120000);
        User disabled = user(); disabled.setStatus(0);
        when(users.selectById(7L)).thenReturn(disabled);
        assertThrows(BusinessException.class, () -> service.refresh("a".repeat(43)));
        verify(redis, never()).execute(any(RedisScript.class), anyList(), any(), any());
    }
    @Test void missingSessionAndExpiredAbsoluteDeadlineAreRejected() {
        when(redis.opsForValue()).thenReturn(values);
        assertThrows(BusinessException.class, () -> service.refresh("a".repeat(43)));
        session(System.currentTimeMillis() - 1000);
        assertThrows(BusinessException.class, () -> service.refresh("a".repeat(43)));
        verify(redis, never()).execute(any(RedisScript.class), anyList(), any(), any());
    }
    @Test void accessTokenIsBoundToSessionOwnerAndLogoutRevokesIt() {
        session(System.currentTimeMillis() + 120000);
        String id = AuthSessionService.digest("a".repeat(43));
        assertTrue(service.valid(id, 7L));
        assertFalse(service.valid(id, 8L));
        service.revoke("a".repeat(43));
        verify(redis).delete("auth:session:" + id);
    }
}
