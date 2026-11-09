package com.easyjob.service;
import com.easyjob.vo.ArticleListVO;
import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

class RecommendationDiversityTests {
    ArticleListVO article(String id,String author,String category,boolean readable) {
        ArticleListVO row=new ArticleListVO();row.setArticleId(id);row.setUserId(author);row.setCategoryId(category);row.setReadableNow(readable);return row;
    }
    @Test void breaksAuthorRunWithoutDroppingOrMutatingRankedPage() {
        List<ArticleListVO> ranked=List.of(article("1","a","x",true),article("2","a","x",true),article("3","a","x",true),article("4","b","y",true));
        List<ArticleListVO> result=RecommendationDiversity.reorder(ranked);
        assertEquals(List.of("1","2","4","3"),result.stream().map(ArticleListVO::getArticleId).toList());
        assertEquals("3",ranked.get(2).getArticleId());assertEquals(ranked.size(),result.size());
    }
    @Test void neverMovesLockedContentBeforeReadableContent() {
        List<ArticleListVO> ranked=List.of(article("1","a","x",true),article("2","a","x",true),article("3","a","x",true),article("4","b","y",false));
        assertEquals(ranked,RecommendationDiversity.reorder(ranked));
    }
    @Test void smallOrSingleAuthorPagesRemainComplete() {
        assertTrue(RecommendationDiversity.reorder(List.of()).isEmpty());
        List<ArticleListVO> ranked=List.of(article("1","a","x",true),article("2","a","x",true),article("3","a","x",true));
        assertEquals(ranked,RecommendationDiversity.reorder(ranked));
    }
    @Test void canDiversifyCategoriesEvenWhenOnlyOneAuthorIsAvailable() {
        List<ArticleListVO> ranked=List.of(article("1","a","x",true),article("2","a","x",true),article("3","a","x",true),article("4","a","y",true));
        assertEquals("4",RecommendationDiversity.reorder(ranked).get(2).getArticleId());
    }
}
