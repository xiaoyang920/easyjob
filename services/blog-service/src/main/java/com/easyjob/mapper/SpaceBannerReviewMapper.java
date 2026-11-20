package com.easyjob.mapper;

import com.easyjob.vo.SpaceBannerSubmission;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.util.List;

@Mapper
public interface SpaceBannerReviewMapper {
    record StoredImage(byte[] content) {}

    SpaceBannerSubmission current(@Param("userId") Long userId);

    List<SpaceBannerSubmission> pending(@Param("offset") long offset, @Param("size") int size);

    StoredImage image(@Param("userId") Long userId, @Param("reviewId") String reviewId);

    int submit(@Param("userId") Long userId, @Param("reviewId") String reviewId, @Param("image") byte[] image);

    int position(@Param("userId") Long userId, @Param("reviewId") String reviewId, @Param("position") int position,
                 @Param("view") String view);

    int decide(@Param("userId") Long userId, @Param("reviewId") String reviewId, @Param("state") String state,
               @Param("reason") String reason, @Param("reviewerId") Long reviewerId);

    int withdraw(@Param("userId") Long userId, @Param("reviewId") String reviewId);
}
