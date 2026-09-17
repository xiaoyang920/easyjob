package com.easyjob.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.easyjob.dto.UserUpdateDTO;
import com.easyjob.entity.User;
import com.easyjob.vo.UserFollowVO;
import org.springframework.stereotype.Service;

import java.util.List;

public interface UserService extends IService<User> {
    void updateUserSpaceInfo(UserUpdateDTO userUpdateDTO);



    void follow(Long userId);

    void unfollow(Long userId);
    
    boolean checkFollowStatus(Long userId);

    User getUserByEmail(String email);
}