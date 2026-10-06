package com.easyjob.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.easyjob.entity.User;
import com.easyjob.vo.UserFollowVO;
import com.easyjob.vo.UserSearchVO;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.util.List;

// 继承BaseMapper，获得MyBatis-Plus提供的CRUD方法
@Mapper
public interface UserMapper extends BaseMapper<User> {
    long countSearchUsers(@Param("pattern") String pattern);
    List<UserSearchVO> searchUsers(@Param("keyword") String keyword, @Param("pattern") String pattern,
            @Param("viewerId") Long viewerId, @Param("offset") int offset, @Param("limit") int limit);
    void changeArticleCount(Long userId, @Param("count") int count);
    
    void changeFollowingCount(Long userId, @Param("count") int count);
    
    void changeFollowerCount(Long userId, @Param("count") int count);

    List<UserFollowVO> getUserFollowers(Long userId);

    List<UserFollowVO> getUserFollowing(Long userId);
    // 可以在这里添加自定义的方法
}
