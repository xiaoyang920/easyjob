package com.easyjob.billing;

import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.mail.javamail.JavaMailSenderImpl;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.Properties;

public class DeepseekBalanceMail {
    private final JavaMailSender sender;
    private final String from;
    public DeepseekBalanceMail(JavaMailSender sender, String from) { this.sender = sender; this.from = from; }

    /** Copy the existing SMTP account with bounded I/O; do not alter verification-email settings. */
    public static JavaMailSender boundedSender(JavaMailSender existing) {
        if (!(existing instanceof JavaMailSenderImpl source)) throw new IllegalArgumentException("SMTP mail sender required");
        JavaMailSenderImpl result = new JavaMailSenderImpl();
        result.setHost(source.getHost()); result.setPort(source.getPort()); result.setProtocol(source.getProtocol());
        result.setUsername(source.getUsername()); result.setPassword(source.getPassword()); result.setDefaultEncoding("UTF-8");
        Properties properties = new Properties(); properties.putAll(source.getJavaMailProperties());
        for (String protocol : new String[]{"smtp", "smtps"}) {
            for (String timeout : new String[]{"connectiontimeout", "timeout", "writetimeout"}) properties.setProperty("mail." + protocol + "." + timeout, "10000");
            properties.setProperty("mail." + protocol + ".ssl.checkserveridentity", "true");
        }
        if (Boolean.parseBoolean(properties.getProperty("mail.smtp.starttls.enable"))) properties.setProperty("mail.smtp.starttls.required", "true");
        result.setJavaMailProperties(properties);
        return result;
    }
    public void send(ProviderBalanceStore.Notice notice) {
        String unit = notice.currency().equals("CNY") ? "元人民币" : "美元";
        String threshold = notice.threshold().stripTrailingZeros().toPlainString();
        String amount = notice.balance().stripTrailingZeros().toPlainString();
        String checked = notice.checkedAt().atOffset(ZoneOffset.UTC).atZoneSameInstant(ZoneId.of("Asia/Shanghai"))
                .format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"));
        SimpleMailMessage message = new SimpleMailMessage();
        message.setFrom(from); message.setTo(notice.recipient());
        message.setSubject("【EasyJob】DeepSeek 余额低于 " + threshold + " " + unit);
        message.setText("DeepSeek API 账户余额提醒\n\n当前可用余额：" + amount + " " + unit
                + "\n预警阈值：低于 " + threshold + " " + unit + "\n检查时间：" + checked + "（北京时间）"
                + "\n\n可用余额包含未过期赠金和充值余额。请登录 DeepSeek 官方平台检查并按需充值："
                + "\nhttps://platform.deepseek.com/"
                + "\n\n本轮低余额提醒只发送一次，余额恢复至阈值及以上后重新启用。"
                + "\n提醒编号：" + notice.id());
        sender.send(message);
    }
}
