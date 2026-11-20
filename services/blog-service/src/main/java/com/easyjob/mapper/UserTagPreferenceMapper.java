package com.easyjob.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.easyjob.entity.UserTagPreference;
import org.apache.ibatis.annotations.Param;

import java.util.List;

public interface UserTagPreferenceMapper extends BaseMapper<UserTagPreference> {

    void refreshAllPreferences();

    List<Long> selectTopTagIds(@Param("userId") Long userId,@Param("limit") Integer limit);
}
