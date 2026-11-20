package com.easyjob.mapper;

import com.easyjob.vo.SpaceArtwork;
import com.easyjob.vo.SpaceCustomization.Appearance;
import com.easyjob.vo.SpaceCustomization.Product;
import com.easyjob.vo.SpaceCustomization.ProductEdit;
import com.easyjob.vo.SpaceCustomization.PurchaseOrder;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.util.Collection;
import java.util.List;

@Mapper
public interface SpaceSkinMapper {
    Appearance appearance(@Param("userId") Long userId);

    Integer balance(@Param("userId") Long userId);

    Integer lockWallet(@Param("userId") Long userId);

    /** Listed products plus every product the user owns. */
    List<Product> shopProducts(@Param("userId") Long userId);

    Product product(@Param("userId") Long userId, @Param("productId") String productId);

    Product lockProduct(@Param("userId") Long userId, @Param("productId") String productId);

    List<Product> allProducts();

    List<SpaceArtwork> artworks();

    List<SpaceArtwork> equippedArtworks(@Param("userId") Long userId);

    List<SpaceArtwork.Worn> wornArtworks(@Param("userIds") Collection<Long> userIds, @Param("slot") String slot);

    /** Artworks of {@code slot} granted by any product the user owns. */
    List<SpaceArtwork> ownedArtworks(@Param("userId") Long userId, @Param("slot") String slot);

    /** Artworks by id, including withdrawn ones, so content that already references them keeps rendering. */
    List<SpaceArtwork> artworksById(@Param("ids") Collection<String> ids);

    SpaceArtwork lockArtwork(@Param("id") String id);

    boolean ownsArtwork(@Param("userId") Long userId, @Param("id") String id);

    int editArtwork(@Param("id") String id, @Param("name") String name, @Param("artist") String artist,
                    @Param("version") int version);

    int withdrawArtwork(@Param("id") String id, @Param("version") int version);

    int insertArtwork(@Param("id") String id, @Param("slot") String slot, @Param("name") String name,
                      @Param("artist") String artist, @Param("assets") String assets, @Param("settings") String settings);

    int linkArtwork(@Param("product") String product, @Param("slot") String slot, @Param("artwork") String artwork,
                    @Param("single") boolean single);

    int clearArtworkSlot(@Param("userId") Long userId, @Param("slot") String slot);

    int equipArtwork(@Param("userId") Long userId, @Param("slot") String slot, @Param("id") String id);

    String productForRequest(@Param("userId") Long userId, @Param("requestId") String requestId);

    int addOwnership(@Param("userId") Long userId, @Param("productId") String productId,
                     @Param("requestId") String requestId, @Param("purchaseId") String purchaseId,
                     @Param("price") int price);

    int recordPurchase(@Param("userId") Long userId, @Param("purchaseId") String purchaseId,
                       @Param("delta") int delta);

    List<PurchaseOrder> purchaseOrders(@Param("userId") Long userId);

    int insertProduct(@Param("productId") String productId, @Param("name") String name, @Param("price") int price);

    int updateProduct(@Param("id") String id, @Param("edit") ProductEdit edit);

    int saveBanner(@Param("userId") Long userId, @Param("url") String url, @Param("position") int position,
                   @Param("view") String view);

    int saveBannerPosition(@Param("userId") Long userId, @Param("position") int position, @Param("view") String view);
}
