package com.easyjob.service;

import com.easyjob.exception.BusinessException;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.mock.web.MockMultipartFile;
import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.nio.file.*;
import static org.junit.jupiter.api.Assertions.*;

class FileStorageTests {
    @TempDir Path root;
    FileStorageService service(long pixels) { return new FileStorageService(root.toString(), "/uploads", pixels, 10000, 640, .8f, "covers"); }
    MockMultipartFile png(String filename, int width, int height) throws Exception {
        var bytes = new ByteArrayOutputStream();
        ImageIO.write(new BufferedImage(width, height, BufferedImage.TYPE_INT_ARGB), "png", bytes);
        return new MockMultipartFile("file", filename, "image/png", bytes.toByteArray());
    }
    @Test void ownerCanDeleteButAnotherUserAndLegacyAddressesCannot() throws Exception {
        var files = service(20000000);
        var result = files.upload(png("x.png", 20, 30), "articles", 7L);
        assertTrue(result.get("path").startsWith("articles/7/"));
        assertEquals(403, assertThrows(BusinessException.class, () -> files.delete(result.get("url"), 8L)).getCode());
        assertTrue(Files.exists(root.resolve(result.get("path"))));
        assertThrows(BusinessException.class, () -> files.delete("/uploads/articles/2025/01/01/old.png", 7L));
        files.delete(result.get("url"), 7L);
        assertFalse(Files.exists(root.resolve(result.get("path"))));
    }
    @Test void rejectsTraversalForeignUrlsAndEncodedPaths() {
        for (String url : new String[]{"/uploads/../x", "/uploads/articles/7/../../x", "/uploads/articles/7/%2e%2e/x", "https://other/x", "/uploads/articles\\7\\x"})
            assertThrows(BusinessException.class, () -> service(1000).delete(url, 7L), url);
    }
    @Test void rejectsFakeImagesMismatchedExtensionsAndExcessivePixels() throws Exception {
        assertThrows(BusinessException.class, () -> service(1000).upload(new MockMultipartFile("file", "x.jpg", "image/jpeg", "not a picture".getBytes()), "articles", 7L));
        var mismatched = png("x.jpg", 10, 10);
        assertThrows(BusinessException.class, () -> service(1000).upload(mismatched, "articles", 7L));
        var tooLarge = png("x.png", 40, 40);
        assertThrows(BusinessException.class, () -> service(1000).upload(tooLarge, "articles", 7L));
    }
    @Test void visionUploadIsJpegAndPreservesAspectRatio() throws Exception {
        var result = service(20000000).upload(png("portrait.png", 600, 3000), "ai-chat", 7L);
        var file = root.resolve(result.get("path"));
        assertEquals(0xff, Files.readAllBytes(file)[0] & 0xff);
        var image = ImageIO.read(file.toFile());
        assertEquals(1920, image.getHeight()); assertEquals(384, image.getWidth());
        assertEquals(0xffffff, image.getRGB(100,100) & 0xffffff);
    }
    @Test void thumbnailAddressOnlyReturnedForAnExistingImage() throws Exception {
        var result = service(20000000).upload(png("cover.png", 100, 60), "covers", 7L);
        if (result.containsKey("thumbUrl")) {
            var thumb = root.resolve(result.get("thumbUrl").substring("/uploads/".length()));
            assertTrue(Files.size(thumb) > 0); assertNotNull(ImageIO.read(thumb.toFile()));
            service(20000000).delete(result.get("url"), 7L);
            assertFalse(Files.exists(thumb));
        } else assertTrue(Files.exists(root.resolve(result.get("path"))));
    }
    @Test void authenticationIsRequiredForStorageOperations() throws Exception {
        var file = png("x.png",10,10);
        assertEquals(401, assertThrows(BusinessException.class, () -> service(1000).upload(file,"articles",null)).getCode());
        assertEquals(401, assertThrows(BusinessException.class, () -> service(1000).delete("/uploads/x",null)).getCode());
    }
}
