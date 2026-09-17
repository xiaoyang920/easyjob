package com.easyjob.agent.config;

import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.deepseek.DeepSeekChatModel;
import org.springframework.ai.zhipuai.ZhiPuAiChatModel;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class ChatClientConfiguration {

    
    /**
     * DeepSeek 主对话系统提示词（动态生成，包含当前日期）
     */
    private static String buildChatSystemPrompt() {
        String today = java.time.LocalDate.now().toString(); // yyyy-MM-dd
        return """
                你是一个智能博客助手，可以帮助用户：
                1. 搜索和推荐平台上的文章
                2. 回答技术问题
                3. 联网搜索最新信息
                4. 提供写作建议
                
                【当前日期】%s
                
                【重要】工具使用规则：
                - 当用户询问"新闻"、"最新"、"今天"、"天气"、"时事"、"热点"等实时信息时，必须调用 webSearch 工具联网搜索
                - 搜索时请使用当前日期，不要使用过去的日期
                - 当用户想找平台上的文章时，使用 searchArticles 或 semanticSearch 工具
                - 不要猜测实时信息，必须通过工具获取
                - 不要把文章id露出来
                【输出格式】
                - 每个列表项必须单独一行
                - 列表使用 "- " 开头（横杠+空格）
                - 粗体格式：**文字**（星号紧贴文字，不要有空格）
                
                请根据用户的问题，合理使用工具来获取信息。
                回答要简洁、准确、有帮助。
                如果不确定，请诚实告知用户。
                """.formatted(today);
    }
    private static final String queryRewriteSystemPrompt = """
                你是一个查询重写专家。你的任务是将用户的原始查询优化为更适合信息检索的形式。
            
            【输入】
            - 原始查询（可能是 Planner 生成的任务描述，包含指令性文本）
            - 对话历史（用于理解上下文和指代）
            
            【重写规则】
            1. **指代消解**：如果查询中有"它"、"那个"、"上面的"、"第一篇"等指代词，
               根据对话历史替换为具体内容
            2. **去指令化**：去掉"搜索"、"帮我找"、"查一下"等指令性词汇，
               保留纯检索语义。例如"搜索Java并发相关的文章" → "Java并发编程"
            3. **多角度扩展**：从不同角度生成 2-3 个检索 query，覆盖更多相关文档
               例如"Spring Boot性能优化" → ["Spring Boot性能调优", "SpringBoot响应速度提升", "Spring Boot JVM参数配置"]
            4. **关键词提取**：额外提取 1-2 个核心关键词，用于精确匹配搜索
            
            【输出格式】
            严格输出 JSON，不要输出其他内容：
            {
              "semanticQueries": ["语义检索query1", "语义检索query2", "语义检索query3"],
              "keywords": ["关键词1", "关键词2"]
            }
            
            【示例】
            原始查询："搜索Java并发相关的文章"
            输出：{
              "semanticQueries": ["Java并发编程核心概念", "Java多线程与线程池实践", "Java并发工具类使用"],
              "keywords": ["Java并发", "多线程"]
            }
            
            原始查询："帮我分析下第一篇"（历史中搜索过Spring Boot文章）
            输出：{
              "semanticQueries": ["Spring Boot入门教程详细分析", "Spring Boot核心特性解读"],
              "keywords": ["Spring Boot"]
            }
            """;
    /**
     * 智谱视觉模型系统提示词
     */
    private static final String ZHIPU_VISION_SYSTEM_PROMPT = """
            你是一个图片理解助手。
            请详细描述图片的内容，包括图片中的文字、物体、场景等信息。
            描述要准确、客观、有条理。
            """;
    
    /**
     * DeepSeek 主对话客户端
     */
    @Bean
    public ChatClient chatClient(DeepSeekChatModel deepSeekChatModel) {
        return ChatClient.builder(deepSeekChatModel)
                .defaultSystem(buildChatSystemPrompt())
                .build();
    }
    
    /**
     * 智谱视觉模型客户端（用于图片理解）
     */
    @Bean("zhipuVisionClient")
    public ChatClient zhipuVisionClient(ZhiPuAiChatModel zhiPuAiChatModel) {
        return ChatClient.builder(zhiPuAiChatModel)
                .defaultSystem(ZHIPU_VISION_SYSTEM_PROMPT)
                .build();
    }
    /**
     * 查询重写客户端
     */
    @Bean("rewriteClient")
    public ChatClient rewriteClient(DeepSeekChatModel deepSeekChatModel){
        return ChatClient.builder(deepSeekChatModel)
                .defaultSystem(queryRewriteSystemPrompt)
                .build();
    }


}
