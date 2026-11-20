package com.easyjob.excel;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableScheduling
public class ExcelApplication {
    public static void main(String[] args) {
        SpringApplication.run(ExcelApplication.class, args);
    }
}
