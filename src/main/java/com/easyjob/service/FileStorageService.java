package com.easyjob.service;

import com.easyjob.exception.BusinessException;
import lombok.extern.slf4j.Slf4j;
import net.coobird.thumbnailator.Thumbnails;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import javax.imageio.ImageIO;
import javax.imageio.ImageReader;
import javax.imageio.stream.ImageInputStream;
import java.awt.Color;
import java.awt.image.BufferedImage;
import java.io.IOException;
import java.nio.file.*;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.*;

/** Ownership is encoded by server-created category/user-id paths. Legacy URLs remain readable. */
@Service
@Slf4j
public class FileStorageService {
    private static final Set<String> CATEGORIES = Set.of("messages", "ai-chat", "avatars", "covers", "articles", "comments");
    private static final Set<String> FORMATS = Set.of("jpeg", "png", "gif", "webp");
    private final Path root;
    private final String prefix;
    private final long maxPixels;
    private final int maxDimension, thumbnailWidth;
    private final float quality;
    private final Set<String> thumbnails;

    public FileStorageService(@Value("${file.upload.path:./uploads}") String path,
            @Value("${file.access.url:/uploads}") String access,
            @Value("${file.image.max-pixels:20000000}") long maxPixels,
            @Value("${file.image.max-dimension:10000}") int maxDimension,
            @Value("${file.thumbnail.width:640}") int width,
            @Value("${file.thumbnail.quality:0.8}") float quality,
            @Value("${file.thumbnail.categories:avatars,covers,messages,comments}") String categories) {
        root = Paths.get(path).toAbsolutePath().normalize();
        prefix = access.replaceAll("/+$", "") + "/";
        this.maxPixels = maxPixels; this.maxDimension = maxDimension;
        thumbnailWidth = width; this.quality = quality;
        thumbnails = new HashSet<>(Arrays.asList(categories.split(",")));
        if (maxPixels < 1 || maxDimension < 1 || width < 1 || quality <= 0 || quality > 1)
            throw new IllegalArgumentException("Invalid image storage limits");
    }

    private record Image(BufferedImage pixels, String format) {}

    private Image validate(MultipartFile file) throws IOException {
        if (file == null || file.isEmpty()) throw new BusinessException("请选择要上传的文件");
        if (file.getSize() > 15L * 1024 * 1024) throw new BusinessException("文件大小不能超过15MB");
        String name = Optional.ofNullable(file.getOriginalFilename()).orElse("");
        String extension = name.substring(name.lastIndexOf('.') + 1).toLowerCase(Locale.ROOT);
        if (extension.equals("jpg")) extension = "jpeg";
        if (!name.contains(".") || !FORMATS.contains(extension)) throw new BusinessException("只支持 jpg、jpeg、png、gif、webp 图片");
        // Inspect dimensions before allocating the raster; a MIME header does not prove the format.
        try (var input = file.getInputStream(); ImageInputStream stream = ImageIO.createImageInputStream(input)) {
            if (stream == null) throw new BusinessException("无法解析图片文件");
            var readers = ImageIO.getImageReaders(stream);
            if (!readers.hasNext()) throw new BusinessException("无法解析图片文件");
            ImageReader reader = readers.next();
            try {
                reader.setInput(stream, true, true);
                String format = reader.getFormatName().toLowerCase(Locale.ROOT);
                if (format.equals("jpg")) format = "jpeg";
                if (!FORMATS.contains(format) || !format.equals(extension)) throw new BusinessException("图片内容与文件扩展名不一致");
                int w = reader.getWidth(0), h = reader.getHeight(0);
                if (w < 1 || h < 1 || w > maxDimension || h > maxDimension || (long)w * h > maxPixels)
                    throw new BusinessException("图片尺寸过大，请缩小后上传");
                BufferedImage pixels = reader.read(0);
                if (pixels == null) throw new BusinessException("无法解析图片文件");
                return new Image(pixels, format);
            } finally { reader.dispose(); }
        }
    }

    public Map<String,String> upload(MultipartFile file, String category, Long uid) {
        if (uid == null || uid <= 0) throw new BusinessException(401, "请先登录");
        if (!CATEGORIES.contains(category)) throw new BusinessException("上传类型无效");
        Path target = null;
        boolean created = false;
        try {
            Image image = validate(file);
            String extension = category.equals("ai-chat") ? "jpg" : image.format().equals("jpeg") ? "jpg" : image.format();
            String relative = category + "/" + uid + "/" + LocalDate.now().format(DateTimeFormatter.ofPattern("yyyy/MM/dd"))
                    + "/" + UUID.randomUUID().toString().replace("-", "") + "." + extension;
            target = root.resolve(relative);
            prepareParent(target);
            Files.createFile(target);
            created = true;
            if (category.equals("ai-chat")) {
                BufferedImage rgb = new BufferedImage(image.pixels().getWidth(), image.pixels().getHeight(), BufferedImage.TYPE_INT_RGB);
                var g = rgb.createGraphics();
                try { g.setColor(Color.WHITE); g.fillRect(0, 0, rgb.getWidth(), rgb.getHeight()); g.drawImage(image.pixels(), 0, 0, null); }
                finally { g.dispose(); }
                Thumbnails.of(rgb).size(1920, 1920).outputQuality(quality).outputFormat("jpeg").toFile(target.toFile());
            } else file.transferTo(target);
            var result = new LinkedHashMap<String,String>();
            result.put("url", prefix + relative); result.put("path", relative);
            result.put("fileName", file.getOriginalFilename());
            String thumb = thumbnail(target, relative, category);
            if (thumb != null) result.put("thumbUrl", thumb);
            return result;
        } catch (IOException | RuntimeException ex) {
            if (created) try { Files.deleteIfExists(target); } catch (IOException cleanup) { log.warn("Upload cleanup failed", cleanup); }
            if (ex instanceof BusinessException business) throw business;
            log.warn("Image upload failed", ex);
            throw new BusinessException("图片上传失败，请稍后重试");
        }
    }

    private void prepareParent(Path target) throws IOException {
        Files.createDirectories(root);
        for (Path part = target.getParent(); part != null && part.startsWith(root); part = part.getParent())
            if (Files.isSymbolicLink(part)) throw new BusinessException(403, "文件目录无效");
        Files.createDirectories(target.getParent());
        if (!target.getParent().toRealPath().startsWith(root.toRealPath())) throw new BusinessException(403, "文件目录无效");
    }

    private String thumbnail(Path original, String relative, String category) {
        if (!thumbnails.contains(category)) return null;
        Path target = root.resolve("thumbnails/" + relative.replaceFirst("\\.[^.]+$", ".webp"));
        try {
            prepareParent(target);
            BufferedImage scaled = Thumbnails.of(original.toFile()).width(thumbnailWidth).asBufferedImage();
            if (!ImageIO.write(scaled, "webp", target.toFile()) || !Files.isRegularFile(target) || Files.size(target) == 0) {
                Files.deleteIfExists(target);
                return null;
            }
            return prefix + root.relativize(target).toString().replace('\\', '/');
        } catch (IOException | RuntimeException ex) {
            try { Files.deleteIfExists(target); } catch (IOException ignored) { /* Original remains valid. */ }
            log.warn("Thumbnail unavailable; original retained", ex);
            return null;
        }
    }

    public void delete(String url, Long uid) {
        if (uid == null || uid <= 0) throw new BusinessException(401, "请先登录");
        if (url == null || !url.startsWith(prefix)) throw new BusinessException("文件地址无效");
        String relative = url.substring(prefix.length());
        if (relative.contains("\\") || relative.contains("%") || relative.contains(":") || relative.contains("?") || relative.contains("#"))
            throw new BusinessException("文件地址无效");
        String[] parts = relative.split("/", -1);
        if (parts.length != 6 || Arrays.stream(parts).anyMatch(p -> p.isEmpty() || p.equals(".") || p.equals("..")))
            throw new BusinessException(403, "该文件没有可验证的上传归属");
        if (!CATEGORIES.contains(parts[0]) || !parts[1].equals(uid.toString())) throw new BusinessException(403, "只能删除自己上传的文件");
        if (!parts[5].matches("[a-f0-9]{32}\\.(jpg|jpeg|png|gif|webp)")) throw new BusinessException("文件地址无效");
        Path target = root.resolve(relative).normalize();
        if (!target.startsWith(root)) throw new BusinessException(403, "文件地址无效");
        try {
            for (Path part = target; part != null && part.startsWith(root); part = part.getParent())
                if (Files.isSymbolicLink(part)) throw new BusinessException(403, "文件地址无效");
            if (!Files.isRegularFile(target, LinkOption.NOFOLLOW_LINKS)) throw new BusinessException(404, "文件不存在");
            if (!target.toRealPath().startsWith(root.toRealPath())) throw new BusinessException(403, "文件地址无效");
            Files.delete(target);
            Path thumb = root.resolve("thumbnails/" + relative.replaceFirst("\\.[^.]+$", ".webp"));
            for (Path part = thumb; part != null && part.startsWith(root); part = part.getParent())
                if (Files.isSymbolicLink(part)) return;
            Files.deleteIfExists(thumb);
        } catch (IOException ex) { throw new BusinessException("文件删除失败，请稍后重试", ex); }
    }
}
