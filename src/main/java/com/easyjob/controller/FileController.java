package com.easyjob.controller;

import com.easyjob.exception.BusinessException;
import com.easyjob.service.FileStorageService;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ResponseVO;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import java.util.Map;

@RestController
@RequestMapping("/api/file")
@RequiredArgsConstructor
public class FileController {
    private final FileStorageService files;
    private Long owner() {
        Long uid = UserContext.getUserId();
        if (uid == null) throw new BusinessException(401, "请先登录");
        return uid;
    }
    private ResponseVO<Map<String,String>> upload(MultipartFile file, String category) {
        return ResponseVO.success("上传成功", files.upload(file, category, owner()));
    }
    @PostMapping("/upload-message")
    public ResponseVO<?> uploadMessage(@RequestParam("file") MultipartFile file) { return upload(file, "messages"); }
    @PostMapping("/upload-ai-chat")
    public ResponseVO<?> uploadAiChat(@RequestParam("file") MultipartFile file) { return upload(file, "ai-chat"); }
    @PostMapping("/upload-avatar")
    public ResponseVO<?> uploadAvatar(@RequestParam("file") MultipartFile file) { return upload(file, "avatars"); }
    @PostMapping("/upload-cover")
    public ResponseVO<?> uploadCover(@RequestParam("file") MultipartFile file) { return upload(file, "covers"); }
    @PostMapping("/upload-article-image")
    public ResponseVO<?> uploadArticleImage(@RequestParam("file") MultipartFile file) { return upload(file, "articles"); }
    @PostMapping("/upload-comment-image")
    public ResponseVO<?> uploadCommentImage(@RequestParam("file") MultipartFile file) { return upload(file, "comments"); }
    @DeleteMapping("/delete")
    public ResponseVO<?> deleteFile(@RequestParam("fileUrl") String url) {
        files.delete(url, owner());
        return ResponseVO.success("删除成功", null);
    }
}
