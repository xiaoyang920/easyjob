package com.easyjob.utils;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.ResponseCookie;
import org.springframework.stereotype.Component;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.UUID;

@Component
public class ArticleReaderIdentity {
    public String resolve(HttpServletRequest request, HttpServletResponse response, Long userId) {
        String visitor = null;
        if (request.getCookies() != null) for (var cookie : request.getCookies()) {
            if ("ej_reader".equals(cookie.getName()) && cookie.getValue().matches("[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}")) visitor = cookie.getValue();
        }
        if (visitor == null) {
            visitor = UUID.randomUUID().toString();
            response.addHeader("Set-Cookie", ResponseCookie.from("ej_reader", visitor).httpOnly(true)
                    .secure(request.isSecure()).sameSite("Lax").path("/").maxAge(31536000).build().toString());
        }
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(
                    (userId == null ? "visitor:" + visitor : "user:" + userId).getBytes(StandardCharsets.UTF_8)));
        } catch (java.security.NoSuchAlgorithmException impossible) { throw new IllegalStateException(impossible); }
    }
}
