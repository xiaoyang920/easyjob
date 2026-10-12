package com.easyjob.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import java.util.List;
import java.util.Map;
import com.easyjob.entity.ArticleRevisionInsert;
import com.easyjob.entity.PublishedArticleProjection;

/** Persistence statements only; authorization and transactions belong to the service. */
@Mapper
public interface ArticleRevisionMapper {
    int reviewRevision(@Param("state") int state, @Param("reason") String reason, @Param("reviewerId") Long reviewerId, @Param("revisionId") Long revisionId);
    int publishRevision(@Param("revisionId") Long revisionId, @Param("articleId") Long articleId);
    List<Map<String,Object>> findReviewLogs(@Param("articleId") Long articleId);
    List<Map<String,Object>> findHistory(@Param("articleId") Long articleId);
    int deletePublishedArticle(@Param("articleId") Long articleId);
    int deleteRevisions(@Param("articleId") Long articleId);
    int restorePublishedHead(@Param("articleId") Long articleId);
    int setCurrentRevision(@Param("revisionId") Long revisionId);
    int clearCurrentRevision(@Param("articleId") Long articleId);
    int supersedeRevision(@Param("revisionId") Long revisionId);
    int withdrawRevision(@Param("revisionId") Long revisionId);
    int submitWorkingRevision(@Param("payload") String payload, @Param("contentHash") String contentHash, @Param("revisionId") Long revisionId);
    int updatePublishedProjection(@Param("projection") PublishedArticleProjection projection);
    int insertPublishedProjection(@Param("projection") PublishedArticleProjection projection);
    int saveWorkingRevision(@Param("payload") String payload, @Param("contentHash") String contentHash, @Param("state") int state, @Param("submitting") int submitting, @Param("revisionId") Long revisionId);
    int insertReviewLog(@Param("articleId") Long articleId, @Param("actorId") Long actorId, @Param("action") String action, @Param("reason") String reason, @Param("revisionId") Long revisionId);
    int updatePublishedRevision(@Param("revisionId") Long revisionId, @Param("articleId") Long articleId);
    List<Map<String,Object>> findExistingIdentity(@Param("articleId") Long articleId);
    int updateLatestRevision(@Param("revisionId") Long revisionId, @Param("articleId") Long articleId);
    Integer nextVersion(@Param("articleId") Long articleId);
    List<Map<String,Object>> findCategoryName(@Param("categoryId") Long categoryId);
    List<Map<String,Object>> lockParentCategory(@Param("categoryId") Long categoryId);
    List<Map<String,Object>> lockCategory(@Param("categoryId") Long categoryId);
    List<Map<String,Object>> findRevisionArticle(@Param("revisionId") Long revisionId);
    List<Map<String,Object>> lockRevision(@Param("revisionId") Long revisionId);
    List<Map<String,Object>> lockCurrentRevision(@Param("articleId") Long articleId);
    List<Map<String,Object>> lockPublishedArticle(@Param("articleId") Long articleId);
    List<Map<String,Object>> findOwners(@Param("articleId") Long articleId);
    List<Map<String,Object>> lockOwner(@Param("userId") Long userId);
    int insertRevision(@Param("row") ArticleRevisionInsert row);
    List<Map<String,Object>> lockCategoryRedirect(@Param("categoryId") Long categoryId);
    List<Map<String,Object>> findOwnDrafts(@Param("userId") Long userId, @Param("pattern") String pattern);
    Long countWorkspace(@Param("userId") Long userId, @Param("state") Integer state);
    List<Map<String,Object>> findWorkspace(@Param("userId") Long userId, @Param("state") Integer state, @Param("size") int size, @Param("offset") int offset);
    Long countReviewQueue(@Param("state") Integer state);
    List<Map<String,Object>> findReviewQueue(@Param("state") Integer state, @Param("size") int size, @Param("offset") int offset);
}
