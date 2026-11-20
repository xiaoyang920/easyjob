package com.easyjob.auth;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.util.Map;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
class SessionContractTests {
    @Test @SuppressWarnings("unchecked")void revokedSessionCannotBeRecreatedByRefresh()throws Exception{
        StringRedisTemplate redis=mock(StringRedisTemplate.class);ValueOperations values=mock(ValueOperations.class);when(redis.opsForValue()).thenReturn(values);AccountStore accounts=mock(AccountStore.class);ObjectMapper json=new ObjectMapper();String credential=Sessions.random();String sid=Sessions.digest(credential);
        when(values.get(Sessions.PREFIX+sid)).thenReturn(json.writeValueAsString(Map.of("uid",7,"ver",2,"deadline",System.currentTimeMillis()+100000)));
        when(accounts.byId(7)).thenReturn(new AccountStore.Account(7,"qa@example.invalid","hash","qa",null,1,1,2));
        when(redis.execute(any(org.springframework.data.redis.core.script.RedisScript.class),anyList(),any(Object[].class))).thenReturn(0L);
        Sessions sessions=new Sessions(redis,accounts,json);org.springframework.test.util.ReflectionTestUtils.setField(sessions,"idle",604800L);
        assertThrows(AuthFailure.class,()->sessions.refresh(credential));verify(values,never()).set(anyString(),anyString(),any(java.time.Duration.class));
    }
    @Test void invalidAndDisabledAccountsAreRejected(){assertThrows(AuthFailure.class,()->Sessions.enabled(null));assertThrows(AuthFailure.class,()->Sessions.enabled(new AccountStore.Account(7,"qa@example.invalid","hash","qa",null,1,0,2)));}
}
