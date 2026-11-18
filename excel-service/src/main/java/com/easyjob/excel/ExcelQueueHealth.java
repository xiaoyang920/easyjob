package com.easyjob.excel;

import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.stereotype.Component;

@Component
class ExcelQueueHealth implements HealthIndicator {
    private final ExcelJobMapper jobs;

    ExcelQueueHealth(ExcelJobMapper jobs) {
        this.jobs = jobs;
    }

    @Override
    public Health health() {
        try {
            jobs.probeQueue();
            return Health.up().build();
        } catch (RuntimeException failure) {
            return Health.down().withDetail("reason", "Excel task table unavailable").build();
        }
    }
}
