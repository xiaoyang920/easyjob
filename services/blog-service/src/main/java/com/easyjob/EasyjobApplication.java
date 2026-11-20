package com.easyjob;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.transaction.annotation.EnableTransactionManagement;

import java.util.TimeZone;

@EnableTransactionManagement
@SpringBootApplication
@EnableScheduling
public class EasyjobApplication {

    public static void main(String[] args) {
        // 设置 JVM 默认时区为东八区
        TimeZone.setDefault(TimeZone.getTimeZone("Asia/Shanghai"));
        SpringApplication.run(EasyjobApplication.class, args);
    }

}