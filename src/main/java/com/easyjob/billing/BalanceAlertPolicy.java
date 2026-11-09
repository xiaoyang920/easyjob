package com.easyjob.billing;

import jakarta.mail.internet.InternetAddress;
import java.math.BigDecimal;
import java.util.Set;

public record BalanceAlertPolicy(String monitorId, String currency, BigDecimal threshold,
                                 String recipient, int intervalSeconds) {
    public BalanceAlertPolicy {
        if (monitorId == null || !monitorId.matches("[a-zA-Z0-9_-]{1,48}"))
            throw new IllegalArgumentException("Invalid balance monitor id");
        if (currency == null || !Set.of("CNY", "USD").contains(currency) || threshold == null || threshold.signum() <= 0
                || threshold.scale() > 8 || threshold.precision() - threshold.scale() > 12)
            throw new IllegalArgumentException("Invalid balance currency or threshold");
        try {
            if (recipient == null || recipient.length() > 254 || recipient.contains("\r") || recipient.contains("\n"))
                throw new IllegalArgumentException("Invalid balance notification recipient");
            InternetAddress[] addresses = InternetAddress.parse(recipient, true);
            if (addresses.length != 1 || addresses[0].getPersonal() != null || !recipient.equals(addresses[0].getAddress()))
                throw new IllegalArgumentException("One mailbox is required");
            addresses[0].validate();
        } catch (jakarta.mail.internet.AddressException error) {
            throw new IllegalArgumentException("Invalid balance notification recipient");
        }
        if (intervalSeconds < 60 || intervalSeconds > 86400)
            throw new IllegalArgumentException("Balance interval must be between 60 and 86400 seconds");
    }

    public String key() { return monitorId + ":" + currency; }
    public boolean low(BigDecimal balance) { return balance.compareTo(threshold) < 0; }
}
