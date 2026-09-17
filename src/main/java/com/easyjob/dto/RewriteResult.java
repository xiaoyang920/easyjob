package com.easyjob.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class RewriteResult {
    private List<String> semanticQueries;   // 语义检索用的 query 列表
    private List<String> keywords;          // 关键词搜索用的关键词列表
    public static RewriteResult fallback(String originalQuery) {
        return new RewriteResult(List.of(originalQuery), List.of());
    }
}
