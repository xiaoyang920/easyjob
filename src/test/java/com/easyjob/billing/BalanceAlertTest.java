package com.easyjob.billing;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.mail.javamail.JavaMailSenderImpl;
import org.mockito.ArgumentCaptor;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.net.http.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import com.easyjob.billing.DeepseekBalanceClient.Balance;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;

class BalanceAlertTest {
    private final DeepseekBalanceClient client = new DeepseekBalanceClient("test-key",new ObjectMapper());
    @Test void thresholdIsStrictAndDecimal() {
        BalanceAlertPolicy policy=new BalanceAlertPolicy("test","CNY",new BigDecimal("2.00"),"qa@example.invalid",600);
        assertFalse(policy.low(new BigDecimal("2")));
        assertTrue(policy.low(new BigDecimal("1.99999999")));
        assertFalse(policy.low(new BigDecimal("4.79")));
        assertThrows(IllegalArgumentException.class,()->new BalanceAlertPolicy("test","CNY",BigDecimal.TWO,"a@a.com,b@b.com",600));
    }
    @Test void readsOnlyRequestedCurrencyWithoutGuessingZero() {
        Balance balance=client.parse("{\"is_available\":true,\"balance_infos\":[{\"currency\":\"USD\",\"total_balance\":\"9.5\"},{\"currency\":\"CNY\",\"total_balance\":\"1.999\"}]}","CNY");
        assertEquals(new BigDecimal("1.999"),balance.total());
        for(String body:new String[]{"{}","not json","{\"is_available\":true,\"balance_infos\":[]}",
                "{\"is_available\":true,\"balance_infos\":[{\"currency\":\"CNY\",\"total_balance\":\"NaN\"}]}",
                "{\"is_available\":true,\"balance_infos\":[{\"currency\":\"CNY\",\"total_balance\":\"1\"},{\"currency\":\"CNY\",\"total_balance\":\"1\"}]}"})
            assertThrows(DeepseekBalanceClient.CheckFailed.class,()->client.parse(body,"CNY"));
    }
    @Test @SuppressWarnings("unchecked") void authFailureIsSanitizedAndEndpointIsFixed() throws Exception {
        HttpClient http=mock(HttpClient.class); HttpResponse<String> response=mock(HttpResponse.class);
        when(response.statusCode()).thenReturn(401);
        when(http.send(any(HttpRequest.class),any(HttpResponse.BodyHandler.class))).thenReturn(response);
        DeepseekBalanceClient api=new DeepseekBalanceClient("test-secret",new ObjectMapper(),http);
        assertEquals("provider_http_401",assertThrows(DeepseekBalanceClient.CheckFailed.class,()->api.fetch("CNY")).getMessage());
        ArgumentCaptor<HttpRequest> request=ArgumentCaptor.forClass(HttpRequest.class);
        verify(http).send(request.capture(),any(HttpResponse.BodyHandler.class));
        assertEquals("https://api.deepseek.com/user/balance",request.getValue().uri().toString());
        assertTrue(request.getValue().timeout().isPresent());
    }
    @Test void emailUsesExactBalanceAndConfiguredRecipient() {
        JavaMailSender sender=mock(JavaMailSender.class);
        new DeepseekBalanceMail(sender,"sender@example.invalid").send(new ProviderBalanceStore.Notice("id","qa@example.invalid","CNY",new BigDecimal("2.00"),new BigDecimal("1.999"),LocalDateTime.of(2026,10,26,0,0)));
        ArgumentCaptor<SimpleMailMessage> message=ArgumentCaptor.forClass(SimpleMailMessage.class); verify(sender).send(message.capture());
        assertArrayEquals(new String[]{"qa@example.invalid"},message.getValue().getTo());
        assertTrue(message.getValue().getText().contains("1.999 元人民币"));
        assertTrue(message.getValue().getText().contains("2026-10-26 08:00:00"));
    }
    @Test void monitorMailTimeoutsDoNotChangeExistingSender() {
        JavaMailSenderImpl original=new JavaMailSenderImpl(); original.setHost("smtp.qq.com"); original.getJavaMailProperties().setProperty("mail.smtp.starttls.enable","true");
        JavaMailSenderImpl bounded=(JavaMailSenderImpl)DeepseekBalanceMail.boundedSender(original);
        assertEquals("10000",bounded.getJavaMailProperties().getProperty("mail.smtp.timeout"));
        assertEquals("true",bounded.getJavaMailProperties().getProperty("mail.smtp.starttls.required"));
        assertNull(original.getJavaMailProperties().getProperty("mail.smtp.timeout"));
    }
}
