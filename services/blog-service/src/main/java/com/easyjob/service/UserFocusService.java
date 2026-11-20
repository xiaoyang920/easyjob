package com.easyjob.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.easyjob.entity.UserFocus;
import com.easyjob.vo.PageVO;



public interface UserFocusService extends IService<UserFocus> {
    PageVO getUserFollowers(Long userId, Integer page, Integer size);

    PageVO getUserFollowing(Long userId, Integer page, Integer size);
}
