package com.easyjob.excel;

import java.time.LocalDate;

public record ExcelJob(String jobNo, long ownerId, int days, String source, LocalDate fromDay,
                       LocalDate toDay, String status, int attempts, Integer rowCount,
                       String fileName, String lastError) {
    public record View(String jobNo, String status, int attempts, Integer rowCount, String error,
                       LocalDate from, LocalDate to, String source) {}

    View view() {
        return new View(jobNo, status, attempts, rowCount, lastError, fromDay, toDay, source);
    }
}
