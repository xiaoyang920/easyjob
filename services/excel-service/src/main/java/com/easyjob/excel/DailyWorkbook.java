package com.easyjob.excel;

import com.alibaba.excel.EasyExcel;
import com.alibaba.excel.ExcelWriter;
import com.alibaba.excel.support.ExcelTypeEnum;
import com.alibaba.excel.write.metadata.WriteSheet;
import com.alibaba.excel.write.metadata.fill.FillWrapper;
import org.springframework.core.io.ClassPathResource;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import java.util.function.IntFunction;

final class DailyWorkbook {
    private DailyWorkbook() {}

    record Daily(LocalDate date, long newUsers, long newArticles, long readingMillis, long readingUsers) {
        Map<String, Object> cells() {
            return Map.of("date", date.toString(), "newUsers", newUsers, "newArticles", newArticles,
                    "readingSeconds", readingMillis / 1000.0, "readingUsers", readingUsers);
        }
    }

    static int write(Path output, LocalDate from, int days, int pageSize,
                     IntFunction<List<Daily>> loadPage) throws IOException {
        int rows = 0;
        try (InputStream template = new ClassPathResource("templates/community-daily.xlsx").getInputStream();
             OutputStream stream = Files.newOutputStream(output);
             ExcelWriter writer = EasyExcel.write(stream).autoCloseStream(false).excelType(ExcelTypeEnum.XLSX)
                     .withTemplate(template).build()) {
            WriteSheet sheet = EasyExcel.writerSheet(0).build();
            while (rows < days) {
                List<Daily> page = loadPage.apply(rows);
                if (page == null || page.size() != Math.min(pageSize, days - rows)) {
                    throw new IllegalStateException("Unexpected number of statistics rows");
                }
                for (Daily day : page) {
                    if (!from.plusDays(rows).equals(day.date())) {
                        throw new IllegalStateException("Statistics dates are out of order");
                    }
                    rows++;
                }
                writer.fill(new FillWrapper("daily", page.stream().map(Daily::cells).toList()), sheet);
            }
        }
        return rows;
    }
}
