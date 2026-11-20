package com.easyjob.controller;
import com.easyjob.service.AdminCategoryService;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ResponseVO;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

@RestController @RequestMapping("/api/admin/categories") @RequiredArgsConstructor
public class AdminCategoryController {
    private final AdminCategoryService service;
    private final com.easyjob.service.AdminCategoryManagementService management;
    @GetMapping public ResponseVO<?> list(){return ResponseVO.success(service.list(UserContext.getUserId()));}
    @PostMapping public ResponseVO<?> create(@RequestBody AdminCategoryService.Create body){return ResponseVO.success("分类已创建",service.create(UserContext.getUserId(),body));}
    @PutMapping("/{id}") public ResponseVO<?> update(@PathVariable long id,@RequestBody com.easyjob.service.AdminCategoryManagementService.Update body){management.update(UserContext.getUserId(),id,body);return ResponseVO.success("分类已更新");}
    @PostMapping("/{id}/migrate") public ResponseVO<?> migrate(@PathVariable long id,@RequestBody com.easyjob.service.AdminCategoryManagementService.Move body){return ResponseVO.success("分类文章已迁移",management.move(UserContext.getUserId(),id,body));}
}
