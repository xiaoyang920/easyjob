package com.easyjob.service;

import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.GrowthMapper;
import com.easyjob.mapper.SpaceSkinMapper;
import com.easyjob.service.FileStorageService.StoredImage;
import com.easyjob.vo.DecorationSpec;
import com.easyjob.vo.DecorationSpec.ImageField;
import com.easyjob.vo.DecorationSpec.ListField;
import com.easyjob.vo.DecorationSpec.Setting;
import com.easyjob.vo.DecorationSpec.Slot;
import com.easyjob.vo.SpaceArtwork;
import com.easyjob.vo.SpaceArtwork.Assets;
import com.easyjob.vo.SpaceArtwork.Assets.Item;
import com.easyjob.vo.SpaceBannerView;
import com.easyjob.vo.SpaceCustomization.AdminCatalog;
import com.easyjob.vo.SpaceCustomization.Appearance;
import com.easyjob.vo.SpaceCustomization.ArtworkDraft;
import com.easyjob.vo.SpaceCustomization.ArtworkDraft.DraftItem;
import com.easyjob.vo.SpaceCustomization.Catalog;
import com.easyjob.vo.SpaceCustomization.Product;
import com.easyjob.vo.SpaceCustomization.ProductEdit;
import com.easyjob.vo.SpaceCustomization.PublishProduct;
import com.easyjob.vo.SpaceCustomization.Purchase;
import com.easyjob.vo.SpaceCustomization.PurchaseOrder;
import com.easyjob.vo.SpaceCustomization.Quote;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.Collection;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import java.util.function.Predicate;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/** Sells designer-made space artworks for coins and keeps track of what each user wears. */
@Service
@RequiredArgsConstructor
public class SpaceCustomizationService {
    private static final Pattern PRODUCT_ID = Pattern.compile("[a-z][a-z0-9-]{0,31}");
    private static final int MAX_TEXT = 60;

    private final SpaceSkinMapper store;
    private final GrowthMapper growth;
    private final FileStorageService files;

    /** Loads the decoration contract at startup, so a broken contract fails the deploy instead of the first upload. */
    @PostConstruct
    void checkDecorationContract() {
        DecorationSpec.SPEC.slots();
    }

    @Transactional(readOnly = true)
    public Appearance appearance(Long userId) {
        Appearance base = Objects.requireNonNullElse(store.appearance(userId), Appearance.DEFAULT);
        return base.withArtworks(store.equippedArtworks(userId).stream()
                .collect(Collectors.toMap(SpaceArtwork::slot, artwork -> artwork)));
    }

    /** The artwork each of {@code userIds} currently wears in {@code slot}; users wearing nothing are absent. */
    @Transactional(readOnly = true)
    public Map<Long, SpaceArtwork> wornArtworks(Collection<Long> userIds, String slot) {
        if (userIds.isEmpty()) return Map.of();
        return store.wornArtworks(userIds, slot).stream()
                .collect(Collectors.toMap(SpaceArtwork.Worn::userId, SpaceArtwork.Worn::artwork));
    }

    /** Sticker packs the user can send from, in a stable order for the chat picker. */
    @Transactional(readOnly = true)
    public List<SpaceArtwork> ownedStickerPacks(Long userId) {
        return store.ownedArtworks(userId, SpaceArtwork.STICKER_PACK);
    }

    /** The sticker a user is allowed to send: the pack must be a sticker pack the user owns. */
    @Transactional(readOnly = true)
    public Item requireSticker(Long userId, String packId, String key) {
        SpaceArtwork pack = SpaceArtwork.isId(packId) ? artworksById(List.of(packId)).get(packId) : null;
        if (pack == null || !SpaceArtwork.STICKER_PACK.equals(pack.slot())) throw new BusinessException(404, "表情包不存在");
        if (!store.ownsArtwork(userId, packId)) throw new BusinessException(403, "请先在商城获得这套表情包");
        return pack.assets().items().stream().filter(item -> item.key().equals(key)).findFirst()
                .orElseThrow(() -> new BusinessException(404, "表情不存在"));
    }

    @Transactional(readOnly = true)
    public Map<String, SpaceArtwork> artworksById(Collection<String> ids) {
        if (ids.isEmpty()) return Map.of();
        return store.artworksById(ids).stream().collect(Collectors.toMap(SpaceArtwork::artworkId, artwork -> artwork));
    }

    @Transactional(readOnly = true)
    public Catalog catalog(Long userId) {
        Integer balance = store.balance(userId);
        if (balance == null) throw new BusinessException(403, "账号不可用");
        Appearance appearance = appearance(userId);
        List<Product> products = store.shopProducts(userId).stream().filter(product -> !product.artworks().isEmpty()).toList();
        Set<String> owned = products.stream().filter(Product::owned)
                .flatMap(product -> product.artworks().values().stream()).collect(Collectors.toSet());
        // A product counts as owned once the user has every artwork it grants, however they were obtained.
        List<Product> shown = products.stream().map(product -> !product.owned() && owned.containsAll(product.artworks().values())
                ? product.withOwned(true) : product).toList();
        Map<String, Quote> quotes = new LinkedHashMap<>();
        shown.stream().filter(product -> !product.owned())
                .forEach(product -> quotes.put(product.productId(), quote(product, owned::contains)));
        Set<String> referenced = new HashSet<>(owned);
        products.forEach(product -> referenced.addAll(product.artworks().values()));
        appearance.equippedArtworks().values().forEach(artwork -> referenced.add(artwork.artworkId()));
        List<SpaceArtwork> artworks = store.artworks().stream()
                .filter(artwork -> referenced.contains(artwork.artworkId())).toList();
        return new Catalog(appearance, shown, balance, artworks, owned.stream().sorted().toList(), quotes);
    }

    /**
     * What this user pays: the list price reduced by the share of the bundle's artworks they already own,
     * rounded up and never below one coin. A standalone product has one artwork, so it always costs its list price.
     */
    static Quote quote(Product product, Predicate<String> owns) {
        int total = product.artworks().size();
        int alreadyOwned = (int) product.artworks().values().stream().filter(owns).count();
        int price = alreadyOwned == 0 ? product.coinPrice()
                : Math.max(1, (int) Math.ceil(product.coinPrice() * (double) (total - alreadyOwned) / total));
        return new Quote(price, alreadyOwned, total);
    }

    @Transactional
    public Purchase purchase(Long userId, String productId, UUID requestId, Integer expectedPrice) {
        validateProductId(productId);
        if (requestId == null) throw new BusinessException("缺少购买请求编号");
        int balance = lockAccount(userId);
        String previous = store.productForRequest(userId, requestId.toString());
        if (previous != null) {
            if (!previous.equals(productId)) throw new BusinessException(409, "请求编号已用于另一件商品");
            return new Purchase(productId, balance, true);
        }
        Product product = store.lockProduct(userId, productId);
        if (product == null) throw new BusinessException(404, "这件装扮商品未上架");
        Set<String> alreadyOwned = product.artworks().values().stream()
                .filter(id -> store.ownsArtwork(userId, id)).collect(Collectors.toSet());
        if (product.owned() || (!product.artworks().isEmpty() && alreadyOwned.size() == product.artworks().size())) {
            return new Purchase(productId, balance, true);
        }
        if (!product.listed() || product.coinPrice() <= 0 || product.artworks().isEmpty()) {
            throw new BusinessException(404, "这件装扮商品未上架");
        }
        product.artworks().forEach(this::requireArtwork);
        int price = quote(product, alreadyOwned::contains).price();
        if (expectedPrice != null && expectedPrice != price) {
            throw new BusinessException(409, "商品价格已变更，请刷新商城后重试");
        }
        if (growth.debitCoins(price, userId, price) != 1) throw new BusinessException("硬币余额不足");
        String purchaseId = UUID.randomUUID().toString();
        store.recordPurchase(userId, purchaseId, -price);
        store.addOwnership(userId, productId, requestId.toString(), purchaseId, price);
        return new Purchase(productId, balance - price, false);
    }

    @Transactional(readOnly = true)
    public List<PurchaseOrder> purchaseOrders(Long userId) {
        return store.purchaseOrders(userId);
    }

    /** Wears an owned artwork in its slot, or takes the slot off when {@code id} is null. */
    @Transactional
    public Appearance wearArtwork(Long userId, String slot, String id) {
        lockAccount(userId);
        Slot definition = slot == null ? null : DecorationSpec.SPEC.slots().get(slot);
        if (definition == null || !definition.wearable()) throw new BusinessException("该部位不能佩戴");
        store.clearArtworkSlot(userId, slot);
        if (id != null) {
            requireArtwork(slot, id);
            if (!store.ownsArtwork(userId, id)) throw new BusinessException(403, "请先拥有这件作品");
            store.equipArtwork(userId, slot, id);
        }
        return appearance(userId);
    }

    private SpaceArtwork requireArtwork(String slot, String id) {
        SpaceArtwork artwork = SpaceArtwork.isId(id) ? store.lockArtwork(id) : null;
        if (artwork == null || !artwork.slot().equals(slot)) throw new BusinessException(409, "作品不可用或部位不匹配");
        return artwork;
    }

    /**
     * Lists one artwork as a standalone product, or several artworks (at most one per slot) as a bundle.
     * Retrying the same request returns the same product.
     */
    @Transactional
    public String publishProduct(PublishProduct input) {
        String id = input.id();
        validateProductId(id);
        String name = validText(input.name(), "商品名称");
        validatePrice(input.price());
        List<String> ids = Objects.requireNonNullElse(input.artworkIds(), List.of());
        if (ids.isEmpty() || new HashSet<>(ids).size() != ids.size()) {
            throw new BusinessException("请选择要上架的作品，每件作品只能出现一次");
        }
        Map<String, String> bySlot = new LinkedHashMap<>();
        for (String artworkId : ids) {
            SpaceArtwork artwork = SpaceArtwork.isId(artworkId) ? store.lockArtwork(artworkId) : null;
            if (artwork == null) throw new BusinessException(404, "作品不存在或已撤回");
            if (bySlot.putIfAbsent(artwork.slot(), artwork.artworkId()) != null) {
                throw new BusinessException("套装中每个部位只能放一件作品");
            }
        }
        boolean standalone = bySlot.size() == 1;
        try {
            store.insertProduct(id, name, input.price());
        } catch (DuplicateKeyException duplicate) {
            Product existing = store.product(null, id);
            if (existing == null || !bySlot.equals(existing.artworks()) || standalone != (existing.standaloneArtworkId() != null)
                    || !name.equals(existing.name()) || existing.coinPrice() != input.price()) {
                throw new BusinessException(409, "商品编号已被使用");
            }
            return id;
        }
        try {
            bySlot.forEach((slot, artworkId) -> store.linkArtwork(id, slot, artworkId, standalone));
        } catch (DuplicateKeyException duplicate) {
            throw new BusinessException(409, "该作品已有单件商品");
        }
        return id;
    }

    /**
     * Saves an artwork for any ready slot. Every image is re-checked against its contract rule and must have been
     * uploaded by this admin. Retrying the same draft returns the same id.
     */
    @Transactional
    public String createArtwork(Long adminId, ArtworkDraft draft) {
        if (!SpaceArtwork.isId(draft.id())) throw new BusinessException("作品编号无效");
        Slot slot = DecorationSpec.SPEC.readySlot(draft.slot());
        String title = validText(draft.name(), "作品名称");
        String credit = validText(draft.artist(), "作者署名");
        Map<String, String> given = Objects.requireNonNullElse(draft.images(), Map.of());
        Set<String> expected = slot.images().stream().map(ImageField::key).collect(Collectors.toSet());
        if (!given.keySet().equals(expected)) throw new BusinessException("请上传该部位要求的全部图片");
        Map<String, String> images = new LinkedHashMap<>();
        Map<String, StoredImage> stored = new HashMap<>();
        for (ImageField field : slot.images()) {
            StoredImage image = files.requireDecorationImage(given.get(field.key()), DecorationSpec.SPEC.rules().get(field.rule()), adminId);
            images.put(field.key(), image.url());
            stored.put(field.key(), image);
        }
        Assets assets = new Assets(images, listItems(slot.list(), draft.items(), adminId));
        Map<String, Object> settings = validSettings(slot, draft.settings(), stored);
        try {
            store.insertArtwork(draft.id(), draft.slot(), title, credit, assets.encode(), SpaceArtwork.encodeSettings(settings));
        } catch (DuplicateKeyException duplicate) {
            SpaceArtwork existing = store.lockArtwork(draft.id());
            if (existing == null || !existing.slot().equals(draft.slot()) || !title.equals(existing.name())
                    || !credit.equals(existing.artist()) || !assets.equals(existing.assets())
                    || !settings.equals(existing.settings())) {
                throw new BusinessException(409, "作品编号已被使用");
            }
        }
        return draft.id();
    }

    private List<Item> listItems(ListField list, List<DraftItem> drafts, Long adminId) {
        List<DraftItem> given = Objects.requireNonNullElse(drafts, List.of());
        if (list == null) {
            if (!given.isEmpty()) throw new BusinessException("该部位不需要批量图片");
            return List.of();
        }
        if (given.size() < list.min() || given.size() > list.max()) {
            throw new BusinessException(list.label() + "数量须为 " + list.min() + " 到 " + list.max() + " 张");
        }
        Set<String> names = new HashSet<>();
        List<Item> items = new ArrayList<>();
        for (DraftItem draft : given) {
            String name = draft == null ? null : draft.name() == null ? null : draft.name().strip();
            if (name == null || name.isEmpty() || name.length() > list.nameMaxLength()) {
                throw new BusinessException(list.label() + "名称须为 1 到 " + list.nameMaxLength() + " 字");
            }
            if (!names.add(name)) throw new BusinessException(list.label() + "名称不能重复：" + name);
            StoredImage image = files.requireDecorationImage(draft.url(), DecorationSpec.SPEC.rules().get(list.rule()), adminId);
            // Keys are positional and permanent, so messages that reference an item keep resolving.
            items.add(new Item("%02d".formatted(items.size() + 1), name, image.url()));
        }
        return items;
    }

    private Map<String, Object> validSettings(Slot slot, Map<String, Object> drafts, Map<String, StoredImage> images) {
        Map<String, Object> given = Objects.requireNonNullElse(drafts, Map.of());
        Set<String> expected = slot.settings().stream().map(Setting::key).collect(Collectors.toSet());
        if (!given.keySet().equals(expected)) throw new BusinessException("请填写该部位的全部设置");
        Map<String, Object> settings = new LinkedHashMap<>();
        Map<String, Integer> sliced = new HashMap<>();
        for (Setting setting : slot.settings()) {
            Object value = given.get(setting.key());
            if ("slice".equals(setting.type())) {
                if (!(value instanceof Integer pixels) || pixels < 1) throw new BusinessException(setting.label() + "须为正整数");
                sliced.merge(setting.image() + ":" + setting.axis(), pixels, Integer::sum);
                settings.put(setting.key(), pixels);
            } else {
                if (!(value instanceof String color) || !color.matches("#[0-9a-fA-F]{6}")) {
                    throw new BusinessException(setting.label() + "须为 #RRGGBB 颜色");
                }
                settings.put(setting.key(), color.toLowerCase(Locale.ROOT));
            }
        }
        sliced.forEach((key, total) -> {
            String[] parts = key.split(":");
            StoredImage image = images.get(parts[0]);
            int length = "vertical".equals(parts[1]) ? image.height() : image.width();
            // At least one pixel has to remain in the middle so the image can stretch.
            if (total >= length) throw new BusinessException("不拉伸的边距之和必须小于图片的" + ("vertical".equals(parts[1]) ? "高度" : "宽度"));
        });
        return settings;
    }

    @Transactional
    public void editArtwork(String id, String name, String artist, Integer version) {
        validateVersion(version);
        if (store.editArtwork(id, validText(name, "作品名称"), validText(artist, "作者署名"), version) != 1) {
            throw artworkChanged();
        }
    }

    @Transactional
    public void withdrawArtwork(String id, Integer version) {
        validateVersion(version);
        SpaceArtwork artwork = store.lockArtwork(id);
        if (artwork == null || artwork.version() != version) throw artworkChanged();
        if (store.withdrawArtwork(id, version) != 1) {
            throw new BusinessException(409, "已出售的作品须保留。尚未出售时，请先下架关联商品");
        }
    }

    @Transactional(readOnly = true)
    public AdminCatalog adminCatalog() {
        return new AdminCatalog(store.allProducts(), store.artworks());
    }

    @Transactional
    public Product updateProduct(String id, ProductEdit edit) {
        validateProductId(id);
        String name = validText(edit.name(), "商品名称");
        validatePrice(edit.price());
        if (edit.listed() == null || edit.sortOrder() == null || edit.sortOrder() < 0 || edit.sortOrder() > 100000) {
            throw new BusinessException("商品状态或排序无效");
        }
        validateVersion(edit.version());
        Product product = store.product(null, id);
        if (product == null) throw new BusinessException(404, "装扮商品不存在");
        if (edit.listed()) {
            if (product.artworks().isEmpty()) throw new BusinessException("商品没有关联作品");
            product.artworks().forEach(this::requireArtwork);
        }
        ProductEdit normalized = new ProductEdit(name, edit.price(), edit.sortOrder(), edit.listed(), edit.version());
        if (store.updateProduct(id, normalized) != 1) throw new BusinessException(409, "商品已更新，请刷新后重试");
        return store.product(null, id);
    }

    @Transactional
    public Appearance replaceBanner(Long userId, String url) {
        lockAccount(userId);
        Appearance previous = appearance(userId);
        store.saveBanner(userId, url, 50, null);
        return previous;
    }

    @Transactional
    public Appearance updatePosition(Long userId, String expectedUrl, Integer position) {
        return updateView(userId, expectedUrl, legacyView(position));
    }

    static SpaceBannerView legacyView(Integer position) {
        if (position == null || position < 0 || position > 100) throw new BusinessException("头图位置必须在 0 到 100 之间");
        return SpaceBannerView.read(null, position);
    }

    @Transactional
    public Appearance updateView(Long userId, String expectedUrl, SpaceBannerView view) {
        String encoded = view.encode();
        lockAccount(userId);
        Appearance current = appearance(userId);
        if (current.spaceBannerUrl() == null || !current.spaceBannerUrl().equals(expectedUrl)) {
            throw new BusinessException(409, "头图已更换，请刷新后调整");
        }
        store.saveBannerPosition(userId, view.y(), encoded);
        return appearance(userId);
    }

    private BusinessException artworkChanged() {
        return new BusinessException(409, "作品已更新或已撤回，请刷新后重试");
    }

    private String validText(String value, String label) {
        if (value == null || value.isBlank() || value.strip().length() > MAX_TEXT) {
            throw new BusinessException(label + "须为 1 到 " + MAX_TEXT + " 字");
        }
        return value.strip();
    }

    private void validatePrice(Integer price) {
        if (price == null || price < 1) throw new BusinessException("硬币价格须大于零");
    }

    private void validateVersion(Integer version) {
        if (version == null || version < 0) throw new BusinessException("版本号无效，请刷新后重试");
    }

    private void validateProductId(String id) {
        if (id == null || !PRODUCT_ID.matcher(id).matches()) throw new BusinessException("商品编号无效");
    }

    private int lockAccount(Long userId) {
        Integer balance = store.lockWallet(userId);
        if (balance == null) throw new BusinessException(403, "账号不可用");
        return balance;
    }
}
