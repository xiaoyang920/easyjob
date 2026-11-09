package com.easyjob.billing;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigDecimal;
import java.net.URI;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.HexFormat;
import com.fasterxml.jackson.databind.JsonNode;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;

/** Only the official balance endpoint receives this credential. Never follows redirects. */
public class DeepseekBalanceClient {
    public record Balance(BigDecimal total, boolean available) {}
    public static class CheckFailed extends RuntimeException {
        public CheckFailed(String code) { super(code); }
    }
    private final String apiKey;
    private final HttpClient http;
    private final ObjectMapper json;

    public DeepseekBalanceClient(String apiKey, ObjectMapper json) {
        this(apiKey, json, HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5))
                .followRedirects(HttpClient.Redirect.NEVER).build());
    }
    public DeepseekBalanceClient(String apiKey, ObjectMapper json, HttpClient http) {
        if (apiKey == null || apiKey.isBlank() || apiKey.contains("\r") || apiKey.contains("\n"))
            throw new IllegalArgumentException("DeepSeek API key is required for balance monitoring");
        this.apiKey = apiKey; this.json = json; this.http = http;
    }
    public String fingerprint() {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(apiKey.getBytes(StandardCharsets.UTF_8))); }
        catch (java.security.NoSuchAlgorithmException error) { throw new IllegalStateException(error); }
    }
    public Balance fetch(String currency) {
        try {
            HttpRequest request = HttpRequest.newBuilder(URI.create("https://api.deepseek.com/user/balance"))
                    .timeout(Duration.ofSeconds(12)).header("Accept", "application/json")
                    .header("Authorization", "Bearer " + apiKey).GET().build();
            HttpResponse<String> response = http.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() != 200) throw new CheckFailed("provider_http_" + response.statusCode());
            return parse(response.body(), currency);
        } catch (CheckFailed error) { throw error; }
        catch (InterruptedException error) {
            Thread.currentThread().interrupt(); throw new CheckFailed("provider_interrupted");
        } catch (Exception error) { throw new CheckFailed("provider_unavailable"); }
    }
    public Balance parse(String body, String currency) {
        try {
            if (body == null || body.length() > 65536) throw new CheckFailed("provider_invalid_response");
            JsonNode root = json.readTree(body);
            if (root == null || !root.path("is_available").isBoolean() || !root.path("balance_infos").isArray())
                throw new CheckFailed("provider_invalid_response");
            BigDecimal amount = null;
            for (JsonNode item : root.get("balance_infos")) {
                if (!currency.equals(item.path("currency").asText())) continue;
                if (amount != null || !item.path("total_balance").isTextual()) throw new CheckFailed("provider_invalid_response");
                String text = item.get("total_balance").asText();
                if (!text.matches("-?\\d{1,12}(?:\\.\\d{1,8})?")) throw new CheckFailed("provider_invalid_response");
                amount = new BigDecimal(text);
            }
            if (amount == null) throw new CheckFailed("provider_currency_missing");
            return new Balance(amount, root.get("is_available").booleanValue());
        } catch (CheckFailed error) { throw error; }
        catch (Exception error) { throw new CheckFailed("provider_invalid_response"); }
    }
}
