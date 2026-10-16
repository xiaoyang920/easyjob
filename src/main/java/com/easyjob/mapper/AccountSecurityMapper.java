package com.easyjob.mapper;
import com.easyjob.entity.User;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
@Mapper
public interface AccountSecurityMapper {
    User lockUser(@Param("uid")Long uid);
    User findByEmail(@Param("email")String email);
    int changePassword(@Param("uid")Long uid,@Param("hash")String hash);
}
