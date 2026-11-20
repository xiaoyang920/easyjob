package com.easyjob.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.easyjob.entity.UserFocus;
import com.easyjob.vo.UserFollowVO;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

/**
 * 用户关注Mapper接口
 */
@Mapper
public interface UserFocusMapper extends BaseMapper<UserFocus> {
    
    /**
     * 获取用户的粉丝列表
     * @param userId 用户ID
     * @param currentUserId 当前登录用户ID
     * @param page 分页参数
     * @return 粉丝列表
     */
    IPage<UserFollowVO> getUserFollowers(@Param("userId") Long userId, 
                                         @Param("currentUserId") Long currentUserId,
                                         Page<UserFollowVO> page);
    
    /**
     * 获取用户的关注列表
     * @param userId 用户ID
     * @param currentUserId 当前登录用户ID
     * @param page 分页参数
     * @return 关注列表
     */
    IPage<UserFollowVO> getUserFollowing(@Param("userId") Long userId,
                                         @Param("currentUserId") Long currentUserId,
                                         Page<UserFollowVO> page);
}
