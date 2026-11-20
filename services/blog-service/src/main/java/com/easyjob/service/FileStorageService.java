package com.easyjob.service;

import com.easyjob.exception.BusinessException;
import com.easyjob.vo.DecorationSpec.ImageRule;
import lombok.extern.slf4j.Slf4j;
import net.coobird.thumbnailator.Thumbnails;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import javax.imageio.ImageIO;
import javax.imageio.ImageWriteParam;
import javax.imageio.ImageWriter;
import javax.imageio.stream.MemoryCacheImageOutputStream;
import javax.imageio.ImageReader;
import javax.imageio.stream.ImageInputStream;
import java.awt.Color;
import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.file.*;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.awt.Graphics2D;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Iterator;
import java.util.LinkedHashMap;

/** Ownership is encoded by server-created category/user-id paths. Legacy URLs remain readable. */
@Service
@Slf4j
public class FileStorageService {
    private static final Set<String> CATEGORIES = Set.of("messages", "ai-chat", "avatars", "covers", "articles", "comments");
    private static final String SPACE_BANNERS = "space-banners";
    private static final String DECORATIONS = "space-decorations";
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

    /** A checked decoration image. {@code pixels} is only decoded for static rules, which are re-encoded. */
    private record Decoration(String format, int width, int height, BufferedImage pixels) {}

    /** A decoration image already stored on the server, with the dimensions read from the file. */
    public record StoredImage(String url, int width, int height) {}

    private Image validate(MultipartFile file) throws IOException {
        if (file == null || file.isEmpty()) throw new BusinessException("请选择要上传的文件");
        if (file.getSize() > 15L * 1024 * 1024) throw new BusinessException("文件大小不能超过15MB");
        String extension = extension(file.getOriginalFilename());
        if (!FORMATS.contains(extension)) throw new BusinessException("只支持 jpg、jpeg、png、gif、webp 图片");
        // Inspect dimensions before allocating the raster; a MIME header does not prove the format.
        try (InputStream input = file.getInputStream(); ImageInputStream stream = ImageIO.createImageInputStream(input)) {
            if (stream == null) throw new BusinessException("无法解析图片文件");
            Iterator<ImageReader> readers = ImageIO.getImageReaders(stream);
            if (!readers.hasNext()) throw new BusinessException("无法解析图片文件");
            ImageReader reader = readers.next();
            try {
                reader.setInput(stream, true, true);
                String format = reader.getFormatName().toLowerCase(Locale.ROOT);
                if (format.equals("jpg")) format = "jpeg";
                if (!FORMATS.contains(format) || !format.equals(extension)) throw new BusinessException("图片内容与文件扩展名不一致");
                int w = reader.getWidth(0), h = reader.getHeight(0);
                checkBounds(w, h);
                BufferedImage pixels = reader.read(0);
                if (pixels == null) throw new BusinessException("无法解析图片文件");
                return new Image(pixels, format);
            } finally { reader.dispose(); }
        }
    }

    private static String extension(String fileName) {
        String name = Optional.ofNullable(fileName).orElse("");
        if (!name.contains(".")) return "";
        String extension = name.substring(name.lastIndexOf('.') + 1).toLowerCase(Locale.ROOT);
        return extension.equals("jpg") ? "jpeg" : extension;
    }

    private void checkBounds(int w, int h) {
        if (w < 1 || h < 1 || w > maxDimension || h > maxDimension || (long) w * h > maxPixels)
            throw new BusinessException("图片尺寸过大，请缩小后上传");
    }

    /**
     * Checks a decoration image against its contract rule. The format comes from the file signature,
     * dimensions from the header, so animated files never need to be decoded.
     */
    private Decoration inspectDecoration(byte[] data, String extension, ImageRule rule) throws IOException {
        if (!rule.formats().contains(extension)) throw new BusinessException("该位置只支持 " + String.join("、", rule.formats()).toUpperCase() + " 图片");
        if (data.length > rule.maxKiB() * 1024L) throw new BusinessException("图片最大 " + rule.maxKiB() + " KB");
        String format = signature(data);
        if (!extension.equals(format)) throw new BusinessException("图片内容与文件扩展名不一致");
        int[] transparentKey = format.equals("gif") ? checkGif(data) : walkChunks(data, format, !rule.animated());
        int[] size = dimensions(data, format);
        int w = size[0], h = size[1];
        checkBounds(w, h);
        if (rule.square() && w != h) throw new BusinessException("图片须为正方形，" + rule.describe());
        if (w < rule.minWidth() || w > rule.maxWidth() || h < rule.minHeight() || h > rule.maxHeight())
            throw new BusinessException("图片尺寸不符合要求：" + rule.describe());
        if (rule.animated()) return new Decoration(format, w, h, null);
        BufferedImage pixels = ImageIO.read(new ByteArrayInputStream(data));
        if (pixels == null || pixels.getWidth() != w || pixels.getHeight() != h) throw new BusinessException("无法解析图片文件");
        if (transparentKey != null && !pixels.getColorModel().hasAlpha()) pixels = applyTransparentColor(pixels, transparentKey);
        if (rule.transparency()) checkTransparency(pixels);
        return new Decoration(format, w, h, pixels);
    }

    private static String signature(byte[] data) {
        if (data.length >= 8 && Arrays.equals(Arrays.copyOf(data, 8), new byte[]{(byte) 0x89, 'P', 'N', 'G', '\r', '\n', 0x1a, '\n'})) return "png";
        if (data.length >= 13 && (startsWith(data, 0, "GIF87a") || startsWith(data, 0, "GIF89a"))) return "gif";
        if (data.length >= 30 && startsWith(data, 0, "RIFF") && startsWith(data, 8, "WEBP")) return "webp";
        throw new BusinessException("无法识别图片格式");
    }

    private static boolean startsWith(byte[] data, int offset, String ascii) {
        byte[] expected = ascii.getBytes(StandardCharsets.US_ASCII);
        return data.length >= offset + expected.length && Arrays.equals(data, offset, offset + expected.length, expected, 0, expected.length);
    }

    private static int[] dimensions(byte[] data, String format) {
        ByteBuffer buffer = ByteBuffer.wrap(data);
        switch (format) {
            case "png" -> {
                if (!startsWith(data, 12, "IHDR")) throw new BusinessException("图片数据不完整");
                return new int[]{buffer.getInt(16), buffer.getInt(20)};
            }
            case "gif" -> {
                buffer.order(ByteOrder.LITTLE_ENDIAN);
                return new int[]{Short.toUnsignedInt(buffer.getShort(6)), Short.toUnsignedInt(buffer.getShort(8))};
            }
            default -> {
                if (startsWith(data, 12, "VP8X")) {
                    return new int[]{1 + uint24(data, 24), 1 + uint24(data, 27)};
                }
                if (startsWith(data, 12, "VP8L") && (data[20] & 0xff) == 0x2f) {
                    int b0 = data[21] & 0xff, b1 = data[22] & 0xff, b2 = data[23] & 0xff, b3 = data[24] & 0xff;
                    return new int[]{1 + (b0 | (b1 & 0x3f) << 8), 1 + ((b1 >> 6) | b2 << 2 | (b3 & 0x0f) << 10)};
                }
                if (startsWith(data, 12, "VP8 ") && (data[23] & 0xff) == 0x9d && (data[24] & 0xff) == 0x01 && (data[25] & 0xff) == 0x2a) {
                    buffer.order(ByteOrder.LITTLE_ENDIAN);
                    return new int[]{buffer.getShort(26) & 0x3fff, buffer.getShort(28) & 0x3fff};
                }
                throw new BusinessException("图片数据不完整");
            }
        }
    }

    private static int uint24(byte[] data, int offset) {
        return (data[offset] & 0xff) | (data[offset + 1] & 0xff) << 8 | (data[offset + 2] & 0xff) << 16;
    }

    /** GIF blocks are not walked; a well-formed file still has to end with the trailer byte. */
    private static int[] checkGif(byte[] data) {
        if ((data[data.length - 1] & 0xff) != 0x3b) throw new BusinessException("图片数据不完整");
        return null;
    }

    /**
     * Walks PNG or WebP chunks so truncated files are rejected. Image readers silently return the first
     * frame of APNG or animated WebP, so static positions must detect animation chunks here.
     * Returns the colour key of a true-colour PNG {@code tRNS} chunk, if any.
     */
    private static int[] walkChunks(byte[] data, String format, boolean rejectAnimation) {
        boolean png = format.equals("png");
        int position = png ? 8 : 12;
        int[] transparentKey = null;
        boolean trueColor = false;
        ByteBuffer buffer = ByteBuffer.wrap(data).order(png ? ByteOrder.BIG_ENDIAN : ByteOrder.LITTLE_ENDIAN);
        while (data.length - position >= 8) {
            long length = Integer.toUnsignedLong(png ? buffer.getInt(position) : buffer.getInt(position + 4));
            String type = new String(data, png ? position + 4 : position, 4, StandardCharsets.US_ASCII);
            if (rejectAnimation && (type.equals("acTL") || type.equals("ANIM") || type.equals("ANMF"))) {
                throw new BusinessException("该位置只支持静态图片");
            }
            long payload = length + (png ? 4 : length % 2);
            int body = position + 8;
            if (payload > data.length - body) throw new BusinessException("图片数据不完整");
            if (png && type.equals("IHDR") && length == 13) trueColor = (data[body + 9] & 0xff) == 2;
            if (png && trueColor && type.equals("tRNS") && length == 6) {
                transparentKey = new int[]{Short.toUnsignedInt(buffer.getShort(body)), Short.toUnsignedInt(buffer.getShort(body + 2)),
                        Short.toUnsignedInt(buffer.getShort(body + 4))};
            }
            position = (int) (body + payload);
        }
        if (position != data.length) throw new BusinessException("图片数据不完整");
        return transparentKey;
    }

    private BufferedImage applyTransparentColor(BufferedImage source, int[] key) {
        BufferedImage rgba = new BufferedImage(source.getWidth(), source.getHeight(), BufferedImage.TYPE_INT_ARGB);
        java.awt.image.Raster raster = source.getRaster();
        int[] sample = new int[raster.getNumBands()];
        for (int y = 0; y < source.getHeight(); y++) {
            for (int x = 0; x < source.getWidth(); x++) {
                raster.getPixel(x, y, sample);
                int color = source.getRGB(x, y);
                if (sample[0] == key[0] && sample[1] == key[1] && sample[2] == key[2]) color &= 0xffffff;
                rgba.setRGB(x, y, color);
            }
        }
        return rgba;
    }

    private void checkTransparency(BufferedImage image) {
        boolean visible = false, transparent = false;
        if (image.getColorModel().hasAlpha()) {
            for (int y = 0; y < image.getHeight(); y++) {
                for (int x = 0; x < image.getWidth(); x++) {
                    int alpha = image.getRGB(x, y) >>> 24;
                    visible |= alpha > 0;
                    transparent |= alpha == 0;
                    if (visible && transparent) return;
                }
            }
        }
        throw new BusinessException("该图片需要同时包含透明区域和可见图案");
    }

    public Map<String,String> upload(MultipartFile file, String category, Long uid) {
        if (!CATEGORIES.contains(category)) throw new BusinessException("上传类型无效");
        return uploadImage(file, category, uid);
    }

    /** Stores one decoration image after checking it against its contract rule. Static images are re-encoded as PNG. */
    public Map<String, Object> uploadDecoration(MultipartFile file, ImageRule rule, Long uid) {
        if (uid == null || uid <= 0) throw new BusinessException(401, "请先登录");
        if (file == null || file.isEmpty()) throw new BusinessException("请选择要上传的文件");
        if (file.getSize() > rule.maxKiB() * 1024L) throw new BusinessException("图片最大 " + rule.maxKiB() + " KB");
        Path target = null;
        boolean created = false;
        try {
            byte[] data = file.getBytes();
            Decoration image = inspectDecoration(data, extension(file.getOriginalFilename()), rule);
            String relative = DECORATIONS + "/" + uid + "/" + LocalDate.now().format(DateTimeFormatter.ofPattern("yyyy/MM/dd"))
                    + "/" + UUID.randomUUID().toString().replace("-", "") + "." + (image.pixels() == null ? image.format() : "png");
            target = root.resolve(relative);
            prepareParent(target);
            Files.createFile(target);
            created = true;
            // Animated files keep their original bytes; re-encoding would drop every frame after the first.
            if (image.pixels() == null) Files.write(target, data);
            else if (!ImageIO.write(image.pixels(), "png", target.toFile())) throw new IOException("No PNG encoder available");
            LinkedHashMap<String, Object> result = new LinkedHashMap<>();
            result.put("url", prefix + relative);
            result.put("width", image.width());
            result.put("height", image.height());
            return result;
        } catch (IOException | RuntimeException ex) {
            if (created) try { Files.deleteIfExists(target); } catch (IOException cleanup) { log.warn("Upload cleanup failed", cleanup); }
            if (ex instanceof BusinessException business) throw business;
            log.warn("Decoration upload failed", ex);
            throw new BusinessException("图片上传失败，请稍后重试");
        }
    }

    /** Confirms that {@code url} is a decoration image uploaded by {@code uid} that still satisfies {@code rule}. */
    public StoredImage requireDecorationImage(String url, ImageRule rule, Long uid) {
        Path target = requireOwnedImage(url, uid, DECORATIONS, "装扮");
        try {
            Decoration image = inspectDecoration(Files.readAllBytes(target), extension(target.getFileName().toString()), rule);
            return new StoredImage(url, image.width(), image.height());
        } catch (IOException ex) {
            throw new BusinessException("无法读取装扮图片，请重新上传", ex);
        }
    }

    private Map<String,String> uploadImage(MultipartFile file, String category, Long uid) {
        if (uid == null || uid <= 0) throw new BusinessException(401, "请先登录");
        Path target = null;
        boolean created = false;
        try {
            Image image = validate(file);
            String extension = category.equals("ai-chat") || image.format().equals("jpeg") ? "jpg" : image.format();
            String relative = category + "/" + uid + "/" + LocalDate.now().format(DateTimeFormatter.ofPattern("yyyy/MM/dd"))
                    + "/" + UUID.randomUUID().toString().replace("-", "") + "." + extension;
            target = root.resolve(relative);
            prepareParent(target);
            Files.createFile(target);
            created = true;
            if (category.equals("ai-chat")) {
                BufferedImage rgb = new BufferedImage(image.pixels().getWidth(), image.pixels().getHeight(), BufferedImage.TYPE_INT_RGB);
                Graphics2D g = rgb.createGraphics();
                try { g.setColor(Color.WHITE); g.fillRect(0, 0, rgb.getWidth(), rgb.getHeight()); g.drawImage(image.pixels(), 0, 0, null); }
                finally { g.dispose(); }
                Thumbnails.of(rgb).size(1920, 1920).outputQuality(quality).outputFormat("jpeg").toFile(target.toFile());
            } else file.transferTo(target);
            LinkedHashMap<String, String> result = new LinkedHashMap<String,String>();
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
        if (!SPACE_BANNERS.equals(category) && !thumbnails.contains(category)) return null;
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
        deleteOwned(url, uid, CATEGORIES);
    }

    public byte[] prepareSpaceBanner(MultipartFile file) {
        try (ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            BufferedImage image = validate(file).pixels();
            if (image.getWidth() > 2560 || image.getHeight() > 2560) {
                image = Thumbnails.of(image).size(2560, 2560).asBufferedImage();
            }
            Iterator<ImageWriter> writers = ImageIO.getImageWritersByFormatName("webp");
            if (!writers.hasNext()) throw new IOException("No WebP encoder available");
            ImageWriter writer = writers.next();
            try (MemoryCacheImageOutputStream stream = new MemoryCacheImageOutputStream(output)) {
                ImageWriteParam options = writer.getDefaultWriteParam();
                options.setCompressionMode(ImageWriteParam.MODE_EXPLICIT);
                options.setCompressionType(options.getCompressionTypes()[0]);
                options.setCompressionQuality(0.94f);
                writer.setOutput(stream);
                writer.write(null, new javax.imageio.IIOImage(image, null, null), options);
            } finally {
                writer.dispose();
            }
            return output.toByteArray();
        } catch (IOException error) {
            throw new BusinessException("头图处理失败，请更换图片后重试", error);
        }
    }

    public Map<String, String> publishSpaceBanner(byte[] image, Long uid) {
        String relative = SPACE_BANNERS + "/" + uid + "/" + LocalDate.now().format(DateTimeFormatter.ofPattern("yyyy/MM/dd"))
                + "/" + UUID.randomUUID().toString().replace("-", "") + ".webp";
        Path target = root.resolve(relative);
        boolean created = false;
        try {
            prepareParent(target);
            Files.createFile(target);
            created = true;
            Files.write(target, image);
            String thumb = thumbnail(target, relative, SPACE_BANNERS);
            if (thumb == null) throw new IOException("Could not encode space banner thumbnail");
            return Map.of("url", prefix + relative, "path", relative, "thumbUrl", thumb);
        } catch (IOException error) {
            if (created) discardSpaceBanner(prefix + relative, uid);
            throw new BusinessException("头图发布失败，请稍后重试", error);
        }
    }

    public void discardSpaceBanner(String url, Long uid) {
        if (url == null) return;
        try {
            deleteOwned(url, uid, Set.of(SPACE_BANNERS));
        } catch (RuntimeException error) {
            log.warn("Could not clean up space banner for {}", uid, error);
        }
    }

    private void deleteOwned(String url, Long uid, Set<String> categories) {
        if (uid == null || uid <= 0) throw new BusinessException(401, "请先登录");
        if (url == null || !url.startsWith(prefix)) throw new BusinessException("文件地址无效");
        String relative = url.substring(prefix.length());
        if (relative.contains("\\") || relative.contains("%") || relative.contains(":") || relative.contains("?") || relative.contains("#"))
            throw new BusinessException("文件地址无效");
        String[] parts = relative.split("/", -1);
        if (parts.length != 6 || Arrays.stream(parts).anyMatch(p -> p.isEmpty() || p.equals(".") || p.equals("..")))
            throw new BusinessException(403, "该文件没有可验证的上传归属");
        if (!categories.contains(parts[0]) || !parts[1].equals(uid.toString())) throw new BusinessException(403, "只能删除自己上传的文件");
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

    /** Only server-issued uploads owned by the commenter can become new attachments. */
    public void requireCommentImage(String url, Long uid) {
        requireOwnedImage(url, uid, "comments", "评论");
    }

    private Path requireOwnedImage(String url, Long uid, String category, String label) {
        if (uid == null || uid <= 0) throw new BusinessException(401, "请先登录");
        String start = prefix + category + "/" + uid + "/";
        if (url == null || !url.startsWith(start)
                || !url.substring(start.length()).matches("[0-9]{4}/[0-9]{2}/[0-9]{2}/[a-f0-9]{32}\\.(jpg|jpeg|png|gif|webp)"))
            throw new BusinessException(400, "请选择自己上传的" + label + "图片");
        Path target = root.resolve(url.substring(prefix.length())).normalize();
        try {
            for (Path part = target; part != null && part.startsWith(root); part = part.getParent())
                if (Files.isSymbolicLink(part)) throw new BusinessException(400, label + "图片地址无效");
            if (!target.startsWith(root) || !Files.isRegularFile(target, LinkOption.NOFOLLOW_LINKS)
                    || !target.toRealPath().startsWith(root.toRealPath()))
                throw new BusinessException(400, label + "图片不存在，请重新上传");
        } catch (IOException ex) { throw new BusinessException("无法读取" + label + "图片，请重新上传", ex); }
        return target;
    }
}
