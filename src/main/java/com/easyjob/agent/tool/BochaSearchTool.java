package com.easyjob.agent.tool;


import com.alibaba.fastjson2.JSONArray;
import com.alibaba.fastjson2.JSONObject;
import lombok.extern.slf4j.Slf4j;
import okhttp3.*;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.util.concurrent.TimeUnit;

@Slf4j
@Component
public class BochaSearchTool {
    @Value("${agent.bocha.api-key:}")
    private String apiKey;

    @Value("${agent.bocha.base-url:https://api.bocha.cn/v1/web-search}")
    private String baseUrl;

    @Value("${agent.bocha.max-results:10}")
    private int maxResults;

    @Value("${agent.bocha.enabled:true}")
    private boolean enabled;

    private final OkHttpClient httpClient = new OkHttpClient().newBuilder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .build();
    @Tool(description = "联网搜索工具，用于获取实时信息。当用户询问新闻、天气、热点、最新动态、今日事件等需要实时数据的问题时，必须调用此工具。")
    public String webSearch(
            @ToolParam(description = "搜索关键词") String query,
            @ToolParam(description = "时效性: day/week/month/year，默认不限", required = false) String freshness
    ){
        if(!enabled){
            return "联网搜索功能未启用。";
        }
        if(query == null || query.isEmpty()){
            return "请输入搜索关键词。";
        }
        log.info("开始搜索: {}", query);
        try{
            //组装json请求体
            JSONObject requestBody = new JSONObject();
            requestBody.put("query", query);
            requestBody.put("count", maxResults);
            if(freshness != null&& !freshness.isEmpty()){
                requestBody.put("freshness", freshness);
            }
            //组装请求 url header body
            Request request = new Request.Builder()
                    .url(baseUrl)
                    .addHeader("Authorization", "Bearer " + apiKey)
                    .addHeader("Content-Type", "application/json")
                    .post(RequestBody.create(
                            requestBody.toJSONString(),
                            MediaType.parse("application/json")
                    ))
                    .build();
            //发送请求
            try(Response response = httpClient.newCall(request).execute()){
                if(!response.isSuccessful()){
                    log.error("博查搜索请求失败: {}", response.code());
                    return "联网搜索请求失败，请稍后重试。";
                }
                String responseBody = response.body().string();
                return parseSearchResult(responseBody);
            }
        }catch (Exception e){
            log.error("博查搜索异常", e);
            return "联网搜索时出现错误，请稍后重试。";
        }
    }
    private String parseSearchResult(String responseBody){
        try{
            JSONObject json = JSONObject.parseObject(responseBody);
            Integer code = json.getInteger("code");

            if (code == null || code != 200) {
                String msg = json.getString("message");
                return "搜索失败: " + (msg != null ? msg : "未知错误");
            }

            JSONObject data = json.getJSONObject("data");
            if (data == null) {
                return "未找到相关结果。";
            }
            JSONObject webPages = data.getJSONObject("webPages");
            if (webPages == null) {
                return "未找到相关结果。";
            }

            JSONArray results = webPages.getJSONArray("value");
            if (results == null || results.isEmpty()) {
                return "未找到相关结果。";
            }
            StringBuilder sb = new StringBuilder();
            sb.append("联网搜索结果：\n\n");
            for (int i = 0; i < results.size() && i < maxResults; i++) {
                JSONObject item = results.getJSONObject(i);
                String title = item.getString("name");
                String url = item.getString("url");
                String snippet = item.getString("snippet");
                String date = item.getString("datePublished");

                sb.append(String.format("【%d】%s\n", i + 1, title));
                if (date != null && !date.isEmpty()) {
                    sb.append("发布时间: ").append(date.substring(0, 10)).append("\n");
                }
                sb.append("摘要: ").append(snippet != null ? snippet : "无").append("\n");
                sb.append("链接: ").append(url).append("\n\n");
            }

            return sb.toString();
        }catch (Exception e) {
            log.error("解析搜索结果失败", e);
            return "解析搜索结果时出现错误。";
        }
    }
}
