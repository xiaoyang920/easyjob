package com.easyjob.controller;

import com.easyjob.exception.BusinessException;
import com.easyjob.vo.ResponseVO;
import lombok.extern.slf4j.Slf4j;
import net.coobird.thumbnailator.Thumbnails;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.*;

/**
 * 文件上传控制器
 * 处理所有文件相关的操作（图片、文档等）
 */
@Slf4j
@RestController
@RequestMapping("/api/file")
public class FileController {

    /**
     * 文件上传根目录（从配置文件读取）
     */
    @Value("${file.upload.path:./uploads}")
    private String uploadPath;

    /**
     * 文件访问URL前缀（从配置文件读取）
     */
    @Value("${file.access.url:/uploads}")
    private String accessUrl;
    /** AI图片最大边长 */
    private static final int AI_IMAGE_MAX_DIMENSION = 1920;
    /** AI图片免压缩阈值（2MB） */
    private static final long AI_IMAGE_MAX_BYTES = 2 * 1024 * 1024;
    /**
     * 允许的图片格式
     */
    private static final String[] ALLOWED_IMAGE_TYPES = {"jpg", "jpeg", "png", "gif", "webp"};

    /**
     * 最大文件大小（15MB）
     */
    private static final long MAX_FILE_SIZE = 15 * 1024 * 1024;
    @Value("${file.thumbnail.width}")
    private int thumbnailWidth;

    @Value("${file.thumbnail.quality}")
    private float thumbnailQuality;

    @Value("#{'${file.thumbnail.categories}'.split(',')}")
    private Set<String> thumbnailCategories;

    /**
     * 通用图片上传方法
     * 
     * @param file 图片文件
     * @param category 文件分类（avatars/covers/articles等）
     * @return 文件访问URL
     */
    private ResponseVO<?> uploadImage(MultipartFile file, String category) {
        log.info("开始上传{}，文件名: {}, 大小: {} bytes", category, file.getOriginalFilename(), file.getSize());
        
        // 验证文件
        validateImageFile(file);
        
        // 保存文件
        Map<String, String> urls = saveFile(file, category);
        
        // 返回文件URL
        Map<String, String> data = new HashMap<>();
        data.put("url", urls.get("url"));
        data.put("fileName", file.getOriginalFilename());
        if (urls.containsKey("thumbUrl")) {
            data.put("thumbUrl", urls.get("thumbUrl"));
        }

        log.info("{}上传成功: {}", category, urls.get("url"));
        return ResponseVO.success("上传成功", data);
    }
    /**
     * 上传消息图片
     *
     * @param file 图片文件
     * @return 文件访问URL
     */
    @PostMapping("/upload-message")
    public ResponseVO<?> uploadMessage(@RequestParam("file") MultipartFile file) {
        return uploadImage(file, "messages");
    }

    /**
     * 上传AI聊天图片（按用户ID分文件夹）
     *
     * @param file 图片文件
     * @return 文件访问URL和相对路径
     */
    @PostMapping("/upload-ai-chat")
    public ResponseVO<?> uploadAiChat(@RequestParam("file") MultipartFile file) {
        Long userId = com.easyjob.utils.UserContext.getUserId();
        if (userId == null) {
            throw new BusinessException("请先登录");
        }

        log.info("上传AI聊天图片，用户ID: {}, 文件名: {}, 大小: {}KB",
                userId, file.getOriginalFilename(), file.getSize() / 1024);
        
        // 验证文件
        validateImageFile(file);
        
        try{
            //构建统一路径
            String datePath = LocalDate.now().format(DateTimeFormatter.ofPattern("yyyy/MM/dd"));
            String fileName = UUID.randomUUID().toString().replace("-", "")+".jpg";
            String relativePath = "ai-chat/"+userId+"/"+datePath+"/"+fileName;
            Path outputPath = Paths.get(uploadPath, relativePath);
            Files.createDirectories(outputPath.getParent());
            if(needsCompression(file)){
                BufferedImage originalImage = ImageIO.read(file.getInputStream());
                if(originalImage==null){
                    throw new BusinessException("无法解析图片文件");
                }
                int w = originalImage.getWidth();
                int h = originalImage.getHeight();
                int targetW = Math.min(w, AI_IMAGE_MAX_DIMENSION);
                int targetH = Math.min(h, AI_IMAGE_MAX_DIMENSION);
                Thumbnails.of(originalImage)
                        .size(targetW, targetH)
                        .outputQuality(thumbnailQuality)
                        .outputFormat("jpeg")
                        .toFile(outputPath.toFile());
                log.info("AI图片压缩保存: {}x{} → {}KB", w, h, Files.size(outputPath) / 1024);
            } else {
                // 无需压缩：直接保存原文件
                file.transferTo(outputPath.toFile());
                log.info("AI图片直接保存: {}KB", file.getSize() / 1024);
            }
            Map<String, String> data = new HashMap<>();
            data.put("url", accessUrl + "/" + relativePath);
            data.put("path", relativePath);

            return ResponseVO.success("上传成功", data);
        }catch (BusinessException e){
            throw e;
        }catch (IOException e){
            log.error("AI聊天图片保存失败", e);
            throw new BusinessException("图片上传失败，请稍后重试");
        }
    }

    /**
     * 上传头像
     * 
     * @param file 图片文件
     * @return 文件访问URL
     */
    @PostMapping("/upload-avatar")
    public ResponseVO<?> uploadAvatar(@RequestParam("file") MultipartFile file) {
        return uploadImage(file, "avatars");
    }

    /**
     * 上传文章封面
     * 
     * @param file 图片文件
     * @return 文件访问URL
     */
    @PostMapping("/upload-cover")
    public ResponseVO<?> uploadCover(@RequestParam("file") MultipartFile file) {
        return uploadImage(file, "covers");
    }

    /**
     * 上传文章图片（富文本编辑器）
     * 
     * @param file 图片文件
     * @return 文件访问URL
     */
    @PostMapping("/upload-article-image")
    public ResponseVO<?> uploadArticleImage(@RequestParam("file") MultipartFile file) {
        return uploadImage(file, "articles");
    }

    /**
     * 上传评论图片
     * 
     * @param file 图片文件
     * @return 文件访问URL
     */
    @PostMapping("/upload-comment-image")
    public ResponseVO<?> uploadCommentImage(@RequestParam("file") MultipartFile file) {
        return uploadImage(file, "comments");
    }

    /**
     * 验证图片文件
     * 
     * @param file 文件
     */
    private void validateImageFile(MultipartFile file) {
        // 检查文件是否为空
        if (file == null || file.isEmpty()) {
            throw new BusinessException("请选择要上传的文件");
        }

        // 检查文件大小
        if (file.getSize() > MAX_FILE_SIZE) {
            throw new BusinessException("文件大小不能超过15MB");
        }

        // 获取文件扩展名
        String originalFilename = file.getOriginalFilename();
        if (originalFilename == null || !originalFilename.contains(".")) {
            throw new BusinessException("文件格式不正确");
        }

        String extension = originalFilename.substring(originalFilename.lastIndexOf(".") + 1).toLowerCase();

        // 检查文件类型
        boolean isAllowed = Arrays.asList(ALLOWED_IMAGE_TYPES).contains(extension);
        if (!isAllowed) {
            throw new BusinessException("只支持上传 jpg、jpeg、png、gif、webp 格式的图片");
        }

        // 检查MIME类型
        String contentType = file.getContentType();
        if (contentType == null || !contentType.startsWith("image/")) {
            throw new BusinessException("文件类型不正确，请上传图片文件");
        }
    }

    /**
     * 保存文件到本地
     * 
     * @param file 文件
     * @param category 文件分类（avatars/covers/articles等）
     * @return 文件访问URL
     */
    private  Map<String, String>saveFile(MultipartFile file, String category) {
        try {
            // 获取原始文件名和扩展名
            String originalFilename = file.getOriginalFilename();
            String extension = originalFilename.substring(originalFilename.lastIndexOf("."));

            // 生成唯一文件名 (UUID)
            String fileName = UUID.randomUUID().toString().replace("-", "") + extension;

            // 按日期分目录存储：uploads/avatars/2024/12/08/
            String datePath = LocalDate.now().format(DateTimeFormatter.ofPattern("yyyy/MM/dd"));
            String relativePath = category + "/" + datePath + "/" + fileName;
            
            // 完整的文件保存路径
            Path filePath = Paths.get(uploadPath, relativePath);

            // 创建目录（如果不存在）
            Files.createDirectories(filePath.getParent());

            // 保存原图
            file.transferTo(filePath.toFile());

            // 返回文件访问URL
            String fileUrl = accessUrl + "/" + relativePath.replace("\\", "/");
            log.info("文件保存成功: {}", filePath.toAbsolutePath());
            // 生成缩略图
            String thumbUrl = generateThumbnail(filePath, category);
            Map<String, String> result = new HashMap<>();

            result.put("url", fileUrl);
            if (thumbUrl != null) {
                result.put("thumbUrl", thumbUrl);
            }
            return result;

        } catch (IOException e) {
            log.error("文件保存失败", e);
            throw new BusinessException("文件上传失败，请稍后重试");
        }
    }

    /**
     * 删除文件（可选功能）
     * 
     * @param fileUrl 文件URL
     * @return 删除结果
     */
    @DeleteMapping("/delete")
    public ResponseVO<?> deleteFile(@RequestParam("fileUrl") String fileUrl) {
        try {
            // 从URL中提取相对路径
            String relativePath = fileUrl.replace(accessUrl + "/", "");
            Path filePath = Paths.get(uploadPath, relativePath);

            // 删除文件
            if (Files.exists(filePath)) {
                Files.delete(filePath);
                log.info("文件删除成功: {}", filePath);
                return ResponseVO.success("删除成功", null);
            } else {
                throw new BusinessException("文件不存在");
            }

        } catch (IOException e) {
            log.error("文件删除失败", e);
            throw new BusinessException("文件删除失败，请稍后重试");
        }
    }
    private String generateThumbnail(Path originalPath, String category){
        // 检查是否是允许的缩略图分类
        if(!thumbnailCategories.contains(category)){
            return null;
        }
        try{
            Path basePath = Paths.get(uploadPath);
            String originalRelative = basePath.relativize(originalPath).toString().replace("\\", "/");
            //替换扩展名为 .webp
            String thumbnailRelative = "thumbnails/"+originalRelative.replaceAll("\\.[^.]+$", ".webp");
            Path thumbnailPath = Paths.get(uploadPath, thumbnailRelative);
            //创建缩略图目录
            Files.createDirectories(thumbnailPath.getParent());
            //缩略图
            BufferedImage scaledImage = Thumbnails.of(originalPath.toFile())
                    .width(thumbnailWidth)
                    .outputQuality(thumbnailQuality)
                    .asBufferedImage();
            //保存缩略图
            ImageIO.write(scaledImage, "webp", thumbnailPath.toFile());
            log.info("WebP缩略图生成成功: {}", thumbnailPath);

            return accessUrl + "/" + thumbnailRelative;
        } catch (IOException e) {
            log.error("缩略图生成失败", e);
            // 缩略图生成失败不影响主流程，返回null
            return null;
        }
    }
    /**
     * 判断是否需要压缩
     * JPEG 且 ≤2MB 且 宽高≤1920px → 不需要
     */
    private boolean needsCompression(MultipartFile file) throws IOException {
        String originalFilename = file.getOriginalFilename();
        if (originalFilename == null) return true;

        String ext = originalFilename.substring(originalFilename.lastIndexOf(".") + 1).toLowerCase();

        // 非JPEG格式 → 需要压缩（转JPEG）
        if (!"jpg".equals(ext) && !"jpeg".equals(ext)) {
            return true;
        }
        // 超过2MB → 需要压缩
        if (file.getSize() > AI_IMAGE_MAX_BYTES) {
            return true;
        }
        // 检查尺寸
        BufferedImage img = ImageIO.read(file.getInputStream());
        if (img == null) return true;
        return img.getWidth() > AI_IMAGE_MAX_DIMENSION || img.getHeight() > AI_IMAGE_MAX_DIMENSION;
    }
}
