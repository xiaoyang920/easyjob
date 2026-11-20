package com.easyjob.service.impl;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.easyjob.entity.UserFocus;
import com.easyjob.mapper.UserFocusMapper;
import com.easyjob.service.UserFocusService;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.PageVO;
import com.easyjob.vo.UserFollowVO;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.List;
@Service
public class UserFocusServiceImpl extends ServiceImpl<UserFocusMapper, UserFocus> implements UserFocusService {
    @Autowired
    private UserFocusMapper userFocusMapper;

    @Override
    public PageVO getUserFollowers(Long userId, Integer page, Integer size) {
       Page<UserFollowVO> userFocusPage = new Page<>(page,size);
        IPage<UserFollowVO> userFollowers = userFocusMapper.getUserFollowers(userId, UserContext.getUserId(), userFocusPage);
        List<UserFollowVO> records = userFollowers.getRecords();
        records.stream().map(record->{
            record.setUserId(String.valueOf(record.getUserId()));
            return records;
        });
        PageVO pageVO=new PageVO<>(records,userFollowers.getTotal(),userFollowers.getSize(),userFollowers.getCurrent(),userFollowers.getPages());
        return pageVO;
    }

    @Override
    public PageVO getUserFollowing(Long userId, Integer page, Integer size) {
        Page<UserFollowVO>  userFollowVOPage= new Page<>(page,size);
        IPage<UserFollowVO> userFollowing = userFocusMapper.getUserFollowing(userId, UserContext.getUserId(), userFollowVOPage);
        List<UserFollowVO> records = userFollowing.getRecords();
        records.stream().map(record->{
            record.setUserId(String.valueOf(record.getUserId()));
            record.setIsFollowing(true);
            return records;
        });
        PageVO pageVO=new PageVO<>(records,userFollowing.getTotal(),userFollowing.getSize(),userFollowing.getCurrent(),userFollowing.getPages());
        return pageVO;
    }
}
