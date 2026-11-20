package com.easyjob.controller;

import com.easyjob.service.AdminConsoleService;
import com.easyjob.service.FileStorageService;
import com.easyjob.service.SpaceCustomizationService;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.DecorationSpec;
import com.easyjob.vo.ResponseVO;
import com.easyjob.vo.SpaceCustomization.AdminCatalog;
import com.easyjob.vo.SpaceCustomization.ArtworkDraft;
import com.easyjob.vo.SpaceCustomization.Product;
import com.easyjob.vo.SpaceCustomization.ProductEdit;
import com.easyjob.vo.SpaceCustomization.PublishProduct;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.Map;

@RestController
@RequestMapping("/api/admin/space-skins")
@RequiredArgsConstructor
public class AdminSpaceSkinController {
    private final SpaceCustomizationService customization;
    private final AdminConsoleService admin;
    private final FileStorageService files;

    public record ArtworkEdit(String name, String artist, Integer version) {}

    @GetMapping
    public ResponseVO<AdminCatalog> catalog() {
        operator();
        return ResponseVO.success(customization.adminCatalog());
    }

    /** Uploads one image for {@code asset} (an image field or the list key) of {@code slot}, checked against its contract rule. */
    @PostMapping("/artworks/images")
    public ResponseVO<Map<String, Object>> artworkImage(@RequestParam String slot, @RequestParam String asset,
                                                        @RequestParam MultipartFile file) {
        Long adminId = operator();
        return ResponseVO.success(files.uploadDecoration(file, DecorationSpec.SPEC.imageRule(slot, asset), adminId));
    }

    @PostMapping("/artworks")
    public ResponseVO<String> createArtwork(@RequestBody ArtworkDraft input) {
        return ResponseVO.success("作品已保存", customization.createArtwork(operator(), input));
    }

    @PutMapping("/artworks/{id}")
    public ResponseVO<?> editArtwork(@PathVariable String id, @RequestBody ArtworkEdit input) {
        operator();
        customization.editArtwork(id, input.name(), input.artist(), input.version());
        return ResponseVO.success("作品信息已更新");
    }

    @DeleteMapping("/artworks/{id}")
    public ResponseVO<?> withdrawArtwork(@PathVariable String id, @RequestParam Integer version) {
        operator();
        customization.withdrawArtwork(id, version);
        return ResponseVO.success("作品已撤回");
    }

    @PostMapping
    public ResponseVO<String> publish(@RequestBody PublishProduct input) {
        operator();
        return ResponseVO.success("装扮已上架", customization.publishProduct(input));
    }

    @PutMapping("/{id}")
    public ResponseVO<Product> update(@PathVariable String id, @RequestBody ProductEdit input) {
        operator();
        return ResponseVO.success("商品已更新", customization.updateProduct(id, input));
    }

    private Long operator() {
        Long id = UserContext.getUserId();
        admin.requireAdmin(id);
        return id;
    }
}
