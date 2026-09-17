package com.easyjob.agent.service;

import com.easyjob.agent.component.EsVectorStore;
import com.easyjob.dto.RagResult;
import com.easyjob.entity.DocumentChunk;
import com.easyjob.mapper.ArticleMapper;
import com.easyjob.vo.ArticleDetailVO;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Service
public class RagService {
    @Autowired
    private EsVectorStore esVectorStore;
    @Autowired
    private ArticleMapper articleMapper;
    /**
     * 检索文章
     * @param question
     * @return
     */
    public List<RagResult> retrieveWithArticleInfo(String question){
        //向量检索
        List<DocumentChunk> chunks = esVectorStore.search(question, 5, 0.7f);
        if(chunks.isEmpty()){
            return List.of();
        }
        //回查mysql文章信息
        List<String> articleIds = chunks.stream().map(DocumentChunk::getArticleId).toList();
        Map<String, ArticleDetailVO> articleMap = articleMapper.selectArticlesAndUsers(articleIds).stream().collect(Collectors.toMap(
                a -> a.getArticleId().toString(),
                a -> a
        ));
        //组装结果
        return chunks.stream().map(chunk -> {
            RagResult result = new RagResult();
            result.setArticleId(chunk.getArticleId());
            result.setTitle(chunk.getTitle());
            result.setScore(chunk.getScore());
            result.setChunkContent(chunk.getContent());

            //mysql 文章信息
            ArticleDetailVO article = articleMap.get(chunk.getArticleId());
            if(article != null){
                result.setCoverImage(article.getCoverImage());
                result.setAuthorName(article.getAuthorName());
            }
            return result;
        }).toList();
    }

    /**
     * 拼接RAG上下文给ai用
     * @param question
     * @return
     */
    public String buildContext(String question){
        List<DocumentChunk> chunks = esVectorStore.search(question,5,0.7f);
        if(chunks.isEmpty()){
            return "";
        }
        StringBuilder context = new StringBuilder();
        context.append("以下是相关的参考资料：\n\n");
        for (int i = 0; i < chunks.size(); i++) {
            DocumentChunk chunk = chunks.get(i);
            context.append(String.format("【参考%d】来自《%s》:\n%s\n\n",
                    i + 1, chunk.getTitle(), chunk.getContent()));
        }
        return context.toString();
    }
}
