package com.easyjob.excel;

import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.ss.usermodel.Workbook;
import org.apache.poi.ss.usermodel.WorkbookFactory;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Path;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.IntStream;

import static org.junit.jupiter.api.Assertions.assertEquals;

class DailyWorkbookTest {
    @TempDir Path folder;

    @Test
    void appendsThreePagesToOneTemplateSheet() throws Exception {
        LocalDate from = LocalDate.of(2026, 1, 1);
        int days = 30;
        int pageSize = 11;
        List<Integer> offsets = new ArrayList<>();
        Path output = folder.resolve("daily.xlsx.part");

        int rows = DailyWorkbook.write(output, from, days, pageSize, offset -> {
            offsets.add(offset);
            return IntStream.range(offset, Math.min(offset + pageSize, days))
                    .mapToObj(index -> new DailyWorkbook.Daily(
                            from.plusDays(index), index, index * 2L, index * 1000L + 125, index * 3L))
                    .toList();
        });

        assertEquals(days, rows);
        assertEquals(List.of(0, 11, 22), offsets);
        try (Workbook workbook = WorkbookFactory.create(output.toFile())) {
            assertEquals(1, workbook.getNumberOfSheets());
            Sheet sheet = workbook.getSheetAt(0);
            assertEquals("每日统计", sheet.getSheetName());
            assertEquals(days + 1, sheet.getPhysicalNumberOfRows());
            List<String> headers = List.of("日期", "新增用户", "首次发布文章", "有效阅读秒数", "有效阅读用户数");
            for (int col = 0; col < headers.size(); col++) {
                assertEquals(headers.get(col), sheet.getRow(0).getCell(col).getStringCellValue());
            }
            for (int index = 0; index < days; index++) {
                Row row = sheet.getRow(index + 1);
                assertEquals(from.plusDays(index).toString(), row.getCell(0).getStringCellValue());
                assertEquals(index, row.getCell(1).getNumericCellValue());
                assertEquals(index * 2, row.getCell(2).getNumericCellValue());
                assertEquals(index + 0.125, row.getCell(3).getNumericCellValue());
                assertEquals(index * 3, row.getCell(4).getNumericCellValue());
            }
        }
    }
}
