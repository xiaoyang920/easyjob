package com.easyjob.service;

import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.UserMapper;
import com.easyjob.vo.PageVO;
import com.easyjob.vo.UserSearchVO;
import org.springframework.stereotype.Service;
import java.util.List;

@Service
public class UserSearchService {
    private final UserMapper users;
    public UserSearchService(UserMapper users) { this.users = users; }

    public PageVO<UserSearchVO> search(String keyword, int pageNo, int pageSize, Long viewerId) {
        if (keyword == null || keyword.isBlank() || keyword.trim().length() > 200
                || pageNo < 1 || pageNo > 10000 || pageSize < 1 || pageSize > 50) {
            throw new BusinessException(400, "搜索词或分页参数无效");
        }
        String term = keyword.trim();
        // Treat SQL wildcard characters as literal user input.
        String pattern = "%" + term.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%";
        long total = users.countSearchUsers(pattern);
        List<UserSearchVO> records = total == 0 ? List.of()
                : users.searchUsers(term, pattern, viewerId, (pageNo - 1) * pageSize, pageSize);
        return new PageVO<>(records, total, (long) pageSize, (long) pageNo, (total + pageSize - 1) / pageSize);
    }
}
