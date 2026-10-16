package com.easyjob.service;
import com.easyjob.config.*;
import com.easyjob.entity.User;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.*;
import com.easyjob.utils.PasswordUtil;
import org.junit.jupiter.api.*;
import org.springframework.data.redis.core.*;
import org.springframework.data.redis.core.script.RedisScript;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class AccountSecurityTests {
    AccountSecurityMapper users=mock(AccountSecurityMapper.class);
    StringRedisTemplate redis=mock(StringRedisTemplate.class);
    EmailService mail=mock(EmailService.class);
    ChatWebSocketHandler chats=mock(ChatWebSocketHandler.class);
    ArticleWebSocketHandler articles=mock(ArticleWebSocketHandler.class);
    AccountSecurityService service=new AccountSecurityService(users,redis,mail,chats,articles);
    @BeforeEach @SuppressWarnings("unchecked") void setup(){when(redis.execute(any(RedisScript.class),anyList(),any())).thenReturn(1L);}
    User user(){var u=new User();u.setUserId(7L);u.setStatus(1);u.setPassword(PasswordUtil.encode("current-password"));return u;}
    @Test void newPasswordPolicyRejectsShortAndOver72BytesBeforeTouchingDatabase(){
        assertThrows(BusinessException.class,()->service.change(7L,"current","short"));
        assertThrows(BusinessException.class,()->service.change(7L,"current","密".repeat(25)));
        verifyNoInteractions(users);
    }
    @Test void wrongCurrentPasswordNeverChangesCredentials(){when(users.lockUser(7L)).thenReturn(user());assertThrows(BusinessException.class,()->service.change(7L,"wrong-password","new-password"));verify(users,never()).changePassword(anyLong(),anyString());}
    @Test void passwordChangesStoreHashAndCloseExistingSockets(){when(users.lockUser(7L)).thenReturn(user());when(users.changePassword(eq(7L),anyString())).thenReturn(1);service.change(7L,"current-password","new-password");verify(users).changePassword(eq(7L),argThat(hash->PasswordUtil.matches("new-password",hash)));verify(chats).disconnectUser(7L);verify(articles).disconnectUser(7L);}
    @Test void expiredOrInvalidResetCodeCannotChangePassword(){when(redis.execute(any(RedisScript.class),anyList(),any())).thenReturn(0L);assertThrows(BusinessException.class,()->service.reset("test@example.invalid","123456","new-password","local"));verifyNoInteractions(users);}
    @Test void unknownEmailReturnsWithoutRevealingAnAccountOrSendingMail(){service.sendCode("test@example.invalid","local");verifyNoInteractions(mail);verify(users).findByEmail("test@example.invalid");}
    @Test void anotherUsersDeviceCannotBeRevoked(){
        var values=mock(ValueOperations.class);when(redis.opsForValue()).thenReturn(values);when(values.get(anyString())).thenReturn("8:9999999999999:hash:0");
        var sessions=new AuthSessionService(redis,mock(UserMapper.class));assertThrows(BusinessException.class,()->sessions.revokeDevice(7L,"a".repeat(64)));verify(redis,never()).delete(anyList());
    }
    @Test void mapperInvalidationIncrementsAuthVersion(){
        assertDoesNotThrow(()->{var xml=java.nio.file.Files.readString(java.nio.file.Path.of("src/main/resources/mapper/AccountSecurityMapper.xml"));assertTrue(xml.contains("auth_version=COALESCE(auth_version,0)+1"));assertTrue(xml.contains("FOR UPDATE"));});
    }
}
